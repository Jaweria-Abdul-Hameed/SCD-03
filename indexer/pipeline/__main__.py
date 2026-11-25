"""Indexer Job entrypoint — extract -> verify -> data lake -> chunk -> embed -> store.

Implements Assignment 03 Part A1 & A2 (Paper §§4.2.1-4.2.4, Fig. 3 Stages 1-4):
  1. Extract raw document pages (and catch extraction/corruption errors).
  2. Verify every document BEFORE chunking on four checks:
     quality, completeness, recency, uniqueness (hash + embedding cosine).
  3. Quarantine failing documents (never chunked or indexed) and emit a
     per-run verification report.
  4. Update the versioned Data Lake + archive superseded versions, then
     incrementally update ChromaDB:
       - Unchanged corpus -> 0 chunks embedded.
       - Changed document -> replaces only its own chunks.
       - Deleted document -> removes all chunks (0 orphans verified by doc count).
       - Superseded version -> archived on PVC & marked superseded=True.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import chunk as chunk_mod
from . import clean as clean_mod
from . import datalake as dl_mod
from . import embed as embed_mod
from . import extract as extract_mod
from . import store as store_mod
from . import verify as verify_mod

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
    """Find indexable documents: corpus dir first, manifest second."""
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
    pages_override: list[dict] | None = None,
) -> dict:
    """Run one verified document through clean -> chunk -> embed -> store."""
    source = pdf_path.name
    pages = (
        pages_override
        if pages_override is not None
        else extract_mod.extract_document(pdf_path)
    )
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
            "chunk_ids": [],
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
    ids = [
        store_mod.chunk_id(source, c["section"], c.get("chunk_index", i))
        for i, c in enumerate(chunks)
    ]
    return {
        "source": source,
        "chunks": len(chunks),
        "stored": stored,
        "chunk_ids": ids,
        "original_tokens": original_tokens,
        "stored_tokens": stored_tokens,
        "amplification": round(
            chunk_mod.storage_amplification(stored_tokens, original_tokens), 3
        ),
    }


def _sort_oldest_first(paths: list[Path], default_version: str) -> list[Path]:
    """Process older versions before newer ones in the same batch so recency archives old."""

    def key_fn(p: Path) -> tuple[tuple[int, ...], str]:
        hint = _version_from_filename(p.name)
        ver = hint[0] if hint else default_version
        return (verify_mod.version_sort_key(ver, None), p.name.lower())

    return sorted(paths, key=key_fn)


def run_ingestion(
    corpus_dir: Path,
    manifest: Path | None,
    chunk_size: int,
    chunk_overlap: int,
    default_doc_version: str = "2026-06",
    force_superseded: bool = False,
    data_root: Path | None = None,
    near_dup_threshold: float = verify_mod.DEFAULT_NEAR_DUP_THRESHOLD,
    additive: bool = False,
    sync_deletes: bool = True,
    skip_cache_invalidation: bool = False,
    report_out: Path | None = None,
    client=None,
    embed_fn=None,
) -> dict[str, Any]:
    """Execute full Part A1 + A2 ingestion pipeline and return structured summary."""
    docs = discover_documents(corpus_dir, manifest)
    if not docs and not (sync_deletes and not additive):
        return {"exit_code": 2, "error": "no_input_documents"}

    lake = dl_mod.DataLakeStore(data_root)
    if client is None:
        client = store_mod.get_chroma_client()
    embed = embed_fn or embed_mod.embed_texts
    embed_model = embed_mod.get_model_name()

    # Track which active sources came from this corpus_dir for delete detection
    ordered_docs = _sort_oldest_first(docs, default_doc_version)
    seen_sources: set[str] = {p.name for p in ordered_docs}

    counts = {
        "docs_scanned": len(ordered_docs),
        "docs_passed": 0,
        "docs_quarantined": 0,
        "docs_skipped_unchanged": 0,
        "docs_added": 0,
        "docs_updated": 0,
        "docs_superseded_archived": 0,
        "docs_deleted": 0,
        "chunks_embedded": 0,
        "chunks_deleted": 0,
    }
    verification_entries: list[dict[str, Any]] = []
    per_doc_stats: list[dict[str, Any]] = []

    for doc_path in ordered_docs:
        derived = _version_from_filename(doc_path.name)
        hinted_ver = derived[0] if derived else default_doc_version
        pages: list[dict] = []
        extraction_error: str | None = None
        try:
            pages = extract_mod.extract_document(doc_path)
        except Exception as exc:  # noqa: BLE001 — bad file caught by A1 verification
            extraction_error = str(exc)

        meta, pages = verify_mod.extract_document_metadata(
            doc_path,
            pages,
            default_version=default_doc_version,
            version_hint=derived,
        )
        source = str(meta.get("source") or doc_path.name)
        seen_sources.add(source)
        doc_id = str(
            meta.get("doc_id") or verify_mod.derive_doc_id(doc_path.name, meta)
        )
        doc_version = str(meta.get("version") or meta.get("date") or hinted_ver)
        superseded_flag = bool(force_superseded or (derived[1] if derived else False))

        # Already-archived superseded edition in an unchanged corpus re-run:
        # do not re-quarantine or re-embed it.
        prev_rec = lake.find_record(doc_id=doc_id, version=doc_version, source=source)
        cur_hash = (
            verify_mod.compute_content_hash(pages)
            if pages and not extraction_error
            else ""
        )
        if (
            prev_rec is not None
            and prev_rec.get("status") == "archived_superseded"
            and cur_hash
            and prev_rec.get("content_hash") == cur_hash
        ):
            counts["docs_passed"] += 1
            counts["docs_skipped_unchanged"] += 1
            verification_entries.append(
                {
                    "source": source,
                    "file_path": str(doc_path),
                    "doc_id": doc_id,
                    "version": doc_version,
                    "content_hash": cur_hash,
                    "checks": {
                        "quality": {
                            "pass": True,
                            "reason": "ok: matches archived verified copy",
                        },
                        "completeness": {
                            "pass": True,
                            "reason": "ok: matches archived verified copy",
                        },
                        "recency": {
                            "pass": True,
                            "reason": f"ok: previously archived as superseded ({doc_version})",
                        },
                        "uniqueness": {
                            "pass": True,
                            "reason": "ok: unchanged archived copy",
                        },
                    },
                    "overall_pass": True,
                    "disposition": "skipped_archived_unchanged",
                }
            )
            continue

        # Check A2 unchanged fast-path ONLY after A1 checks pass!
        report_entry, doc_embedding, superseded_target = verify_mod.verify_document(
            path=doc_path,
            pages=pages,
            meta=meta,
            active_records=lake.active_records(),
            embed_fn=embed,
            near_dup_threshold=near_dup_threshold,
            extraction_error=extraction_error,
        )

        if not report_entry["overall_pass"]:
            counts["docs_quarantined"] += 1
            fail_reasons = [
                f"{k}: {v['reason']}"
                for k, v in report_entry["checks"].items()
                if not v["pass"]
            ]
            reason_str = "; ".join(fail_reasons)
            q_path = lake.quarantine_file(doc_path, RUN_ID, reason_str)
            report_entry["disposition"] = "quarantined"
            report_entry["quarantine_path"] = str(q_path)
            verification_entries.append(report_entry)
            _log(
                "warning",
                "document_quarantined",
                source=source,
                reasons=fail_reasons,
                quarantine_path=str(q_path),
            )
            continue

        counts["docs_passed"] += 1
        existing_active = lake.find_active_by_source(source)
        content_hash = report_entry["content_hash"]

        # Unchanged check: same source + doc_id + version + hash + chunking + embed model
        if (
            existing_active is not None
            and existing_active.get("doc_id") == doc_id
            and existing_active.get("version") == doc_version
            and existing_active.get("content_hash") == content_hash
            and existing_active.get("chunk_size") == chunk_size
            and existing_active.get("chunk_overlap") == chunk_overlap
            and existing_active.get("embed_model") == embed_model
        ):
            counts["docs_skipped_unchanged"] += 1
            report_entry["disposition"] = "skipped_unchanged"
            verification_entries.append(report_entry)
            _log(
                "info",
                "document_skipped_unchanged",
                source=source,
                chunks_embedded=0,
            )
            continue

        # Handle superseded previous active version of same doc_id
        if superseded_target is not None:
            old_source = superseded_target["source"]
            old_ver = superseded_target["version"]
            lake.archive_version(
                doc_id=doc_id, version=old_ver, superseded_by=doc_version
            )
            store_mod.set_document_superseded(
                source=old_source,
                superseded=True,
                doc_version=old_ver,
                client=client,
            )
            counts["docs_superseded_archived"] += 1

        # Handle changed existing document (same source, changed content/config)
        is_update = existing_active is not None
        if existing_active is not None:
            deleted_old = store_mod.delete_document_chunks(
                source=source,
                chunk_ids=existing_active.get("chunk_ids"),
                client=client,
            )
            counts["chunks_deleted"] += deleted_old

        stats = index_document(
            doc_path,
            doc_version=doc_version,
            superseded=superseded_flag,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            client=client,
            embed_fn=embed,
            pages_override=pages,
        )
        per_doc_stats.append(stats)
        counts["chunks_embedded"] += stats["chunks"]
        if is_update:
            counts["docs_updated"] += 1
            report_entry["disposition"] = "updated"
        elif superseded_target is not None:
            counts["docs_added"] += 1
            report_entry["disposition"] = "indexed_superseding"
        else:
            counts["docs_added"] += 1
            report_entry["disposition"] = "indexed"

        lake.store_verified(
            src_path=doc_path,
            doc_id=doc_id,
            version=doc_version,
            content_hash=content_hash,
            chunk_ids=stats["chunk_ids"],
            doc_embedding=doc_embedding,
            meta=meta,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embed_model=embed_model,
        )
        verification_entries.append(report_entry)

    # Handle deletions when scanning the primary corpus directory (not additive Batch B)
    if sync_deletes and not additive:
        for rec in list(lake.active_records()):
            # Only delete records whose origin was this corpus_dir (or non-batch_b)
            origin = rec.get("origin_dir")
            if origin and Path(origin).resolve() != corpus_dir.resolve():
                continue
            if rec["source"] not in seen_sources:
                removed = store_mod.delete_document_chunks(
                    source=rec["source"],
                    chunk_ids=rec.get("chunk_ids"),
                    client=client,
                )
                lake.mark_deleted(rec["source"])
                counts["docs_deleted"] += 1
                counts["chunks_deleted"] += removed
                verification_entries.append(
                    {
                        "source": rec["source"],
                        "doc_id": rec["doc_id"],
                        "version": rec["version"],
                        "disposition": "deleted_from_corpus",
                        "chunks_deleted": removed,
                    }
                )
    else:
        # Tag origin_dir for active records added in additive mode so future non-additive
        # sync on base corpus_dir doesn't mistakenly delete additive Batch B docs.
        for rec in lake.active_records():
            if "origin_dir" not in rec:
                rec["origin_dir"] = str(corpus_dir)

    for rec in lake.active_records():
        if rec["source"] in seen_sources and "origin_dir" not in rec:
            rec["origin_dir"] = str(corpus_dir)

    lake.save()

    if not skip_cache_invalidation and (
        counts["chunks_embedded"] > 0
        or counts["chunks_deleted"] > 0
        or counts["docs_superseded_archived"] > 0
    ):
        store_mod.invalidate_semantic_cache()

    chunk_counts = store_mod.chunk_counts_by_document(client=client)
    report = {
        "run_id": RUN_ID,
        "timestamp": datetime.now(UTC).isoformat(),
        "corpus_dir": str(corpus_dir),
        "additive": additive,
        "embed_model": embed_model,
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "counts": counts,
        "documents": verification_entries,
        "vector_store_chunks_by_document": chunk_counts,
    }
    ts_path, latest_path = lake.write_verification_report(RUN_ID, report)
    if report_out is not None:
        report_out.parent.mkdir(parents=True, exist_ok=True)
        report_out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    _log(
        "info",
        "index_done",
        counts=counts,
        report_path=str(ts_path),
        latest_report_path=str(latest_path),
        chunks_embedded=counts["chunks_embedded"],
        total_vector_chunks=sum(chunk_counts.values()),
    )
    report["exit_code"] = 0
    report["report_path"] = str(ts_path)
    return report


def _print_summary(report: dict[str, Any]) -> None:
    c = report["counts"]
    print("\n=== VERIFICATION & INCREMENTAL INGESTION REPORT ===")
    print(f"Run ID      : {report['run_id']}")
    print(f"Corpus Dir  : {report['corpus_dir']} (additive={report['additive']})")
    print(
        f"Counts      : scanned={c['docs_scanned']} passed={c['docs_passed']} "
        f"quarantined={c['docs_quarantined']} unchanged_skipped={c['docs_skipped_unchanged']} "
        f"added={c['docs_added']} updated={c['docs_updated']} "
        f"superseded_archived={c['docs_superseded_archived']} deleted={c['docs_deleted']}"
    )
    print(
        f"Chunks      : embedded={c['chunks_embedded']} deleted={c['chunks_deleted']} "
        f"total_in_store={sum(report['vector_store_chunks_by_document'].values())}"
    )
    print("-" * 88)
    for entry in report["documents"]:
        disp = entry.get("disposition", "?")
        src = entry.get("source", "?")
        if "checks" not in entry:
            print(f"[{disp}] {src} (chunks_deleted={entry.get('chunks_deleted', 0)})")
            continue
        status = "PASS" if entry["overall_pass"] else "FAIL"
        print(
            f"[{status} -> {disp}] {src} (doc_id={entry['doc_id']}, ver={entry['version']})"
        )
        for cname in ("quality", "completeness", "recency", "uniqueness"):
            chk = entry["checks"][cname]
            mark = "PASS" if chk["pass"] else "FAIL"
            print(f"    {cname:13s}: {mark} | {chk['reason']}")
    print("=" * 88)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="RAHBAR RAGOps indexer: extract -> verify -> datalake -> chunk -> embed -> store."
    )
    parser.add_argument(
        "--corpus-dir",
        default=os.environ.get("CORPUS_DIR", "corpus/raw"),
        help="Directory of PDFs / .md / .txt / .html files to ingest",
    )
    parser.add_argument(
        "--manifest",
        default=os.environ.get("MANIFEST", "corpus/MANIFEST.md"),
        help="Fallback manifest listing document paths",
    )
    parser.add_argument(
        "--data-root",
        default=os.environ.get("DATA_LAKE_ROOT", "corpus"),
        help="Root directory for datalake/, quarantine/, archive/, reports/",
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
        help="Default doc_version when metadata/filename names none",
    )
    parser.add_argument(
        "--near-dup-threshold",
        type=float,
        default=float(
            os.environ.get(
                "NEAR_DUP_THRESHOLD", str(verify_mod.DEFAULT_NEAR_DUP_THRESHOLD)
            )
        ),
    )
    parser.add_argument(
        "--superseded",
        action="store_true",
        help="Force mark ingested documents superseded",
    )
    parser.add_argument(
        "--additive",
        action="store_true",
        help="Add batch on top of existing Data Lake without treating missing files as deleted",
    )
    parser.add_argument(
        "--no-sync-deletes",
        action="store_true",
        help="Do not delete chunks for active documents missing from --corpus-dir",
    )
    parser.add_argument(
        "--skip-cache-invalidation",
        action="store_true",
        help="Do not flush the Redis semantic cache after indexing",
    )
    parser.add_argument(
        "--report-out",
        default=None,
        help="Optional extra path to save the verification report JSON",
    )
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print human-readable verification & incremental counts table",
    )
    args = parser.parse_args(argv)

    _log(
        "info",
        "index_start",
        corpus_dir=args.corpus_dir,
        manifest=args.manifest,
        data_root=args.data_root,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        embed_model=embed_mod.get_model_name(),
        dimension=embed_mod.get_dimension(),
        collection=store_mod.COLLECTION_NAME,
        chroma=f"{store_mod.CHROMA_HOST}:{store_mod.CHROMA_PORT}",
    )

    report = run_ingestion(
        corpus_dir=Path(args.corpus_dir),
        manifest=Path(args.manifest) if args.manifest else None,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        default_doc_version=args.doc_version,
        force_superseded=args.superseded,
        data_root=Path(args.data_root),
        near_dup_threshold=args.near_dup_threshold,
        additive=args.additive,
        sync_deletes=not args.no_sync_deletes,
        skip_cache_invalidation=args.skip_cache_invalidation,
        report_out=Path(args.report_out) if args.report_out else None,
    )
    if report.get("exit_code") == 2:
        _log(
            "error",
            "no_input_documents",
            corpus_dir=args.corpus_dir,
            manifest=args.manifest,
        )
        return 2
    if args.print_summary or os.environ.get("PRINT_VERIFICATION_SUMMARY", "1") == "1":
        _print_summary(report)
    return int(report.get("exit_code", 0))


if __name__ == "__main__":
    sys.exit(main())
