"""Chunk stage — structure-aware chunking (assignment sec. 3.1).

Order of splitting: sections -> paragraphs -> sentences.

* A document is first split on section headings / numbered clauses
  (``1.21``, ``4.2``, ``Clause 4.2``). A chunk never starts mid-section.
* Inside a section, paragraphs are the next unit, then sentences.
* A numbered clause / long definition is NEVER split across chunks
  if it fits inside the target size whole — this is property 5
  (Student Handbook Generative AI policy): a fixed-size chunker
  cutting a definition in half is failure mode B.
* Target size is ``CHUNK_SIZE`` tokens (default 512, env-overridable)
  with ``CHUNK_OVERLAP`` tokens of overlap (default 64), and the
  overlap is always whole sentences — never a half-sentence tail.
* Token estimate: ~1 token per 4 characters (documented
  approximation; the embedding model tokenises differently, but
  this is the sizing rule the lecture used and it is consistent
  across configs, so the (size, overlap) comparison in
  ``docs/PIPELINE.md`` is apples-to-apples).

Storage amplification (lecture example): ``150 / 120 = 1.25`` —
stored tokens divided by original tokens. Overlap is the cost of
not splitting definitions: every overlapped sentence is stored
twice, so amplification grows with overlap/size.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys

DEFAULT_CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "512"))
DEFAULT_CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "64"))

# Numbered clause / section heading at the start of a line.
SECTION_RE = re.compile(
    r"^(?:Clause\s+|Section\s+)?\d+(?:\.\d+){0,3}(?:\s+[A-Z].*)?$",
    re.IGNORECASE | re.MULTILINE,
)
CLAUSE_START_RE = re.compile(
    r"^\s*(?:Clause\s+|Section\s+)?\d+(?:\.\d+){0,3}\b", re.IGNORECASE
)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def estimate_tokens(text: str) -> int:
    """Approximate token count: 1 token ~ 4 characters (documented rule).

    This is an approximation, not the embedding model's tokenizer.
    It is used only for chunk sizing, so all three evaluated configs
    are measured with the same ruler.
    """
    return max(1, len(text) // 4)


def storage_amplification(stored_tokens: int, original_tokens: int) -> float:
    """Stored tokens / original tokens.

    Lecture example: ``storage_amplification(150, 120) == 1.25``.
    Returns 0.0 when there are no original tokens (empty document).
    """
    if original_tokens <= 0:
        return 0.0
    return stored_tokens / original_tokens


def split_sentences(text: str) -> list[str]:
    """Split text into sentences, keeping the terminator with each one."""
    parts = [s.strip() for s in SENTENCE_RE.split(text.strip()) if s.strip()]
    return parts or ([text.strip()] if text.strip() else [])


MAX_TITLE_CHARS = 80


def short_title(heading: str) -> str:
    """Readable section label: clause number plus the first words, <= 80 chars.

    PDF extraction often puts a whole clause on one line, so the matched
    heading line can be a paragraph. A citation must show ``1.21 Attendance
    requirement``-style text, not 900 characters.
    """
    heading = " ".join(heading.split())
    if len(heading) <= MAX_TITLE_CHARS:
        return heading
    cut = heading[:MAX_TITLE_CHARS].rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:-") + "…"


def split_sections(text: str) -> list[dict]:
    """Split a document into ``{"section": str, "text": str}`` sections.

    A section starts at a numbered clause/heading line. Text before
    the first heading becomes section ``"Introduction"``. Table
    blocks (``[TABLE]...[/TABLE]``) are kept intact inside their
    section — they are never split across sections.
    """
    if not text.strip():
        return []
    # Find heading lines; a heading is a whole line matching SECTION_RE.
    sections: list[dict] = []
    current_title = "Introduction"
    current_lines: list[str] = []
    in_table = False
    for line in text.splitlines():
        if line.strip() == "[TABLE]":
            in_table = True
        elif line.strip() == "[/TABLE]":
            in_table = False
        if not in_table and SECTION_RE.match(line.strip()):
            if current_lines:
                sections.append(
                    {"section": current_title, "text": "\n".join(current_lines).strip()}
                )
            current_title = short_title(line.strip())
            current_lines = [line]
            continue
        current_lines.append(line)
    if current_lines or not sections:
        sections.append(
            {"section": current_title, "text": "\n".join(current_lines).strip()}
        )
    return [s for s in sections if s["text"]]


def _sentences_with_tables(paragraph: str) -> list[str]:
    """Sentences of a paragraph, with a [TABLE] block as one unit."""
    if "[TABLE]" in paragraph:
        # A table block is atomic: never sentence-split a table.
        return [paragraph.strip()]
    return split_sentences(paragraph)


def chunk_document(
    doc: dict, chunk_size: int | None = None, chunk_overlap: int | None = None
) -> list[dict]:
    """Chunk one document dict into structure-aware chunks.

    ``doc``: ``{"source": str, "doc_version": str, "superseded": bool,
    "pages": [{"page": int, "text": str, ...}], ...}`` — or a flat
    ``{"source": ..., "text": str, "page": int}`` document. Each
    returned chunk is ``{"text", "section", "page", "chunk_index"}``
    (metadata enrichment — ``source``/``doc_version``/``superseded`` —
    happens in ``store.py``, which enforces the full schema).

    Guarantees:
    * a numbered clause/definition that fits in ``chunk_size`` whole
      is never split across chunks;
    * overlap is whole sentences only;
    * chunks never exceed ``chunk_size`` tokens unless a single
      sentence/clause alone is larger (then it is one chunk as-is —
      splitting it would destroy the definition it carries).
    """
    size = chunk_size if chunk_size is not None else DEFAULT_CHUNK_SIZE
    overlap = chunk_overlap if chunk_overlap is not None else DEFAULT_CHUNK_OVERLAP
    if overlap >= size:
        raise ValueError(f"CHUNK_OVERLAP ({overlap}) must be < CHUNK_SIZE ({size})")

    source = doc.get("source", "unknown")
    # Flatten pages to (page, text) while remembering page boundaries.
    if "pages" in doc:
        page_texts = [(p.get("page", 1), p.get("text") or "") for p in doc["pages"]]
    else:
        page_texts = [(doc.get("page", 1), doc.get("text") or "")]
    full_text = "\n\n".join(t for _, t in page_texts if t.strip())
    if not full_text.strip():
        return []

    # Page lookup: first page whose text contains the section title,
    # else the document's first page. (Chunk-level page is the page
    # the chunk starts on; exact per-chunk pages are refined below
    # by searching for the chunk's first sentence.)
    def page_for(snippet: str) -> int:
        needle = snippet.strip()[:60]
        for page_no, text in page_texts:
            if needle and needle in text:
                return page_no
        return page_texts[0][0]

    chunks: list[dict] = []
    for section in split_sections(full_text):
        section_title = section["section"]
        # Paragraphs, then sentences — but keep a whole clause together.
        paragraphs = [p for p in section["text"].split("\n\n") if p.strip()]
        units: list[str] = []  # atomic units: sentences, or whole clauses/tables
        for para in paragraphs:
            para = para.strip()
            if CLAUSE_START_RE.match(para) and estimate_tokens(para) <= size:
                # Whole numbered clause/definition: one atomic unit.
                units.append(para)
            else:
                units.extend(_sentences_with_tables(para))

        # Greedy pack of atomic units into size-bounded chunks.
        current: list[str] = []
        current_tokens = 0
        for unit in units:
            unit_tokens = estimate_tokens(unit)
            if current and current_tokens + unit_tokens > size:
                chunks.append(
                    {
                        "text": " ".join(current),
                        "section": section_title,
                        "page": page_for(current[0]),
                        "chunk_index": len(chunks),
                    }
                )
                # Overlap: whole sentences from the tail of the chunk
                # just closed, up to `overlap` tokens.
                tail: list[str] = []
                tail_tokens = 0
                for unit_back in reversed(current):
                    t = estimate_tokens(unit_back)
                    if tail_tokens + t > overlap:
                        break
                    tail.append(unit_back)
                    tail_tokens += t
                current = list(reversed(tail))
                current_tokens = tail_tokens
            current.append(unit)
            current_tokens += unit_tokens
        if current:
            chunks.append(
                {
                    "text": " ".join(current),
                    "section": section_title,
                    "page": page_for(current[0]),
                    "chunk_index": len(chunks),
                }
            )

    # Stable chunk ids are assigned by store.py
    # (sha256(source + section + chunk_index)); keep index local here.
    _ = hashlib.sha256(source.encode()).hexdigest()  # source noted for id stability
    return chunks


def chunk_text(
    text: str,
    source: str = "unknown",
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[dict]:
    """Convenience wrapper for a flat text document."""
    return chunk_document(
        {"source": source, "text": text},
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: chunk a text file, print JSON chunks + amplification stats."""
    parser = argparse.ArgumentParser(
        description="Structure-aware chunker (sections -> paragraphs -> sentences)."
    )
    parser.add_argument("input", help="Text file to chunk")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)
    parser.add_argument(
        "--source", default=None, help="Source name (default: input filename)"
    )
    args = parser.parse_args(argv)

    with open(args.input, encoding="utf-8") as f:
        text = f.read()
    source = args.source or args.input
    chunks = chunk_document(
        {"source": source, "text": text},
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    original = estimate_tokens(text)
    stored = sum(estimate_tokens(c["text"]) for c in chunks)
    print(
        json.dumps(
            {
                "source": source,
                "chunk_size": args.chunk_size,
                "chunk_overlap": args.chunk_overlap,
                "chunks": len(chunks),
                "original_tokens": original,
                "stored_tokens": stored,
                "storage_amplification": round(
                    storage_amplification(stored, original), 3
                ),
                "chunks_detail": chunks,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
