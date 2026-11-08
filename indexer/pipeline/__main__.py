"""Indexer Job entrypoint — extract -> clean -> chunk -> embed -> store.

Usage (in-cluster, via the indexer Job / reindex CronJob)::

    python -m pipeline [--corpus-dir corpus/raw] [--manifest corpus/MANIFEST.md]
                       [--chunk-size 512] [--chunk-overlap 64]

Input discovery, in order:
1. ``--corpus-dir`` (default ``corpus/raw``): every ``*.pdf``, ``*.md``
   and ``*.txt`` under it (Markdown/text files are indexed as single-page
   documents, page 1 — this is how the CI fixture corpus eval/fixtures/
   doc1-3.md is indexed).
2. ``--manifest`` (default ``corpus/MANIFEST.md``): if the corpus dir
   is empty/missing, PDF paths listed in the manifest are used
   (lines with a ``.pdf`` path; SHA-256 values are NOT re-verified
   here — the fetch script owns that — but a missing file is an error).

Idempotency: chunk ids are ``sha256(source + section + chunk_index)``
(``store.chunk_id``), so re-running the Job upserts the same ids
instead of duplicating chunks.

Superseded rule: the doc version is derived from the filename when
it names a version (``2023-08`` / ``Aug 2023`` -> superseded=True,
``2026-06`` / ``Jun 2026`` -> superseded=False); otherwise the
``--doc-version`` default (``2026-06``) applies and
``--superseded`` can override it explicitly.

Logging: one JSON object per line on stdout (assignment sec. 4.8),
each with ``stage``, ``event`` and a ``request_id``-style ``run_id``.
No secrets are ever logged. Exit code 0 = indexed, 2 = no input
documents found, 1 = any stage failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

from . import chunk as chunk_mod
from . import clean as clean_mod
from . import embed as embed_mod
from . import extract as extract_mod
from . import store as store_mod

RUN_ID = str(uuid.uuid4())


def _log(level: str, event: str, **fields: object) -> None:
    record = {
        "level": level,
        "stage": "indexer",
        "event": event,
        "run_id": RUN_ID,
        **fields,
    }
    print(
        json.dumps(record),
        file=sys.stderr if level in ("warning", "error") else sys.stdout,
    )


CURRENT_ANNUAL_REPORT_START = 2023  # Annual Report 2023-24 is the newest edition


def _version_from_filename(name: str) -> tuple[str, bool] | None:
    """Derive (doc_version, superseded) from a filename, if it names one.

    ``...2023-08...`` / ``...aug-2023...`` -> ("2023-08", True);
    ``...2026-06...`` / ``...jun-2026...`` -> ("2026-06", False).
    """
    low = name.lower()
    # Version pairs in the corpus (docs/CORPUS.md property 2): the EE learning
    # outcomes (12 PLOs before 2024, 11 from 2024) and the annual-report
    # editions. Older editions are superseded so the retriever's
    # `superseded: false` filter returns the current one (failure mode E).
    if "plos" in low and "before" in low:
        return ("pre-2024", True)
    if "plos" in low and "2024" in low:
        return ("2024+", False)
    report = re.search(r"annual[_ -]?report[_ -]?(\d{4})-(\d{2})", low)
    if report:
        start = int(report.group(1))
        return (
            f"{report.group(1)}-{report.group(2)}",
            start < CURRENT_ANNUAL_REPORT_START,
        )
    if (
        "2023-08" in low
        or "aug-2023" in low
        or "aug2023" in low
        or "2023" in low
        and "aug" in low
    ):
        return ("2023-08", True)
    if (
        "2026-06" in low
        or "jun-2026" in low
        or "jun2026" in low
        or "2026" in low
        and "jun" in low
    ):
        return ("2026-06", False)
    return None


SUPPORTED_SUFFIXES = (".pdf", ".md", ".txt", ".html", ".htm")


def discover_documents(corpus_dir: Path, manifest: Path | None) -> list[Path]:
    """Find indexable documents: corpus dir first, manifest second.

    Corpus dir: every *.pdf / *.md / *.txt under it (sorted). Plain-text
    fixtures (.md/.txt) are indexed as single-page documents (page 1).
    """
    if corpus_dir.is_dir():
        docs = sorted(
            p
            for p in corpus_dir.rglob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
        )
        if docs:
            return docs
    if manifest and manifest.is_file():
        pdfs: list[Path] = []
        for line in manifest.read_text(encoding="utf-8").splitlines():
            for token in re.split(r"\s+", line.strip()):
                if token.lower().endswith(SUPPORTED_SUFFIXES):
                    candidate = Path(token)
                    if candidate.is_file():
                        pdfs.append(candidate)
        return sorted(set(pdfs))
    return []


def discover_pdfs(corpus_dir: Path, manifest: Path | None) -> list[Path]:
    """Backwards-compatible alias: PDFs only (see discover_documents)."""
    return [
        p
        for p in discover_documents(corpus_dir, manifest)
        if p.suffix.lower() == ".pdf"
    ]


def index_document(
    pdf_path: Path,
    doc_version: str,
    superseded: bool,
    chunk_size: int,
    chunk_overlap: int,
    client=None,
    embed_fn=None,
) -> dict:
    """Run one document through extract -> clean -> chunk -> embed -> store.

    ``pdf_path`` is any supported document (PDF, .md or .txt — see
    ``extract_document``). Returns a stats dict. ``client``/``embed_fn``
    are injectable for tests (no network/model needed in unit tests).
    """
    source = pdf_path.name
    pages = extract_mod.extract_document(pdf_path)
    pages = clean_mod.clean_document(pages)
    doc = {
        "source": source,
        "doc_version": doc_version,
        "superseded": superseded,
        "pages": pages,
    }
    chunks = chunk_mod.chunk_document(
        doc, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    _log(
        "info",
        "document_chunked",
        source=source,
        chunks=len(chunks),
        doc_version=doc_version,
        superseded=superseded,
    )
    if not chunks:
        return {
            "source": source,
            "chunks": 0,
            "stored": 0,
            "original_tokens": 0,
            "stored_tokens": 0,
            "amplification": 0.0,
        }
    for c in chunks:
        c["source"] = source
        c["doc_version"] = doc_version
        c["superseded"] = superseded
    original_tokens = sum(chunk_mod.estimate_tokens(p.get("text") or "") for p in pages)
    stored_tokens = sum(chunk_mod.estimate_tokens(c["text"]) for c in chunks)
    texts = [embed_mod.document_text(source, c["section"], c["text"]) for c in chunks]
    embed = embed_fn or embed_mod.embed_texts
    embeddings = embed(texts)
    metadatas = [
        {
            "source": source,
            "section": c["section"],
            "page": int(c["page"]),
            "doc_version": doc_version,
            "superseded": bool(superseded),
        }
        for c in chunks
    ]
    stored = store_mod.store_chunks(
        chunks,
        embeddings,
        metadatas,
        model_name=embed_mod.get_model_name(),
        dimension=embed_mod.get_dimension(),
        client=client,
    )
    return {
        "source": source,
        "chunks": len(chunks),
        "stored": stored,
        "original_tokens": original_tokens,
        "stored_tokens": stored_tokens,
        "amplification": round(
            chunk_mod.storage_amplification(stored_tokens, original_tokens), 3
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RAHBAR indexer: extract -> clean -> chunk -> embed -> store."
    )
    parser.add_argument(
        "--corpus-dir",
        default=os.environ.get("CORPUS_DIR", "corpus/raw"),
        help="Directory of PDFs / .md / .txt files to index (default: corpus/raw)",
    )
    parser.add_argument(
        "--manifest",
        default=os.environ.get("MANIFEST", "corpus/MANIFEST.md"),
        help="Fallback manifest listing PDF paths (default: corpus/MANIFEST.md)",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=int(os.environ.get("CHUNK_SIZE", "512"))
    )
    parser.add_argument(
        "--chunk-overlap", type=int, default=int(os.environ.get("CHUNK_OVERLAP", "64"))
    )
    parser.add_argument(
        "--doc-version",
        default=os.environ.get("DOC_VERSION", "2026-06"),
        help="Default doc_version when the filename names none",
    )
    parser.add_argument(
        "--superseded",
        action="store_true",
        help="Mark all documents superseded (overrides filename rule)",
    )
    parser.add_argument(
        "--skip-cache-invalidation",
        action="store_true",
        help="Do not flush the Redis semantic cache after indexing",
    )
    args = parser.parse_args(argv)

    _log(
        "info",
        "index_start",
        corpus_dir=args.corpus_dir,
        manifest=args.manifest,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        embed_model=embed_mod.get_model_name(),
        dimension=embed_mod.get_dimension(),
        collection=store_mod.COLLECTION_NAME,
        chroma=f"{store_mod.CHROMA_HOST}:{store_mod.CHROMA_PORT}",
    )
    pdfs = discover_documents(Path(args.corpus_dir), Path(args.manifest))
    if not pdfs:
        _log(
            "error",
            "no_input_documents",
            corpus_dir=args.corpus_dir,
            manifest=args.manifest,
            hint="Run scripts/fetch_corpus.py first, or place PDFs / .md / .txt files in corpus/raw/",
        )
        return 2

    total_chunks = total_stored = total_orig = total_stored_tok = 0
    per_doc: list[dict] = []
    for pdf in pdfs:
        derived = _version_from_filename(pdf.name)
        doc_version, superseded = (
            derived if derived else (args.doc_version, args.superseded)
        )
        if args.superseded:
            superseded = True
        try:
            stats = index_document(
                pdf, doc_version, superseded, args.chunk_size, args.chunk_overlap
            )
        except Exception as exc:  # noqa: BLE001 — a document indexing failure aborts the batch
            _log("error", "document_failed", source=pdf.name, error=str(exc))
            return 1
        per_doc.append(stats)
        total_chunks += stats["chunks"]
        total_stored += stats["stored"]
        total_orig += stats["original_tokens"]
        total_stored_tok += stats["stored_tokens"]

    if not args.skip_cache_invalidation:
        store_mod.invalidate_semantic_cache()
    _log(
        "info",
        "index_done",
        documents=len(pdfs),
        chunks=total_chunks,
        stored=total_stored,
        original_tokens=total_orig,
        stored_tokens=total_stored_tok,
        storage_amplification=round(
            chunk_mod.storage_amplification(total_stored_tok, total_orig), 3
        ),
        per_document=per_doc,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
