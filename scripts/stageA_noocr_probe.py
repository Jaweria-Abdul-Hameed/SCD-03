"""Failure-analysis stage A: index the scanned PDF WITHOUT OCR (measured).

Runs in the indexer image (``python /probe.py``) against the corpus PVC. It
extracts + chunks the scanned policy twice -- OCR on, OCR forced off -- and
prints characters / chunks / first 120 characters, so the symptom ("0 chunks,
the document is invisible to retrieval") is a measurement, not a story.
"""

import json
import sys

sys.path.insert(0, "/app")
from pipeline import chunk as chunk_mod
from pipeline import extract as extract_mod

PDFS = [
    "/corpus/raw/Faculty_Entrepreneurship_Technical_Startups_Policy.pdf",
    "/corpus/raw/Undergraduate_Academic_Rules_Aug_2023.pdf",
]


def run(path: str, ocr: bool) -> dict:
    original = extract_mod._ocr_page
    if not ocr:

        def _off(*_a, **_k):
            raise RuntimeError("OCR disabled for the failure-analysis experiment")

        extract_mod._ocr_page = _off
    try:
        pages = extract_mod.extract_pdf(path)
    finally:
        extract_mod._ocr_page = original
    chars = sum(len(p["text"]) for p in pages)
    chunks = chunk_mod.chunk_document(
        {"source": path.rsplit("/", 1)[-1], "pages": pages}, 512, 64
    )
    first = next((p["text"] for p in pages if p["text"].strip()), "")[:120].replace(
        "\n", " "
    )
    return {
        "ocr": ocr,
        "pages": len(pages),
        "chars": chars,
        "chunks": len(chunks),
        "first_120_chars": first,
    }


if __name__ == "__main__":
    out = {p.rsplit("/", 1)[-1]: [run(p, True), run(p, False)] for p in PDFS}
    print(json.dumps(out, indent=1))
