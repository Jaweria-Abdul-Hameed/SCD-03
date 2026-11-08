"""Clean stage — remove extraction artefacts without destroying structure.

Rules applied (in order)
------------------------
1.  Page numbers: a line that is only digits (optionally "Page N" /
    "N of M") is removed.
2.  Repeated headers/footers: lines already stripped by
    ``extract._strip_repeating_headers_footers``; ``clean_text`` also
    drops a leading/trailing line repeated verbatim at the same
    position on consecutive pages when handed a whole document
    (defensive second pass — see ``clean_document``).
3.  Hyphenation across line breaks: ``word-\\nword`` -> ``wordword``
    (a hyphen at end-of-line followed by a lower-case continuation
    is a line-wrap artefact, not punctuation).
4.  Excess whitespace: runs of 3+ blank lines collapse to one blank
    line; runs of spaces/tabs collapse to a single space; trailing
    spaces removed. Single newlines inside a paragraph are joined
    to a space; blank lines (paragraph breaks) are kept.
5.  Control characters (other than tab/newline) are removed.
6.  Table blocks are preserved: a run of lines containing ``|`` or
    2+ columns separated by 2+ spaces is marked with
    ``[TABLE]`` / ``[/TABLE]`` markers and its line breaks are kept
    verbatim (joining them would jumble the columns — failure mode A).

Deliberately NOT stripped
-------------------------
Clause numbers and section headings (e.g. ``4.2``, ``1.21``,
``Clause 4.2``) are NEVER removed. They are the retrieval anchors:
the golden set asks for exact clause numbers (G11), the
``doc_version``/``superseded`` filter and the citation ``section``
field both depend on them, and stripping them would turn a
grounded answer into an uncitable one. The same applies to table
delimiters (``|`` and column spacing) inside ``[TABLE]`` blocks:
removing them destroys the row/column mapping that the fee and
grading tables carry.
"""

from __future__ import annotations

import re

# A line that is only a page number: "12", "Page 12", "12 of 53".
PAGE_NUMBER_RE = re.compile(r"^\s*(?:Page\s+)?\d+(?:\s+of\s+\d+)?\s*$", re.IGNORECASE)
# Numbered clause / heading — structure, must survive cleaning.
CLAUSE_RE = re.compile(
    r"^\s*(?:Clause\s+|Section\s+)?\d+(?:\.\d+){0,3}\b", re.IGNORECASE
)
# End-of-line hyphen followed by a lower-case continuation = wrap artefact.
HYPHEN_WRAP_RE = re.compile(r"([A-Za-z])-\n([a-z])")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

#: The rules above, as data — also surfaced by ``cleaning_rules()``
#: for docs / tests so the documented list cannot drift from the code.
RULES = [
    "1. page-numbers: drop lines that are only a page number ('12', 'Page 12', '12 of 53')",
    "2. headers-footers: drop lines repeated on >80% of pages (extract stage) + same-position repeats (clean_document)",
    "3. hyphenation: rejoin words split by a hyphen at a line break ('regis-\\ntration' -> 'registration')",
    "4. whitespace: collapse 3+ blank lines to one, runs of spaces/tabs to one, strip trailing spaces; join single newlines inside a paragraph, keep blank-line paragraph breaks",
    "5. control-chars: remove C0 control characters except tab/newline",
    "6. tables: mark runs of '|' / multi-column lines as [TABLE]...[/TABLE] and keep their line breaks verbatim",
]

#: Deliberately NOT stripped, with the reason (assignment sec. 3.1).
NOT_STRIPPED = (
    "Clause numbers and section headings (e.g. '4.2', '1.21', 'Clause 4.2') "
    "and table delimiters ('|', column spacing) inside [TABLE] blocks: "
    "they are the retrieval/citation anchors (golden-set exact-term questions, "
    "the 'section' citation field, and the doc_version/superseded filter depend "
    "on them); removing them would destroy groundedness, not noise."
)


