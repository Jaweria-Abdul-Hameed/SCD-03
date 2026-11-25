#!/usr/bin/env python3
"""Part E2 & E4 Query Coverage Checker (Paper §4.2.7).

Embeds live user queries (eval/live_queries.jsonl) and golden test questions
(eval/golden.jsonl), finds each live query's nearest golden question by cosine
similarity, reports coverage share above --sim-threshold, groups uncovered
queries into topics, and exits non-zero (1) if coverage < --coverage-threshold.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from eval.run_ragops_eval import cosine_sim, embed_texts_ollama, load_jsonl


def infer_topic(query: str, explicit_topic: str | None = None) -> str:
    if explicit_topic and explicit_topic.strip():
        return explicit_topic.strip()
    low = query.lower()
    if any(
        k in low for k in ("alumni", "transcript", "degree verification", "convocation")
    ):
        return "alumni_and_degree_verification"
    if any(
        k in low for k in ("cafeteria", "gym", "sports", "parking", "medical", "clinic")
    ):
        return "campus_facilities_and_services"
    if any(
        k in low
        for k in (
            "exchange",
            "erasmus",
            "international",
            "study abroad",
            "transfer credit",
        )
    ):
        return "international_exchange_and_transfers"
    if any(k in low for k in ("internship", "career", "job fair", "placement")):
        return "career_services_and_internships"
    return "other_uncovered"


def compute_coverage(
    live_queries: list[dict[str, Any]],
    golden_questions: list[dict[str, Any]],
    *,
    ollama_host: str,
    embed_model: str,
    provider_mode: str,
    sim_threshold: float,
    coverage_threshold: float,
) -> dict[str, Any]:
    live_texts = [q["query"] for q in live_queries]
    gold_texts = [g["question"] for g in golden_questions]

    live_vecs, _ = embed_texts_ollama(
        live_texts, ollama_host, embed_model, provider_mode
    )
    gold_vecs, _ = embed_texts_ollama(
        gold_texts, ollama_host, embed_model, provider_mode
    )

    rows: list[dict[str, Any]] = []
    uncovered: list[dict[str, Any]] = []
    topics: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for q_obj, l_vec in zip(live_queries, live_vecs):
        best_sim = -1.0
        best_gold = None
        for g_obj, g_vec in zip(golden_questions, gold_vecs):
            s = cosine_sim(l_vec, g_vec)
            if s > best_sim:
                best_sim = s
                best_gold = g_obj
        covered = best_sim >= sim_threshold
        entry = {
            "id": q_obj["id"],
            "query": q_obj["query"],
            "nearest_golden_id": best_gold["id"] if best_gold else None,
            "nearest_golden_question": best_gold["question"] if best_gold else None,
            "max_similarity": round(best_sim, 4),
            "covered": covered,
        }
        rows.append(entry)
        if not covered:
            topic = infer_topic(q_obj["query"], q_obj.get("topic"))
            entry["topic"] = topic
            uncovered.append(entry)
            topics[topic].append(entry)

    total = len(rows)
    covered_count = total - len(uncovered)
    coverage_share = (covered_count / total) if total else 0.0
    passed = coverage_share >= coverage_threshold

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "total_live_queries": total,
        "golden_questions_count": len(golden_questions),
        "sim_threshold": sim_threshold,
        "coverage_threshold": coverage_threshold,
        "covered_count": covered_count,
        "uncovered_count": len(uncovered),
        "coverage_share": round(coverage_share, 4),
        "passed": passed,
        "uncovered_by_topic": dict(sorted(topics.items())),
        "uncovered_queries": uncovered,
        "all_queries": rows,
    }


def print_coverage_report(report: dict[str, Any]) -> None:
    pct = report["coverage_share"] * 100.0
    thresh_pct = report["coverage_threshold"] * 100.0
    status = "PASS" if report["passed"] else "FAIL (COVERAGE GAP)"
    print("\n" + "=" * 78)
    print(f"PART E QUERY COVERAGE REPORT  [{status}]")
    print("=" * 78)
    print(
        f"Live Queries: {report['total_live_queries']} | Golden Questions: {report['golden_questions_count']} | "
        f"Sim Threshold: {report['sim_threshold']:.2f}"
    )
    print(
        f"Covered     : {report['covered_count']}/{report['total_live_queries']} "
        f"({pct:.1f}%) | Required: >= {thresh_pct:.1f}%"
    )
    print("-" * 78)
    print("UNCOVERED QUERIES GROUPED BY TOPIC:")
    for topic, items in report["uncovered_by_topic"].items():
        print(f"  Topic [{topic}] ({len(items)} queries):")
        for it in items:
            print(
                f"    - ({it['id']}, sim={it['max_similarity']:.4f}, nearest={it['nearest_golden_id']}) "
                f"{it['query']}"
            )
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check live query coverage against golden.jsonl."
    )
    parser.add_argument("--live-queries", default="eval/live_queries.jsonl")
    parser.add_argument("--golden", default="eval/golden.jsonl")
    parser.add_argument(
        "--ollama-host", default=os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
    )
    parser.add_argument(
        "--embed-model", default=os.environ.get("EMBED_MODEL", "nomic-embed-text")
    )
    parser.add_argument(
        "--provider-mode", default=os.environ.get("LLM_PROVIDER", "ollama-host")
    )
    parser.add_argument("--sim-threshold", type=float, default=0.70)
    parser.add_argument("--coverage-threshold", type=float, default=0.85)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    live_queries = load_jsonl(Path(args.live_queries))
    golden_questions = load_jsonl(Path(args.golden))

    report = compute_coverage(
        live_queries,
        golden_questions,
        ollama_host=args.ollama_host,
        embed_model=args.embed_model,
        provider_mode=args.provider_mode,
        sim_threshold=args.sim_threshold,
        coverage_threshold=args.coverage_threshold,
    )
    print_coverage_report(report)
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    # Windows consoles default to cp1252; traces/summaries contain non-ASCII text.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
