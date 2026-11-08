"""Extract stage — PDF -> per-page text (RAHBAR, assignment sec. 3.1).

Contract
--------
``extract_pdf(path)`` returns a list of dicts, one per page::

    {"page": int, "text": str, "is_scanned": bool, "ocr_used": bool}

* Text layer first: PyMuPDF (``fitz``) when installed, else ``pypdf``.
* Automatic image-only detection: a page is scanned when it yields
  fewer than 20 extractable characters **or** reports no fonts
  (``pdffonts``-style check: an empty font list means a scan — see
  ``docs/CORPUS.md`` property 3, Faculty Entrepreneurship policy).
* OCR fallback for scanned pages via ``pytesseract`` + ``pdf2image``/
  poppler when available. When OCR tooling is absent the page is
  **never dropped silently and never crashes the Job**: it is kept
  with empty text, ``ocr_used=False``, and a clear warning naming
  the page is logged; the loss is surfaced again in
  ``docs/PIPELINE.md`` ("what could not be recovered").
* Repeating headers/footers (a line appearing on >80% of pages) are
  stripped, but headings and section boundaries are preserved:
  numbered clauses such as ``1.21`` / ``4.2`` and heading lines are
  never treated as headers/footers.

No secrets. No network access. Pure extraction.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# A page with fewer extractable characters than this is treated as
# image-only (scanned) and sent to the OCR fallback.
SCANNED_CHAR_THRESHOLD = 20
# A line repeated on more than this fraction of pages is a header/footer.
HEADER_FOOTER_FRACTION = 0.80

# Numbered clause / section heading, e.g. "1.21 Attendance", "4.2 Registration",
# "Clause 4.2", "Section 3.1". These are structure, never headers/footers.
CLAUSE_RE = re.compile(
    r"^\s*(?:Clause\s+|Section\s+)?\d+(?:\.\d+){0,3}\b", re.IGNORECASE
)
HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+){0,3}\s+)?[A-Z][A-Za-z0-9 ,&'’\-()]{3,80}$"
)


def _log(level: str, event: str, **fields: object) -> None:
    record = {"level": level, "stage": "extract", "event": event, **fields}
    print(
        json.dumps(record),
        file=sys.stderr if level in ("warning", "error") else sys.stdout,
    )


def _extract_with_fitz(path: Path) -> list[dict]:
    """Per-page text + font info via PyMuPDF. Returns raw page dicts."""
    import fitz  # PyMuPDF; imported lazily so `clean`/`chunk` stay importable

    pages: list[dict] = []
    with fitz.open(path) as doc:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            try:
                fonts = page.get_fonts()
            except Exception:  # noqa: BLE001 — fonts list extraction may fail on malformed PDF
                fonts = []
            pages.append({"page": i, "text": text, "fonts": fonts})
    return pages


def _extract_with_pypdf(path: Path) -> list[dict]:
    """Fallback extractor when PyMuPDF is not installed."""
    from pypdf import PdfReader  # lazy import

    pages: list[dict] = []
    reader = PdfReader(str(path))
    for i, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 — a corrupt page must not kill the Job
            _log(
                "warning",
                "page_extract_failed",
                source=str(path),
                page=i,
                error=str(exc),
            )
            text = ""
        # pypdf exposes no per-page font list; an empty text layer is
        # the only scan signal available on this path.
        pages.append({"page": i, "text": text, "fonts": None})
    return pages


def _ocr_page(path: Path, page_number: int) -> str:
    """OCR one page. Raises RuntimeError with a clear reason if unavailable."""
    try:
        import pytesseract
        from pdf2image import convert_from_path  # needs poppler-utils
    except ImportError as exc:
        raise RuntimeError(
            f"OCR tooling unavailable (pytesseract/pdf2image): {exc}"
        ) from exc
    images = convert_from_path(
        str(path), first_page=page_number, last_page=page_number, dpi=300
    )
    if not images:
        raise RuntimeError(f"pdf2image produced no image for page {page_number}")
    return pytesseract.image_to_string(images[0])


def _is_scanned(raw_page: dict) -> bool:
    """Image-only detection: <20 extractable chars OR no fonts (when known)."""
    text = (raw_page.get("text") or "").strip()
    if len(text) < SCANNED_CHAR_THRESHOLD:
        return True
    fonts = raw_page.get("fonts")
    return bool(fonts is not None and len(fonts) == 0 and len(text) < 200)


def _strip_repeating_headers_footers(pages: list[dict]) -> list[dict]:
    """Remove lines repeated on >80% of pages; keep clauses/headings.

    A line is only a header/footer candidate if it is NOT a numbered
    clause or a heading — a clause number that legitimately repeats
    (e.g. a running "Clause 4.2" cross-reference) must survive.
    """
    if len(pages) < 3:
        return pages
    line_counts: dict[str, int] = {}
    for page in pages:
        seen: set[str] = set()
        for line in (page["text"] or "").splitlines():
            stripped = line.strip()
            if not stripped or CLAUSE_RE.match(stripped) or HEADING_RE.match(stripped):
                continue
            seen.add(stripped)
        for line in seen:
            line_counts[line] = line_counts.get(line, 0) + 1
    threshold = HEADER_FOOTER_FRACTION * len(pages)
    repeating = {line for line, n in line_counts.items() if n > threshold}
    if not repeating:
        return pages
    for page in pages:
        kept = [
            line
            for line in (page["text"] or "").splitlines()
            if line.strip() not in repeating
        ]
        page["text"] = "\n".join(kept)
    _log("info", "headers_footers_stripped", lines_sorted=sorted(repeating))
    return pages


def extract_text_file(path: str | Path) -> list[dict]:
    """Extract a plain-text file (.md / .txt) as a single-page document.

    CI fixture corpus (eval/fixtures/doc1-3.md) is Markdown, not PDF:
    it is indexed as one page (page 1) so the indexer Job can run on it
    in CI without a PDF parser. Returns the same per-page dict shape as
    ``extract_pdf``: [{"page": 1, "text": ..., "is_scanned": False,
    "ocr_used": False}].
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Text file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    _log("info", "text_file_extracted", source=str(path), pages=1, chars=len(text))
    return [{"page": 1, "text": text, "is_scanned": False, "ocr_used": False}]


