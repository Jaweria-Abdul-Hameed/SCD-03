"""Verification stage (Part A1, Paper §4.2.2) — runs after extraction, before chunking.

For every ingested document, records explicit pass/fail + reason for four checks:
1. quality:      non-empty, extraction succeeded, not garbled/corrupt.
2. completeness: required metadata (source, title, date or version, page_count)
                 present and non-empty; text not truncated.
3. recency:      detects newer versions of the same logical document (passes &
                 marks previous version for archiving) and rejects stale older
                 versions when a newer version is already active.
4. uniqueness:   exact duplicates via SHA-256 content hash, and near-duplicates
                 via embedding cosine similarity against active documents.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import embed as embed_mod

REQUIRED_METADATA = ("source", "title", "page_count")
DEFAULT_NEAR_DUP_THRESHOLD = 0.94

_TRUNCATION_MARKERS = (
    "[truncated]",
    "eof_truncated",
    "...truncated",
    "[incomplete]",
)

_ABRUPT_END_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "is",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "with",
    }
)


def normalize_text_for_hash(text: str) -> str:
    """Whitespace-normalised text used for exact hash deduplication."""
    return re.sub(r"\s+", " ", text or "").strip()


def compute_content_hash(pages: list[dict]) -> str:
    joined = "\n".join(p.get("text") or "" for p in pages)
    norm = normalize_text_for_hash(joined)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _strip_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse optional YAML-style frontmatter (`--- ... ---`) at start of .md/.txt."""
    if not text.startswith("---\n") and not text.startswith("---\r\n"):
        return {}, text
    lines = text.splitlines()
    end_idx = None
    for idx in range(1, min(len(lines), 40)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        return {}, text
    meta: dict[str, Any] = {}
    for line in lines[1:end_idx]:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if not k:
            continue
        if k == "page_count":
            try:
                meta[k] = int(v)
            except ValueError:
                meta[k] = v
        elif k in ("truncated", "corrupt"):
            meta[k] = v.lower() == "true"
        else:
            meta[k] = v
    body = "\n".join(lines[end_idx + 1 :]).lstrip("\n")
    return meta, body


def derive_doc_id(filename: str, meta: dict[str, Any] | None = None) -> str:
    """Logical document family id so versions map to one family."""
    if meta and meta.get("doc_id"):
        return str(meta["doc_id"]).strip().lower()
    low = filename.lower()
    if "academic_rules_handbook" in low or "undergraduate_academic_rules" in low:
        return "academic_rules_handbook"
    if "ee_plos" in low:
        return "ee_plos"
    if "annual_report" in low:
        return "annual_report"
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[_-]?(v\d+|20\d{2}(?:[-_]\d{2})?)$", "", stem)
    return re.sub(r"[^a-z0-9]+", "_", stem).strip("_") or filename.lower()


def version_sort_key(version: str | None, date: str | None) -> tuple[int, ...]:
    """Comparable tuple for ordering versions/dates chronologically."""
    raw = str(version or date or "0")
    low = raw.lower()
    if "pre-2024" in low:
        return (2023, 12, 0)
    if "2024+" in low:
        return (2024, 1, 0)
    nums = [int(n) for n in re.findall(r"\d+", raw)]
    if not nums:
        return (0,)
    # Handle version strings like "2026-06-v2" vs "2026-06"
    return tuple(nums)


def extract_document_metadata(
    path: Path,
    pages: list[dict],
    default_version: str = "2026-06",
    version_hint: tuple[str, bool] | None = None,
) -> tuple[dict[str, Any], list[dict]]:
    """Load sidecar `.meta.json` or frontmatter, else derive standard metadata.

    If a `.meta.json` sidecar or explicit `meta_strict: true` frontmatter exists,
    missing fields are intentionally preserved as missing so the completeness
    check catches them cleanly.
    """
    sidecar = Path(f"{path}.meta.json")
    strict_meta = False
    meta: dict[str, Any] = {}

    if sidecar.is_file():
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        strict_meta = True
    elif path.suffix.lower() in (".md", ".txt") and pages:
        fm, body = _strip_frontmatter(pages[0].get("text") or "")
        if fm:
            meta = fm
            strict_meta = bool(fm.get("strict_metadata", True))
            pages = [dict(pages[0], text=body), *pages[1:]]

    if not strict_meta:
        meta.setdefault("source", path.name)
        meta.setdefault("title", embed_mod.doc_title(path.name))
        if version_hint:
            meta.setdefault("version", version_hint[0])
        elif "version" not in meta and "date" not in meta:
            meta["version"] = default_version
        if pages:
            meta.setdefault("page_count", len(pages))

    meta.setdefault("doc_id", derive_doc_id(path.name, meta))
    return meta, pages


def check_quality(
    pages: list[dict],
    extraction_error: str | None = None,
) -> dict[str, Any]:
    """Check 1: non-empty, successful extraction, not garbled or corrupt."""
    if extraction_error:
        return {"pass": False, "reason": f"extraction_failed: {extraction_error}"}
    if not pages:
        return {"pass": False, "reason": "empty_document: 0 pages extracted"}

    joined = "\n".join(p.get("text") or "" for p in pages)
    stripped = joined.strip()
    if len(stripped) < 20:
        unrec = [
            p.get("page")
            for p in pages
            if p.get("is_scanned") and not p.get("ocr_used")
        ]
        if unrec:
            return {
                "pass": False,
                "reason": (
                    f"failed_extraction_scanned_no_ocr: only {len(stripped)} chars "
                    f"across {len(pages)} pages (unrecovered pages: {unrec[:5]})"
                ),
            }
        return {
            "pass": False,
            "reason": f"empty_or_too_short: only {len(stripped)} non-whitespace chars",
        }

    # Garbled / binary corruption check
    total_chars = len(stripped)
    replacement_chars = stripped.count("\ufffd")
    non_printable = sum(
        1
        for ch in stripped
        if ord(ch) < 32 and ch not in ("\n", "\r", "\t")
    )
    weird_ratio = (replacement_chars + non_printable) / max(1, total_chars)
    if weird_ratio > 0.02 or replacement_chars >= 5:
        return {
            "pass": False,
            "reason": (
                f"garbled_or_corrupt_text: replacement_chars={replacement_chars}, "
                f"non_printable={non_printable}, ratio={weird_ratio:.3f}"
            ),
        }

    alpha_num = sum(1 for ch in stripped if ch.isalnum() or ch.isspace())
    symbol_ratio = 1.0 - (alpha_num / max(1, total_chars))
    if symbol_ratio > 0.45:
        return {
            "pass": False,
            "reason": f"garbled_high_symbol_noise: symbol_ratio={symbol_ratio:.3f} > 0.45",
        }

    return {
        "pass": True,
        "reason": f"ok: {total_chars} chars across {len(pages)} page(s)",
    }


def check_completeness(pages: list[dict], meta: dict[str, Any]) -> dict[str, Any]:
    """Check 2: required metadata present + text not truncated."""
    missing: list[str] = []
    for field in REQUIRED_METADATA:
        val = meta.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            if field == "page_count" and not pages:
                missing.append("page_count unavailable (extraction failed)")
            else:
                missing.append(field)
    has_date_or_ver = bool(
        str(meta.get("date") or "").strip() or str(meta.get("version") or "").strip()
    )
    if not has_date_or_ver:
        missing.append("date_or_version")

    if missing:
        return {
            "pass": False,
            "reason": f"missing_required_metadata: {', '.join(missing)}",
        }

    declared_pages = meta.get("page_count")
    try:
        declared_int = int(declared_pages)
    except (TypeError, ValueError):
        return {
            "pass": False,
            "reason": f"invalid_page_count: {declared_pages!r} is not an integer",
        }
    if declared_int < 1:
        if not pages:
            return {
                "pass": False,
                "reason": "missing_required_metadata: page_count unavailable (extraction failed)",
            }
        return {
            "pass": False,
            "reason": f"invalid_page_count: declared page_count={declared_int} must be >= 1",
        }
    if declared_int != len(pages):
        return {
            "pass": False,
            "reason": (
                f"truncated_or_page_mismatch: declared page_count={declared_int} "
                f"!= extracted_pages={len(pages)}"
            ),
        }

    joined = "\n".join(p.get("text") or "" for p in pages).strip()
    low = joined.lower()
    for marker in _TRUNCATION_MARKERS:
        if marker in low:
            return {
                "pass": False,
                "reason": f"truncated_text_marker: found {marker!r} in extracted text",
            }
    if meta.get("truncated") is True:
        return {
            "pass": False,
            "reason": "truncated_flag: document marked truncated in metadata",
        }

    # Check abrupt mid-sentence cut on trailing non-empty line
    last_line = next(
        (ln.strip() for ln in reversed(joined.splitlines()) if ln.strip()), ""
    )
    if last_line and len(joined) > 80:
        last_char = last_line[-1]
        last_word = re.findall(r"[a-zA-Z]+$", last_line)
        if last_line.endswith("...") or last_char in (",", ";", "-"):
            return {
                "pass": False,
                "reason": f"truncated_abrupt_ending: ends with {last_line[-24:]!r}",
            }
        if last_word and last_word[0].lower() in _ABRUPT_END_WORDS:
            return {
                "pass": False,
                "reason": f"truncated_incomplete_clause: ends with dangling word {last_word[0]!r}",
            }

    return {
        "pass": True,
        "reason": (
            f"ok: metadata complete (source={meta['source']}, "
            f"version={meta.get('version') or meta.get('date')}, "
            f"pages={len(pages)}) and text intact"
        ),
    }


def check_recency(
    source: str,
    doc_id: str,
    version: str,
    date: str | None,
    active_by_doc_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Check 3: detect newer version (supersedes old) or reject stale older version.

    Returns ``(check_result, superseded_target_record_or_None)``.
    """
    existing = active_by_doc_id.get(doc_id)
    if not existing:
        return (
            {"pass": True, "reason": f"ok: initial active version {version} for {doc_id}"},
            None,
        )

    existing_ver = str(existing.get("version") or existing.get("date") or "0")
    new_key = version_sort_key(version, date)
    old_key = version_sort_key(existing_ver, existing.get("date"))

    if new_key > old_key:
        return (
            {
                "pass": True,
                "reason": (
                    f"newer_version_detected: {version} supersedes active "
                    f"{existing_ver} ({existing.get('source')}); archiving old version"
                ),
            },
            existing,
        )
    if new_key < old_key:
        return (
            {
                "pass": False,
                "reason": (
                    f"stale_version: {version} is older than active version "
                    f"{existing_ver} ({existing.get('source')})"
                ),
            },
            None,
        )
    # Same version & same doc_id: allowed (incremental engine checks hash)
    return (
        {
            "pass": True,
            "reason": f"ok: matches active version {existing_ver} for {doc_id}",
        },
        None,
    )


def build_doc_signature_text(pages: list[dict], source: str) -> str:
    joined = "\n".join(p.get("text") or "" for p in pages)
    norm = normalize_text_for_hash(joined)
    return f"search_document: {norm[:1500]}"


def check_uniqueness(
    source: str,
    doc_id: str,
    content_hash: str,
    doc_embedding: list[float] | None,
    active_records: list[dict[str, Any]],
    near_dup_threshold: float = DEFAULT_NEAR_DUP_THRESHOLD,
) -> dict[str, Any]:
    """Check 4: exact hash deduplication + near-duplicate embedding similarity."""
    for rec in active_records:
        if rec.get("status") != "active":
            continue
        # Same source & same doc_id & same hash is an unchanged re-run (handled by A2),
        # NOT a duplicate file.
        if rec.get("source") == source and rec.get("doc_id") == doc_id:
            continue
        if rec.get("content_hash") == content_hash:
            return {
                "pass": False,
                "reason": (
                    f"exact_duplicate_hash: sha256={content_hash[:12]} matches "
                    f"existing {rec.get('source')}"
                ),
            }

    if doc_embedding:
        best_sim = 0.0
        best_source = None
        for rec in active_records:
            if rec.get("status") != "active":
                continue
            # Newer/updated versions of the SAME doc_id naturally share wording.
            if rec.get("doc_id") == doc_id:
                continue
            other_vec = rec.get("doc_embedding")
            if not other_vec:
                continue
            sim = cosine_similarity(doc_embedding, other_vec)
            if sim > best_sim:
                best_sim = sim
                best_source = rec.get("source")
        if best_source and best_sim >= near_dup_threshold:
            return {
                "pass": False,
                "reason": (
                    f"near_duplicate_embedding: cosine={best_sim:.4f} >= "
                    f"{near_dup_threshold:.2f} against {best_source}"
                ),
            }
        if best_source:
            return {
                "pass": True,
                "reason": (
                    f"ok: unique hash; max cross-doc cosine={best_sim:.4f} "
                    f"(< {near_dup_threshold:.2f}) vs {best_source}"
                ),
            }

    return {"pass": True, "reason": "ok: unique content hash and embedding"}


def verify_document(
    path: Path,
    pages: list[dict],
    meta: dict[str, Any],
    active_records: list[dict[str, Any]],
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    near_dup_threshold: float = DEFAULT_NEAR_DUP_THRESHOLD,
    extraction_error: str | None = None,
) -> tuple[dict[str, Any], list[float] | None, dict[str, Any] | None]:
    """Run all 4 verification checks on one document after extraction, before chunking."""
    source = str(meta.get("source") or path.name)
    doc_id = str(meta.get("doc_id") or derive_doc_id(path.name, meta))
    version = str(meta.get("version") or meta.get("date") or "2026-06")
    date = str(meta.get("date")) if meta.get("date") else None
    content_hash = compute_content_hash(pages) if pages and not extraction_error else ""

    active_by_doc_id = {
        r["doc_id"]: r for r in active_records if r.get("status") == "active"
    }

    q_res = check_quality(pages, extraction_error=extraction_error)
    c_res = check_completeness(pages, meta) if not extraction_error else {
        "pass": False,
        "reason": f"skipped_due_to_extraction_error: {extraction_error}",
    }
    r_res, superseded_target = check_recency(
        source=source,
        doc_id=doc_id,
        version=version,
        date=date,
        active_by_doc_id=active_by_doc_id,
    )

    doc_embedding: list[float] | None = None
    if q_res["pass"] and pages:
        sig_text = build_doc_signature_text(pages, source)
        fn = embed_fn or embed_mod.embed_texts
        try:
            doc_embedding = fn([sig_text])[0]
        except Exception:  # noqa: BLE001 — fall back to hash-only uniqueness if embed fails
            doc_embedding = None

    u_res = (
        check_uniqueness(
            source=source,
            doc_id=doc_id,
            content_hash=content_hash,
            doc_embedding=doc_embedding,
            active_records=active_records,
            near_dup_threshold=near_dup_threshold,
        )
        if q_res["pass"]
        else {
            "pass": False,
            "reason": f"skipped_due_to_quality_failure: {q_res['reason']}",
        }
    )

    checks = {
        "quality": q_res,
        "completeness": c_res,
        "recency": r_res,
        "uniqueness": u_res,
    }
    overall_pass = all(c["pass"] for c in checks.values())

    report_entry = {
        "source": source,
        "file_path": str(path),
        "doc_id": doc_id,
        "version": version,
        "content_hash": content_hash,
        "checks": checks,
        "overall_pass": overall_pass,
        "superseded_previous": (
            {
                "source": superseded_target["source"],
                "version": superseded_target["version"],
            }
            if overall_pass and superseded_target
            else None
        ),
    }
    return report_entry, doc_embedding, superseded_target
