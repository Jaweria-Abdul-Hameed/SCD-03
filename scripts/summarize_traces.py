#!/usr/bin/env python3
"""D3 Trace Metrics Summarizer — compute RAGOps metrics over a time window.

Reports:
- top-1 retrieval similarity distribution (quantiles + histogram)
- abstention rate
- cache hit rate
- p50 / p95 latency per stage
- number of injection attempts flagged (input + retrieval rails)

Usage:
    python scripts/summarize_traces.py --trace-file traces/traces.jsonl --window 24h --out traces/metrics_summary.json
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def parse_window(spec: str) -> timedelta | None:
    """Parse window strings like '30m', '24h', '7d', or 'all'."""
    s = spec.strip().lower()
    if s in ("all", "0", "none"):
        return None
    m = re.fullmatch(r"(\d+)\s*([smhd])", s)
    if not m:
        raise ValueError(
            f"Invalid window {spec!r}; expected e.g. '30m', '24h', '7d', or 'all'"
        )
    val = int(m.group(1))
    unit = m.group(2)
    if unit == "s":
        return timedelta(seconds=val)
    if unit == "m":
        return timedelta(minutes=val)
    if unit == "h":
        return timedelta(hours=val)
    return timedelta(days=val)


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (pct / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def summarize_traces(
    records: list[dict[str, Any]],
    window: str = "all",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Summarize trace records within the requested time window."""
    delta = parse_window(window)
    ref_now = now or datetime.now(UTC)
    cutoff = (ref_now - delta) if delta is not None else None

    filtered: list[dict[str, Any]] = []
    for rec in records:
        ts_raw = rec.get("timestamp")
        if cutoff is not None and ts_raw:
            try:
                ts = datetime.fromisoformat(str(ts_raw))  # py3.11+ parses a trailing Z
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                if ts < cutoff:
                    continue
            except ValueError:
                pass
        filtered.append(rec)

    total = len(filtered)
    cache_hits = sum(1 for r in filtered if r.get("cache_hit") is True)
    abstentions = sum(
        1
        for r in filtered
        if not bool((r.get("response") or {}).get("answered_from_context", False))
    )

    top1_sims: list[float] = []
    for r in filtered:
        chunks = r.get("retrieved_chunks") or []
        if chunks:
            scores = [
                float(c.get("score", 0.0)) for c in chunks if c.get("score") is not None
            ]
            if scores:
                top1_sims.append(max(scores))

    # Histogram buckets matching Prometheus top1_retrieval_similarity
    buckets = [0.4, 0.5, 0.6, 0.64, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
    sim_hist: dict[str, int] = {}
    prev = 0.0
    for b in buckets:
        sim_hist[f"{prev:.2f}-{b:.2f}"] = sum(
            1 for s in top1_sims if prev <= s < b or (b == 1.0 and s == 1.0)
        )
        prev = b

    stage_names = (
        "guardrail_ms",
        "embed_ms",
        "cache_ms",
        "retrieve_ms",
        "rerank_ms",
        "generate_ms",
        "validate_ms",
        "total_ms",
    )
    stage_summary: dict[str, dict[str, float | None]] = {}
    for st in stage_names:
        vals = [
            float((r.get("latency_per_stage") or {}).get(st))
            for r in filtered
            if (r.get("latency_per_stage") or {}).get(st) is not None
        ]
        stage_summary[st] = {
            "count": len(vals),
            "p50_ms": round(percentile(vals, 50.0), 3) if vals else None,
            "p95_ms": round(percentile(vals, 95.0), 3) if vals else None,
            "max_ms": round(max(vals), 3) if vals else None,
        }

    inj_input = 0
    inj_retrieval = 0
    for r in filtered:
        for act in r.get("guardrail_actions") or []:
            if act.get("triggered") and act.get("rail") == "input":
                inj_input += 1
            elif act.get("triggered") and act.get("rail") == "retrieval":
                inj_retrieval += 1

    return {
        "window": window,
        "generated_at": ref_now.isoformat(),
        "total_queries": total,
        "cache_hits": cache_hits,
        "cache_hit_rate": round(cache_hits / total, 4) if total else 0.0,
        "abstentions": abstentions,
        "abstention_rate": round(abstentions / total, 4) if total else 0.0,
        "injection_attempts_flagged": {
            "total": inj_input + inj_retrieval,
            "input_rail": inj_input,
            "retrieval_rail": inj_retrieval,
        },
        "top1_similarity_distribution": {
            "count": len(top1_sims),
            "min": round(min(top1_sims), 4) if top1_sims else None,
            "p25": round(percentile(top1_sims, 25.0), 4) if top1_sims else None,
            "p50": round(percentile(top1_sims, 50.0), 4) if top1_sims else None,
            "p75": round(percentile(top1_sims, 75.0), 4) if top1_sims else None,
            "p95": round(percentile(top1_sims, 95.0), 4) if top1_sims else None,
            "max": round(max(top1_sims), 4) if top1_sims else None,
            "mean": round(sum(top1_sims) / len(top1_sims), 4) if top1_sims else None,
            "histogram": sim_hist,
        },
        "latency_per_stage": stage_summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize RAGOps JSONL trace logs over a time window."
    )
    parser.add_argument(
        "--trace-file", default="traces/traces.jsonl", help="JSONL trace file path"
    )
    parser.add_argument(
        "--window", default="all", help="Time window (e.g. 1h, 24h, 7d, all)"
    )
    parser.add_argument("--out", default=None, help="Optional JSON output file path")
    args = parser.parse_args(argv)

    p = Path(args.trace_file)
    if not p.is_file():
        print(f"ERROR: trace file not found: {p}", file=sys.stderr)
        return 1

    records: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "trace_id" in obj:
            records.append(obj)

    summary = summarize_traces(records, window=args.window)
    text = json.dumps(summary, indent=2)
    print(text)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    # Windows consoles default to cp1252; traces/summaries contain non-ASCII text.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
