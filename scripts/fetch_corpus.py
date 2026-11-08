#!/usr/bin/env python3
"""RAHBAR corpus fetcher — FAST-NUCES public site (nu.edu.pk).

Downloads the grounded-RAG corpus for RAHBAR (Assignment 02, section 2)
from the university's *public* pages only. Never fetches SLATE, Flex,
NU Mail, admissions.nu.edu.pk, or anything behind a login.

What it does
------------
1. Reads the four public index pages (Downloads, Prospectus, ORIC
   Policies, IQAE Downloads) and the auxiliary public pages (Fee
   Structure, Grading, Academic Calendar, Undergraduate Rules page).
2. Downloads each document in the DOCUMENTS table once, with a polite
   delay between requests, retries, and URL-encoding of file names
   that contain spaces.
3. Converts Google Drive ``/file/d/<ID>/view`` links to the direct
   download form ``https://drive.google.com/uc?export=download&id=<ID>``.
4. Computes the SHA-256 of every downloaded file and writes
   ``corpus/MANIFEST.md`` (file, source URL, SHA-256, pages, properties).

What it does NOT do
-------------------
* It never commits PDFs to the repository. Downloads go to
  ``corpus/raw/`` (gitignored — the script writes
  ``corpus/raw/.gitignore`` for you) and only ``corpus/MANIFEST.md``
  plus this script are committed.
* It never downloads the deliberately absent topic (see
  ``EXCLUDED`` below). That exclusion is the corpus design, not an
  omission: property 6 requires one realistic topic to be absent so
  the system must abstain on it.

Usage
-----
    python3 scripts/fetch_corpus.py                  # download + manifest
    python3 scripts/fetch_corpus.py --dry-run        # list URLs + expected
                                                     # SHA-256, download nothing
    python3 scripts/fetch_corpus.py --out corpus/raw --manifest corpus/MANIFEST.md
    python3 scripts/fetch_corpus.py --delay 2        # be extra polite

Shared constants (do not invent others): namespace ``rahbar``;
EMBED_MODEL ``nomic-embed-text`` (768 dims); LLM ``llama3.2:3b`` via
ollama-host. Those belong to the indexer/API, not to this script.

Dependencies: Python 3.9+ standard library. ``requests`` is used when
available and the script falls back to ``urllib`` when it is not.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlunparse

try:  # requests is preferred when installed; urllib is the fallback.
    import requests  # type: ignore
except ImportError:  # pragma: no cover - exercised on minimal installs
    requests = None  # type: ignore

import urllib.request

log = logging.getLogger("fetch_corpus")

BASE = "https://nu.edu.pk"

# ---------------------------------------------------------------------------
# Index pages (assignment sec. 2: "four index pages").
# NOTE: the short paths do NOT work — /prospectus, /fee-structure and
# /academic-calendar all return 404 (checked live 2026-11-05). The real
# routes are the /Admissions/..., /Oric/..., /IQAE/... and /Student/...
# paths below, which all returned HTTP 200 on 2026-11-05.
# ---------------------------------------------------------------------------
INDEX_PAGES = {
    "Downloads": f"{BASE}/Downloads",
    "Prospectus": f"{BASE}/Admissions/Prospectus",
    "ORIC Policies": f"{BASE}/Oric/Policies",
    "IQAE Downloads": f"{BASE}/IQAE/Downloads",
}

# Auxiliary public pages (not index pages, but they carry corpus content
# that is only available as HTML: fee/grading tables, calendar).
AUX_PAGES = {
    "Fee Structure": f"{BASE}/Admissions/FeeStructure",
    "Grading": f"{BASE}/Student/Grading",
    "Academic Calendar": f"{BASE}/Student/Calender",  # sic: site spells it so
    "Undergraduate Rules page": f"{BASE}/Student/RulesUndergrad",
}

# ---------------------------------------------------------------------------
# Deliberate exclusion — property 6 (absent topic).
# ---------------------------------------------------------------------------
# WHY THIS FILE IS EXCLUDED, ON PURPOSE: the corpus must contain one
# realistic topic that is deliberately absent, so the RAG system has
# something it must honestly abstain on (assignment sec. 2 property 6
# and sec. 3.4). The chosen topic is transport/hostel rules. The
# prospectus's "Transport and Hostel Facilities" PDF is therefore
# NEVER downloaded, even though it is linked from the Prospectus
# index page right next to the documents we do fetch. The Student
# Handbook only says hostels exist ("In-Campus Hostel" facilities
# line) — it gives no allotment rules, routes or timings — so
# questions about hostel allotment and bus routes have no answer in
# the corpus and must return answered_from_context=false.
# If you remove this exclusion, golden questions G13/G14 (must-abstain)
# become answerable and the abstention evaluation becomes meaningless.
EXCLUDED = [
    {
        "title": "Transport and Hostel Facilities (Prospectus 2026)",
        "url": f"{BASE}/Admissions/ProspectusUpload/Transport%20and%20Hostel%20Facilities.pdf",
        "reason": "Property 6 — deliberately absent topic (transport/hostel rules).",
    },
]

# Patterns that must never be fetched (login-gated / private surfaces).
NEVER_FETCH = (
    "slate",
    "flex",
    "nu mail",
    "numail",
    "admissions.nu.edu.pk",
    "/login",
    "signin",
    "sign-in",
)

# ---------------------------------------------------------------------------
# The corpus. One row per document.
#   properties: the assignment sec. 2 property numbers (1-7) it satisfies.
#   sha256:     hash verified live by AGENT_CORPUS on 2026-11-05 by actually
#               downloading the file. A normal run re-computes the hash and
#               warns if it differs (the site may have re-published a file);
#               --dry-run prints this expected value without downloading.
#   pages:      page count verified live on 2026-11-05 (pdfinfo); HTML
#               pages count as 1 page each.
#   superseded: True for the old version of a version pair (property 2).
# ---------------------------------------------------------------------------
DOCUMENTS = [
    {
        "key": "academic-rules-handbook-2026",
        "title": "Academic Rules Handbook, Jun 2026 (Undergraduate Academic Rules & Regulations)",
        "url": f"{BASE}/public/downloads/Academic_Rules_Handbook_2026.pdf",
        "filename": "Academic_Rules_Handbook_2026.pdf",
        "kind": "pdf",
        "index": "Downloads",
        "doc_version": "Jun 2026 (current)",
        "superseded": False,
        "properties": [1, 2, 7],
        "pages": 58,
        "sha256": "4cfee3e191b84aeb9168f17656c7642212ff52b90f2780d028b33c154aa74b62",
        "notes": "Current version of the policy. Attendance is clause 1.21; "
        "registration procedure is clause 4.2; failed/missed-course "
        "rule is clause 5.8; min CGPA 2.00 (clause 5.7).",
    },
    {
        "key": "undergrad-academic-rules-2023",
        "title": "Undergraduate Academic Rules, Aug 2023",
        "url": "http://nu.edu.pk/public/downloads/Academic-Rules-Undergrad-Aug-2023.pdf",
        "filename": "Undergraduate_Academic_Rules_Aug_2023.pdf",
        "kind": "pdf",
        "index": "Undergraduate Rules page (/Student/RulesUndergrad)",
        "doc_version": "Aug 2023 (superseded)",
        "superseded": True,
        "properties": [1, 2],
        "pages": 26,
        "sha256": "cddfe1f5e9770132e27d686abd1c2e6742ef4732f0c2f431ed514bc1691d2004",
        "notes": "Old version of the same policy (version pair with the Jun 2026 "
        "Handbook). KNOWN TRAP: the assignment notes this link 'would "
        "not open when checked' on 2026-11-01. It DID download on "
        "2026-11-05 via plain http:// from the Bachelor rules page — "
        "see FALLBACK_URLS. Its body pages carry almost no text layer "
        "(pdftotext returns ~243 chars for 26 pages), so it ALSO needs "
        "OCR; treat it as a second scanned document, not as clean text.",
    },
    {
        "key": "prospectus-2026-academic-rules",
        "title": "Prospectus 2026: Academic Rules and Regulations",
        "url": f"{BASE}/Admissions/ProspectusUpload/Academic Rules and Regulations.pdf",
        "filename": "Prospectus_2026_Academic_Rules_and_Regulations.pdf",
        "kind": "pdf",
        "index": "Prospectus",
        "doc_version": "Prospectus 2026 (current prospectus)",
        "superseded": False,
        "properties": [1, 2, 7],
        "pages": 5,
        "sha256": "a7e7f6896a59eb9413c9e8826e6c4c018ebe52045d10cebfcba92ded10a3174a",
        "notes": "Same rules in 5 pages with DIFFERENT clause numbers: attendance "
        "is clause 1 here but 1.21 in the Jun 2026 Handbook. Attendance: "
        "100% required, max 20% condoned; minimum 80% (UG) / 75% (graduate).",
    },
    {
        "key": "student-handbook-2026",
        "title": "Student Handbook, Jun 2026",
        "url": f"{BASE}/public/downloads/Student_Handbook_2026.pdf",
        "filename": "Student_Handbook_2026.pdf",
        "kind": "pdf",
        "index": "Downloads",
        "doc_version": "Jun 2026 (current)",
        "superseded": False,
        "properties": [1, 5],
        "pages": 64,
        "sha256": "717eb4b8d37e50185ffe952735c08ef19edd16074d547f10ebd22cf23da67c4d",
        "notes": "Long definitions (property 5): section XII, 'Policy on Generative "
        "AI Based Tools' (p. 40), long numbered sub-sections a fixed-size "
        "chunker would cut in half. Only says hostels exist — no rules.",
    },
    {
        "key": "faculty-entrepreneurship-policy",
        "title": "Faculty Entrepreneurship and Technical Start-ups Policy and Procedure",
        "url": f"{BASE}/OricResources/ResearchPolicies/27.pdf?20220530",
        "filename": "Faculty_Entrepreneurship_Technical_Startups_Policy.pdf",
        "kind": "pdf",
        "index": "ORIC Policies",
        "doc_version": "2022-05-30 (as linked)",
        "superseded": False,
        "properties": [1, 3],
        "pages": 8,
        "sha256": "c2d5c7648d1593daf34d5c0596ede476e8984b0551830cc1690017e6e22f1359",
        "notes": "CONFIRMED scanned/image-only (property 3): `pdffonts` returns an "
        "empty font list and `pdftotext` extracts 8 characters from 8 "
        "pages. OCR is mandatory; without it this document is invisible "
        "to retrieval (failure mode A).",
    },
    {
        "key": "annual-report-2019-20",
        "title": "Annual Report 2019-20",
        "url": f"{BASE}/public/downloads/AnnualReportForm/Annual Report 2019-20.pdf",
        "filename": "Annual_Report_2019-20.pdf",
        "kind": "pdf",
        "index": "Downloads",
        "doc_version": "2019-20",
        "superseded": True,
        "properties": [1, 2, 4],
        "pages": 33,
        "sha256": "4d1961e340b13273bb039805ab5fd5e2c7bd0144a5bd5870f2ce4da13becd650",
        "notes": "Edition 1 of 5 of one report — versions over time, with tables "
        "of faculty by campus, graduates and publications.",
    },
    {
        "key": "annual-report-2020-21",
        "title": "Annual Report 2020-21",
        "url": f"{BASE}/public/downloads/AnnualReportForm/Annual Report 2020-21.pdf",
        "filename": "Annual_Report_2020-21.pdf",
        "kind": "pdf",
        "index": "Downloads",
        "doc_version": "2020-21",
        "superseded": True,
        "properties": [1, 2, 4],
        "pages": 33,
        "sha256": "996ca07ec6db28647f8c43beb56715726361b5afc8bbe0b84d2270bf7ee752ee",
        "notes": "Edition 2 of 5.",
    },
    {
        "key": "annual-report-2021-22",
        "title": "Annual Report 2021-22",
        "url": f"{BASE}/public/downloads/AnnualReportForm/Annual Report 2021-22.pdf",
        "filename": "Annual_Report_2021-22.pdf",
        "kind": "pdf",
        "index": "Downloads",
        "doc_version": "2021-22",
        "superseded": True,
        "properties": [1, 2, 4],
        "pages": 36,
        "sha256": "87f182fe9e6ebc4bb2c56b86145f98b35181efd7f2dc7adf064eca0c0703d643",
        "notes": "Edition 3 of 5.",
    },
    {
        "key": "annual-report-2022-23",
        "title": "Annual Report 2022-23",
        "url": f"{BASE}/public/downloads/AnnualReportForm/Annual Report 2022-23.pdf",
        "filename": "Annual_Report_2022-23.pdf",
        "kind": "pdf",
        "index": "Downloads",
        "doc_version": "2022-23",
        "superseded": True,
        "properties": [1, 2, 4],
        "pages": 36,
        "sha256": "17fefb84832fc0d14723f08a3795bbe70e95c16fd8d57f16eef32ebed805a31d",
        "notes": "Edition 4 of 5.",
    },
    {
        "key": "annual-report-2023-24",
        "title": "Annual Report 2023-24",
        "url": f"{BASE}/public/downloads/AnnualReportForm/Annual Report 2023-24.pdf",
        "filename": "Annual_Report_2023-24.pdf",
        "kind": "pdf",
        "index": "Downloads",
        "doc_version": "2023-24 (latest edition fetched)",
        "superseded": False,
        "properties": [1, 2, 4],
        "pages": 85,
        "sha256": "3c9d89e84af24df4b939f10e32c620a3877b276acea1db52f1aae4098e5c057a",
        "notes": "Edition 5 of 5; the longest single document in the corpus.",
    },
    {
        "key": "ee-plos-2024-onwards",
        "title": "EE Program Learning Outcomes — batches 2024 onwards (11 PLOs)",
        "url": "https://drive.google.com/file/d/1VBkr5aHcgOHmlzAtjpn_GjQZNCXjcSLF/view",
        "filename": "EE_PLOs_2024_onwards_11.pdf",
        "kind": "pdf",
        "index": "IQAE Downloads",
        "doc_version": "2024 onwards (current)",
        "superseded": False,
        "properties": [1, 2, 7],
        "pages": 1,
        "sha256": "bbf1eb1291e81dcf0944328748269668495032cf41c14ccc85eaed6ceced93f1",
        "notes": "Google Drive document; fetched via the uc?export=download "
        "conversion. 11 PLOs (PLO-1 Engineering Knowledge … PLO-11).",
    },
    {
        "key": "ee-plos-before-2024",
        "title": "EE Program Learning Outcomes — batches before 2024 (12 PLOs)",
        "url": "https://drive.google.com/file/d/1yZo--h0fZN9lqRapQbUxkYBqm-7AeL3V/view",
        "filename": "EE_PLOs_before_2024_12.pdf",
        "kind": "pdf",
        "index": "IQAE Downloads",
        "doc_version": "Before 2024 (superseded)",
        "superseded": True,
        "properties": [1, 2, 7],
        "pages": 2,
        "sha256": "0c782e8beb5cb664baee4822f633b9211f029aeb11c350a4c1241ca84e3841e6",
        "notes": "Google Drive document; 12 PLOs. Version pair with the 11-PLO "
        "document above — the answer to 'how many PLOs?' depends on "
        "which version the retriever returns (failure mode E).",
    },
    {
        "key": "fee-structure-page",
        "title": "Fee Structure page (HTML)",
        "url": f"{BASE}/Admissions/FeeStructure",
        "filename": "Fee_Structure_page.html",
        "kind": "html",
        "index": "Admissions (Fee Structure page)",
        "doc_version": "2026-27 (w.e.f. Fall 2026)",
        "superseded": False,
        "properties": [1, 4, 7],
        "pages": 1,
        "sha256": None,  # HTML pages change with site chrome; hash the saved copy.
        "notes": "Complex tables (property 4): tuition per credit hour "
        "(BBA/BS, MBA/MS, PhD — all Rs. 12,000, academic year 2026-27), "
        "miscellaneous fees, refund timeline (100% to 10th day, 80% to "
        "15th, 60% to 20th, 50% to 30th, no refund from 31st day). "
        "Admission fee Rs. 30,000; security deposit Rs. 20,000; Student "
        "Activities Fund Rs. 2,500/semester.",
    },
    {
        "key": "grading-page",
        "title": "Academic Grading page (HTML)",
        "url": f"{BASE}/Student/Grading",
        "filename": "Grading_page.html",
        "kind": "html",
        "index": "Student (Grading page)",
        "doc_version": "current",
        "superseded": False,
        "properties": [1, 4, 7],
        "pages": 1,
        "sha256": None,  # HTML pages change with site chrome; hash the saved copy.
        "notes": "Grade-points tables (property 4): BBA/BS, MBA/MS and PhD scales "
        "(A+ 4.00 … D 1.00); SGPA/CGPA definitions; grade 'I' converts "
        "to 'F' before the end of the next semester; 'S'/'U' for PhD "
        "thesis only, excluded from CGPA.",
    },
    {
        "key": "academic-calendar-page",
        "title": "Academic Calendar page (HTML)",
        "url": f"{BASE}/Student/Calender",
        "filename": "Academic_Calendar_page.html",
        "kind": "html",
        "index": "Student (Academic Calendar page)",
        "doc_version": "2026-2027",
        "superseded": False,
        "properties": [1, 2],
        "pages": 1,
        "sha256": None,  # HTML pages change with site chrome; hash the saved copy.
        "notes": "Version trap (property 2): the 2026-2027 schedule (Fall 2026 "
        "registration Aug 10–14, classes from Aug 17; Spring 2027 "
        "registration Jan 12–16) sits beside a holidays table headed "
        "'Expected Holidays during the year 2023-24'. A retriever that "
        "ignores the heading date answers holiday questions with a "
        "three-year-old table.",
    },
]

# Alternate URLs tried in order for a document whose primary link fails.
# The Aug 2023 rules are the known trap: the assignment records that the
# link "would not open when checked" on 2026-11-01. On 2026-11-05 the
# plain-http link from the Bachelor rules page DID open, so the primary
# URL above is http://... — the https:// variant is kept here as the
# first fallback, and if BOTH fail the script logs a clear warning and
# continues with the Prospectus 2026 rules as the version-pair evidence
# (same rules, different clause numbers) instead of crashing. A missing
# old version weakens property 2; it must never abort the whole fetch.
FALLBACK_URLS = {
    "undergrad-academic-rules-2023": [
        "https://nu.edu.pk/public/downloads/Academic-Rules-Undergrad-Aug-2023.pdf",
    ],
}
# Document used as version-pair evidence if the Aug 2023 file is
# genuinely unreachable (same rules, re-numbered clauses).
VERSION_PAIR_FALLBACK_KEY = "prospectus-2026-academic-rules"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def drive_to_direct(url: str) -> str:
    """Convert a Drive /file/d/<ID>/view link to a direct download URL.

    >>> drive_to_direct("https://drive.google.com/file/d/ABC123/view?usp=sharing")
    'https://drive.google.com/uc?export=download&id=ABC123'
    """
    m = re.search(r"drive\.google\.com/file/d/([^/]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def encode_url(url: str) -> str:
    """URL-encode path segments (several file names contain spaces) while
    leaving the scheme, host, query string and already-encoded parts alone."""
    parsed = urlparse(url)
    path = quote(unquote(parsed.path), safe="/%")
    return urlunparse(parsed._replace(path=path))


def is_forbidden(url: str) -> bool:
    lowered = url.lower()
    return any(p in lowered for p in NEVER_FETCH)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def count_pdf_pages(data: bytes) -> int | None:
    """Best-effort PDF page count without extra dependencies.

    Prefers ``pdfinfo`` (authoritative; the naive ``/Type /Page`` regex
    overcounts — it returned 7 for a 5-page file and 65 for a 64-page
    file), then pypdf/PyPDF2 when installed, then the regex as a last
    resort. Returns None when it cannot tell.
    """
    import subprocess
    import tempfile

    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as tmp:
            tmp.write(data)
            tmp.flush()
            out = subprocess.run(
                ["pdfinfo", tmp.name],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        m = re.search(r"^Pages:\s+(\d+)\s*$", out.stdout, re.MULTILINE)
        if m:
            return int(m.group(1))
    except Exception:  # noqa: BLE001, S110 — pdfinfo may fail or not be installed
        pass
    for mod in ("pypdf", "PyPDF2"):
        try:
            module = __import__(mod)
            import io

            reader = module.PdfReader(io.BytesIO(data))
            return len(reader.pages)
        except Exception:  # noqa: BLE001, S112 — module may fail on malformed PDF
            continue
    try:
        count = len(re.findall(rb"/Type\s*/Page[^s]", data))
        return count or None
    except Exception:  # noqa: BLE001 — regex fallback error
        return None


def fetch_bytes(url: str, timeout: int = 60, retries: int = 3) -> bytes:
    """GET a URL with retries and exponential back-off. Raises on failure."""
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if requests is not None:
                resp = requests.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 RAHBAR-corpus-fetch"},
                    timeout=timeout,
                )
                resp.raise_for_status()
                return resp.content
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 RAHBAR-corpus-fetch"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 - retry then re-raise
            last_exc = exc
            log.warning("attempt %d/%d failed for %s: %s", attempt, retries, url, exc)
            if attempt < retries:
                time.sleep(2**attempt)
    assert last_exc is not None
    raise last_exc


def check_index_pages() -> dict[str, str]:
    """HEAD/GET each index page and report its status (best effort)."""
    status: dict[str, str] = {}
    for name, url in {**INDEX_PAGES, **AUX_PAGES}.items():
        try:
            fetch_bytes(url, timeout=30, retries=1)
            status[name] = "200 OK"
        except Exception as exc:  # noqa: BLE001 - status reporting only
            status[name] = f"UNREACHABLE: {exc}"
            log.warning("index page %s (%s) unreachable: %s", name, url, exc)
    return status


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
MANIFEST_HEADER = """# corpus/MANIFEST.md — RAHBAR corpus manifest