from html.parser import HTMLParser

_HTML_SKIP = {"script", "style", "noscript", "nav", "header", "footer", "form", "svg"}


class _HtmlText(HTMLParser):
    """Visible text of an HTML page; each <table> becomes a [TABLE] block.

    Tables carry real information on the university pages (fee per credit
    hour, refund timeline, grade points). Flattening them to loose text
    would jumble the columns (failure mode A), so every row is emitted as
    ``cell | cell | cell`` between [TABLE] markers, which the chunker keeps
    atomic. Navigation, scripts and footers are dropped.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._skip = 0
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self._table_depth = 0
        self._buf: list[str] = []

    def _flush_text(self) -> None:
        text = " ".join("".join(self._buf).split())
        self._buf = []
        if text:
            self.lines.append(text)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _HTML_SKIP:
            self._skip += 1
        elif self._skip:
            return
        elif tag == "table":
            self._flush_text()
            self._table_depth += 1
            if self._table_depth == 1:
                self.lines.append("[TABLE]")
        elif tag == "tr" and self._table_depth:
            self._row = []
        elif tag in ("td", "th") and self._table_depth:
            self._cell = []
        elif (
            tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6")
            and not self._table_depth
        ):
            self._flush_text()

    def handle_endtag(self, tag: str) -> None:
        if tag in _HTML_SKIP:
            self._skip = max(0, self._skip - 1)
        elif self._skip:
            return
        elif tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.lines.append(" | ".join(self._row))
            self._row = None
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                self.lines.append("[/TABLE]")
        elif (
            tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6")
            and not self._table_depth
        ):
            self._flush_text()

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._cell is not None:
            self._cell.append(data)
        elif not self._table_depth:
            self._buf.append(data)


def extract_html(path: str | Path) -> list[dict]:
    """Extract an HTML page as a single-page document (tables preserved)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"HTML file not found: {path}")
    parser = _HtmlText()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    parser._flush_text()
    # One paragraph per text block and one atomic paragraph per [TABLE] block
    # (blank-line separated), so the chunker can split the page into sections
    # instead of treating the whole page as one "paragraph containing a table".
    blocks: list[str] = []
    table: list[str] | None = None
    for line in parser.lines:
        if line == "[TABLE]":
            table = [line]
        elif line == "[/TABLE]" and table is not None:
            blocks.append(chr(10).join([*table, line]))
            table = None
        elif table is not None:
            table.append(line)
        else:
            blocks.append(line)
    text = (chr(10) * 2).join(blocks)
    _log("info", "html_extracted", source=str(path), pages=1, chars=len(text))
    return [{"page": 1, "text": text, "is_scanned": False, "ocr_used": False}]