def cleaning_rules() -> list[str]:
    """Return the documented list of cleaning rules applied."""
    return list(RULES)


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    if "|" in stripped:
        return True
    # Two or more columns separated by 2+ spaces, with some content.
    return bool(re.search(r"\S\s{2,}\S", stripped))


def _mark_tables(lines: list[str]) -> list[str]:
    """Wrap runs of table lines in [TABLE] / [/TABLE], keeping breaks."""
    out: list[str] = []
    in_table = False
    for line in lines:
        if _is_table_line(line):
            if not in_table:
                out.append("[TABLE]")
                in_table = True
            out.append(line)
        else:
            if in_table:
                out.append("[/TABLE]")
                in_table = False
            out.append(line)
    if in_table:
        out.append("[/TABLE]")
    return out


def clean_text(text: str) -> str:
    """Clean one page's (or one section's) text, preserving structure.

    Clause numbers, headings and table structure survive; see the
    module docstring for the full rule list and what is NOT stripped.
    """
    if not text:
        return ""
    text = CONTROL_CHARS_RE.sub("", text)
    # 3. Rejoin hyphenated line-wrap splits before joining lines.
    text = HYPHEN_WRAP_RE.sub(r"\1\2", text)

    lines = text.splitlines()
    # 1. Drop page-number-only lines (never clause lines: "4.2 ..." has
    #    more than digits, so CLAUSE_RE lines are safe by construction).
    lines = [ln for ln in lines if not PAGE_NUMBER_RE.match(ln)]

    # 6. Mark table blocks first so the paragraph-joining below skips them.
    lines = _mark_tables(lines)

    # 4. Join single newlines inside a paragraph; keep blank lines.
    paragraphs: list[str] = []
    buf: list[str] = []
    in_table = False

    def flush() -> None:
        if buf:
            paragraphs.append(" ".join(buf))
            buf.clear()

    for line in lines:
        stripped = line.strip()
        if line == "[TABLE]":
            flush()
            in_table = True
            paragraphs.append(line)
            continue
        if line == "[/TABLE]":
            in_table = False
            paragraphs.append(line)
            continue
        if in_table:
            paragraphs.append(line)  # verbatim: never join table rows
            continue
        if not stripped:
            flush()
            paragraphs.append("")  # paragraph break
        else:
            buf.append(MULTI_SPACE_RE.sub(" ", stripped))
    flush()

    cleaned = "\n".join(paragraphs)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # 3+ blank lines -> one
    return cleaned.strip()


def clean_document(pages: list[dict]) -> list[dict]:
    """Clean every page dict from ``extract.extract_pdf`` in place-order.

    Returns new dicts with the same keys (``page``, ``text``,
    ``is_scanned``, ``ocr_used``) and cleaned ``text``. Also drops a
    first/last line that repeats verbatim at the same position on
    every page (defensive header/footer pass for PDFs where the
    extract-stage >80% rule did not fire because of page-count
    edge cases).
    """
    if not pages:
        return []
    first_lines = [
        (p.get("text") or "").splitlines()[0].strip()
        for p in pages
        if (p.get("text") or "").strip()
    ]
    last_lines = [
        (p.get("text") or "").splitlines()[-1].strip()
        for p in pages
        if (p.get("text") or "").strip()
    ]
    from collections import Counter

    common_first = {
        ln
        for ln, n in Counter(first_lines).items()
        if n >= max(3, int(0.8 * len(pages))) and ln and not CLAUSE_RE.match(ln)
    }
    common_last = {
        ln
        for ln, n in Counter(last_lines).items()
        if n >= max(3, int(0.8 * len(pages))) and ln and not CLAUSE_RE.match(ln)
    }
    out: list[dict] = []
    for page in pages:
        text = page.get("text") or ""
        lines = text.splitlines()
        if lines and lines[0].strip() in common_first:
            lines = lines[1:]
        if lines and lines[-1].strip() in common_last:
            lines = lines[:-1]
        cleaned = clean_text("\n".join(lines))
        out.append({**page, "text": cleaned})
    return out