> Corpus: FAST-NUCES public site (nu.edu.pk), fetched by `scripts/fetch_corpus.py`.
> **PDFs themselves are NOT committed** — only this manifest and the fetch
> script are. Reproduce the corpus with `python3 scripts/fetch_corpus.py`
> (downloads go to `corpus/raw/`, which is gitignored).
>
> Hashes below were computed live on 2026-11-05 by AGENT_CORPUS by actually
> downloading each file (see `docs/CORPUS.md` for the verification log).
> Re-run the fetch script to re-verify them; the script warns on any mismatch.
> HTML pages have no pinned expected hash (the site's chrome changes
> between fetches) — the hash recorded is the hash of the saved copy in
> `corpus/raw/` at fetch time; re-running the script updates it.
>
> Deliberately ABSENT (property 6): the Prospectus 2026
> `Transport and Hostel Facilities` PDF is excluded on purpose — see
> `EXCLUDED` in `scripts/fetch_corpus.py` and `docs/CORPUS.md`. Do not add it.

"""


def write_manifest(path: Path, rows: list[dict], dry_run: bool) -> None:
    lines = [MANIFEST_HEADER]
    lines.append("| file | source URL | SHA-256 | pages | properties satisfied |")
    lines.append("|---|---|---|---|---|")
    total_pages = 0
    for row in rows:
        total_pages += row["pages"] or 0
        props = ", ".join(str(p) for p in row["properties"])
        lines.append(
            f"| `{row['filename']}` | {row['url']} | `{row['sha256']}` | "
            f"{row['pages'] if row['pages'] is not None else 'unknown'} | {props} |"
        )
    lines.append("")
    lines.append(
        f"**Total: {len(rows)} documents, {total_pages} pages "
        f"(requirement: >=6 documents, >=40 pages).**"
    )
    lines.append("")
    lines.append("## Excluded on purpose (property 6 — absent topic)")
    lines.append("")
    for exc in EXCLUDED:
        lines.append(f"- **{exc['title']}** — <{exc['url']}> — {exc['reason']}")
    lines.append("")
    if dry_run:
        lines.append(
            "> NOTE: this manifest was generated with `--dry-run`; "
            "hashes marked `sha256:TODO-…` are placeholders and no "
            "file was downloaded. Run without `--dry-run` to fetch "
            "and record real hashes."
        )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info("wrote %s (%d documents, %d pages)", path, len(rows), total_pages)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch the RAHBAR corpus from the FAST-NUCES public site."
    )
    parser.add_argument(
        "--out",
        default="corpus/raw",
        help="directory for downloaded files (default: corpus/raw)",
    )
    parser.add_argument(
        "--manifest",
        default="corpus/MANIFEST.md",
        help="manifest file to write (default: corpus/MANIFEST.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list URLs + expected SHA-256 without downloading",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="polite delay in seconds between requests (default: 1.0)",
    )
    parser.add_argument(
        "--skip-index-check",
        action="store_true",
        help="do not check the index pages first",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Keep the raw downloads out of git even if the repo root has no rule.
    (out_dir / ".gitignore").write_text("*\n!/.gitignore\n", encoding="utf-8")

    if args.dry_run:
        log.info("dry run: no files will be downloaded")
        rows = []
        for doc in DOCUMENTS:
            expected = doc["sha256"] or f"TODO-{doc['key']}"
            rows.append({**doc, "sha256": f"sha256:{expected}"})
            print(
                f"{doc['title']}\n  {doc['url']}\n  sha256:{expected}  "
                f"pages={doc['pages']}  properties={doc['properties']}"
            )
        write_manifest(Path(args.manifest), rows, dry_run=True)
        print(
            f"\n{len(rows)} documents, "
            f"{sum(d['pages'] or 0 for d in DOCUMENTS)} pages (dry run)."
        )
        return 0

    if not args.skip_index_check:
        log.info("checking index pages …")
        for name, status in check_index_pages().items():
            log.info("  %-28s %s", name, status)

    rows: list[dict] = []
    for doc in DOCUMENTS:
        if is_forbidden(doc["url"]):
            log.error("refusing forbidden URL (login-gated): %s", doc["url"])
            continue
        urls = [doc["url"], *FALLBACK_URLS.get(doc["key"], [])]
        data: bytes | None = None
        used_url = doc["url"]
        for candidate in urls:
            fetch_url = encode_url(drive_to_direct(candidate))
            try:
                data = fetch_bytes(fetch_url)
                used_url = candidate
                break
            except Exception as exc:  # noqa: BLE001 - try next URL, then warn
                log.warning("could not fetch %s: %s", fetch_url, exc)
        if data is None:
            # The Aug 2023 trap: warn clearly, fall back, never crash.
            log.warning(
                "WARNING: %s (%s) could not be downloaded from any known URL. "
                "This is the known 2026-11-01 trap (the old-rules link would not "
                "open). The version pair is still covered by %s "
                "(Prospectus 2026 rules, same rules with different clause "
                "numbers). Re-check the link on the Bachelor rules page "
                "(https://nu.edu.pk/Student/RulesUndergrad) before building on it.",
                doc["title"],
                doc["url"],
                VERSION_PAIR_FALLBACK_KEY,
            )
            rows.append(
                {**doc, "sha256": f"sha256:TODO-{doc['key']}", "pages": doc["pages"]}
            )
            continue
        dest = out_dir / doc["filename"]
        dest.write_bytes(data)
        digest = sha256_hex(data)
        if doc["sha256"] and digest != doc["sha256"]:
            log.warning(
                "HASH MISMATCH for %s: expected %s, got %s — the site may have "
                "re-published the file. The manifest records the NEW hash; "
                "update docs/CORPUS.md and the golden set if content changed.",
                doc["filename"],
                doc["sha256"],
                digest,
            )
        pages = 1 if doc["kind"] == "html" else count_pdf_pages(data)
        if pages is None:
            pages = doc["pages"]
            log.warning(
                "could not count pages for %s; using expected %s",
                doc["filename"],
                pages,
            )
        elif pages != doc["pages"]:
            log.info(
                "page count for %s: %s (expected %s)",
                doc["filename"],
                pages,
                doc["pages"],
            )
        rows.append(
            {**doc, "sha256": f"sha256:{digest}", "pages": pages, "url": used_url}
        )
        log.info("fetched %s (%d bytes, %s pages)", doc["filename"], len(data), pages)
        time.sleep(args.delay)

    write_manifest(Path(args.manifest), rows, dry_run=False)
    total = sum(r["pages"] or 0 for r in rows)
    print(f"\nDone: {len(rows)} documents, {total} pages -> {args.out}/")
    print(f"Manifest: {args.manifest}")
    print(
        "Reminder: PDFs in corpus/raw/ are NOT committed — only the "
        "manifest and this script are."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
