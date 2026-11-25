"""Pipeline guardrails (Paper §3.2.3 & Assignment Part D4).

Implements:
- Input Rail (I): detects prompt-injection directives in user queries and logs them.
- Retrieval Rail (R): scans retrieved chunks for injected instructions (e.g. from
  poisoned documents like Batch B's b11_library_fine_addendum_injected.md),
  redacts or excludes poisoned lines, and writes structured actions into the trace.
"""

from __future__ import annotations

import re
from copy import deepcopy

INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignore_previous_instructions",
        re.compile(
            r"ignore\s+(?:all\s+)?(?:previous|prior|your)\s+instructions?",
            re.IGNORECASE,
        ),
    ),
    (
        "system_override_marker",
        re.compile(r"system\s+override\s*:|<!--\s*system\s+override", re.IGNORECASE),
    ),
    (
        "disregard_rules",
        re.compile(
            r"disregard\s+(?:all\s+)?(?:previous\s+)?(?:rules|instructions|prompts?)",
            re.IGNORECASE,
        ),
    ),
    (
        "forced_approval_directive",
        re.compile(
            r"(?:always\s+respond|respond\s+that)\s+all\s+.*\s+(?:are|will\s+be)\s+(?:100%\s+)?automatically\s+approved",
            re.IGNORECASE,
        ),
    ),
)


def scan_input_rail(question: str) -> dict:
    """Inspect user query for embedded prompt-injection patterns."""
    matched: list[str] = []
    for name, pat in INJECTION_PATTERNS:
        if pat.search(question or ""):
            matched.append(name)
    if matched:
        return {
            "rail": "input",
            "triggered": True,
            "action": "flagged_treat_as_data",
            "matched_patterns": matched,
            "reason": f"Detected prompt-injection pattern(s) in user query: {', '.join(matched)}",
        }
    return {
        "rail": "input",
        "triggered": False,
        "action": "allow",
        "matched_patterns": [],
        "reason": "no_injection_detected",
    }


def _strip_injected_lines(text: str) -> tuple[str, list[str]]:
    """Remove lines matching injection patterns while preserving legitimate policy lines."""
    matched_names: list[str] = []
    kept_lines: list[str] = []
    for line in (text or "").splitlines():
        line_hit = False
        for name, pat in INJECTION_PATTERNS:
            if pat.search(line):
                matched_names.append(name)
                line_hit = True
        if not line_hit:
            kept_lines.append(line)
    # Deduplicate preserving order
    uniq = list(dict.fromkeys(matched_names))
    return "\n".join(kept_lines).strip(), uniq


def apply_retrieval_rail(
    chunks: list[dict], mode: str = "redact"
) -> tuple[list[dict], list[dict]]:
    """Inspect every retrieved chunk for injected instructions (Paper §3.2.3 Retrieval Rail).

    Returns ``(sanitized_chunks, guardrail_actions)``.
    In ``redact`` mode (default), injected lines are stripped so legitimate policy clauses
    in the same document remain answerable safely; if nothing remains or ``mode == "exclude"``,
    the chunk is dropped before reaching the generator prompt.
    """
    sanitized: list[dict] = []
    actions: list[dict] = []

    for chunk in chunks:
        c = deepcopy(chunk)
        meta = c.get("metadata", {})
        cid = c.get("id", "")
        source = meta.get("source", "")
        text = c.get("text", "")
        cleaned_text, hits = _strip_injected_lines(text)
        if not hits:
            sanitized.append(c)
            continue

        if mode == "exclude" or not cleaned_text:
            actions.append(
                {
                    "rail": "retrieval",
                    "triggered": True,
                    "action": "excluded_poisoned_chunk",
                    "chunk_id": cid,
                    "source": source,
                    "matched_patterns": hits,
                    "reason": f"Excluded retrieved chunk {cid} ({source}) due to injected instruction(s): {', '.join(hits)}",
                }
            )
        else:
            c["text"] = (
                cleaned_text + "\n[RETRIEVAL_RAIL: injected instruction redacted]"
            )
            sanitized.append(c)
            actions.append(
                {
                    "rail": "retrieval",
                    "triggered": True,
                    "action": "redacted_injected_instruction",
                    "chunk_id": cid,
                    "source": source,
                    "matched_patterns": hits,
                    "reason": f"Redacted injected instruction(s) ({', '.join(hits)}) from chunk {cid} ({source})",
                }
            )

    if not actions:
        actions.append(
            {
                "rail": "retrieval",
                "triggered": False,
                "action": "allow_all",
                "chunks_checked": len(chunks),
                "reason": "no_injected_instructions_in_retrieved_chunks",
            }
        )
    return sanitized, actions