def extract_document(path: str | Path) -> list[dict]:
    """Extract any supported input: PDF via extract_pdf, .md/.txt via
    extract_text_file. Raises ValueError for unsupported suffixes."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        return extract_pdf(path)
    if path.suffix.lower() in (".md", ".txt"):
        return extract_text_file(path)
    if path.suffix.lower() in (".html", ".htm"):
        return extract_html(path)
    raise ValueError(
        f"Unsupported document type {path.suffix!r} for {path} "
        "(supported: .pdf, .md, .txt, .html)"
    )


def extract_pdf(path: str | Path) -> list[dict]:
    """Extract one PDF to per-page dicts.

    Returns ``[{"page", "text", "is_scanned", "ocr_used"}, ...]``.
    Unrecoverable (un-OCR-able) scanned pages are returned with
    ``text == ""`` and ``ocr_used == False`` plus a warning — the
    caller / ``docs/PIPELINE.md`` records the loss, the Job continues.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    try:
        raw_pages = _extract_with_fitz(path)
        backend = "pymupdf"
    except ImportError:
        _log("warning", "pymupdf_missing_falling_back_to_pypdf", source=str(path))
        raw_pages = _extract_with_pypdf(path)
        backend = "pypdf"
    _log("info", "pdf_opened", source=str(path), pages=len(raw_pages), backend=backend)

    pages: list[dict] = []
    for raw in raw_pages:
        page_no = raw["page"]
        scanned = _is_scanned(raw)
        text = raw.get("text") or ""
        ocr_used = False
        if scanned:
            try:
                text = _ocr_page(path, page_no)
                ocr_used = True
                _log(
                    "info",
                    "ocr_applied",
                    source=str(path),
                    page=page_no,
                    chars=len(text),
                )
            except Exception as exc:  # noqa: BLE001 — NEVER crash, NEVER silently drop: keep the page, flag it.
                _log(
                    "warning",
                    "ocr_unavailable_page_unrecoverable",
                    source=str(path),
                    page=page_no,
                    error=str(exc),
                    hint="Install tesseract-ocr + poppler-utils and re-run the Job",
                )
                text = ""
        pages.append(
            {"page": page_no, "text": text, "is_scanned": scanned, "ocr_used": ocr_used}
        )

    pages = _strip_repeating_headers_footers(pages)
    scanned_pages = [p["page"] for p in pages if p["is_scanned"]]
    unrecovered = [
        p["page"]
        for p in pages
        if p["is_scanned"] and not p["ocr_used"] and not p["text"].strip()
    ]
    _log(
        "info",
        "extract_done",
        source=str(path),
        pages=len(pages),
        scanned_pages=scanned_pages,
        unrecovered_pages=unrecovered,
    )
    return pages


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract a PDF to per-page text (JSON)."
    )
    parser.add_argument("pdf", help="PDF file to extract")
    args = parser.parse_args()
    print(json.dumps(extract_pdf(args.pdf), indent=2))
