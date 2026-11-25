#!/usr/bin/env python3
"""D2 Trace Tool — print the exact context and prompt for a trace_id.

Usage:
    python scripts/trace_tool.py <trace_id> [--trace-file traces/traces.jsonl]
    kubectl logs deployment/api -n rahbar | python scripts/trace_tool.py <trace_id> --trace-file -
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def load_traces(source: str | Path) -> list[dict[str, Any]]:
    """Load JSONL trace records from a file path or '-' (stdin)."""
    if str(source) == "-":
        lines = sys.stdin.read().splitlines()
    else:
        p = Path(source)
        if not p.is_file():
            raise FileNotFoundError(f"Trace file not found: {p}")
        lines = p.read_text(encoding="utf-8").splitlines()

    records: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "trace_id" in obj:
            records.append(obj)
    return records


def find_trace(records: list[dict[str, Any]], trace_id: str) -> dict[str, Any] | None:
    for rec in records:
        if rec.get("trace_id") == trace_id:
            return rec
    for rec in records:
        if str(rec.get("trace_id", "")).startswith(trace_id):
            return rec
    return None


def reconstruct_context_blocks(rec: dict[str, Any]) -> str:
    """Format the exact retrieved <context> blocks stored in the trace."""
    lines = ["Evidence:"]
    for idx, ch in enumerate(rec.get("retrieved_chunks") or []):
        lines.append(
            f'<context id="{idx}" source="{ch.get("document_id", "")}" '
            f'section="{ch.get("section", "")}" page="{ch.get("page", 0)}" '
            f'version="{ch.get("document_version", "")}" score="{ch.get("score", 0.0)}">'
            f"{ch.get('text', '')}</context>"
        )
    return "\n".join(lines)


def format_trace_inspection(rec: dict[str, Any]) -> str:
    """Render human-readable context, exact prompt, hash check, and metadata."""
    prompt = rec.get("full_prompt") or ""
    expected_hash = rec.get("prompt_hash") or ""
    actual_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else None
    hash_ok = (actual_hash == expected_hash) if (prompt and expected_hash) else None

    out = [
        "=" * 80,
        f"TRACE ID          : {rec.get('trace_id')}",
        f"TIMESTAMP         : {rec.get('timestamp')}",
        f"USER QUERY        : {rec.get('user_query')}",
        f"REWRITTEN QUERY   : {rec.get('rewritten_query')}",
        f"EMBEDDING         : {rec.get('embedding_model')} ({rec.get('embedding_version')})",
        f"COLLECTION        : {rec.get('collection_name')} ({rec.get('collection_version')})",
        f"MODEL / PARAMS    : {rec.get('model')} | {json.dumps(rec.get('parameters', {}))}",
        f"FILTERS APPLIED   : {json.dumps(rec.get('filters_applied', {}))}",
        f"CACHE HIT         : {rec.get('cache_hit')}",
        f"PROMPT HASH       : {expected_hash} (verified={hash_ok})",
        f"GUARDRAIL ACTIONS : {json.dumps(rec.get('guardrail_actions', []), indent=2)}",
        f"LATENCY PER STAGE : {json.dumps(rec.get('latency_per_stage', {}))}",
        "-" * 80,
        "EXACT RETRIEVED CONTEXT:",
        reconstruct_context_blocks(rec),
        "-" * 80,
        "EXACT PROMPT SENT TO LLM:",
        prompt
        if prompt
        else "<No LLM prompt generated (cache hit or early floor abstention)>",
        "-" * 80,
        "RESPONSE & CITATIONS:",
        json.dumps(
            {"response": rec.get("response"), "citations": rec.get("citations")},
            indent=2,
            ensure_ascii=False,
        ),
        "=" * 80,
    ]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect a RAGOps trace_id and print exact context + prompt."
    )
    parser.add_argument("trace_id", help="Trace ID (or unique prefix) to inspect")
    parser.add_argument(
        "--trace-file",
        default="traces/traces.jsonl",
        help="Path to JSONL trace file or '-' for stdin (default: traces/traces.jsonl)",
    )
    args = parser.parse_args(argv)

    records = load_traces(args.trace_file)
    rec = find_trace(records, args.trace_id)
    if rec is None:
        print(
            f"ERROR: trace_id {args.trace_id!r} not found in {args.trace_file}",
            file=sys.stderr,
        )
        return 1
    print(format_trace_inspection(rec))
    return 0


if __name__ == "__main__":
    # Windows consoles default to cp1252; traces/summaries contain non-ASCII text.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
