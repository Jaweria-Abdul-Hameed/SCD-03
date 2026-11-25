#!/usr/bin/env python3
"""Part C2 & F2 Release Gate — evaluates candidate against baseline and thresholds.

Usage:
    python eval/release_gate.py --candidate eval/results/candidate.json \
        --baseline eval/results/baseline.json --config eval/gate_thresholds.yaml

Environment overrides (from Kubernetes ConfigMap in F2):
    GATE_RECALL5_MAX_DROP_PP, GATE_FAITHFULNESS_MIN, GATE_P95_LATENCY_MAX_MS,
    GATE_ABSTENTION_MIN_DELTA, GATE_ABSTENTION_MIN, GATE_CITATION_VALIDITY_MIN
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml


def load_thresholds(config_path: Path) -> dict[str, float]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    env_map = {
        "recall5_max_drop_pp": "GATE_RECALL5_MAX_DROP_PP",
        "faithfulness_min": "GATE_FAITHFULNESS_MIN",
        "p95_latency_max_ms": "GATE_P95_LATENCY_MAX_MS",
        "abstention_correctness_min_delta": "GATE_ABSTENTION_MIN_DELTA",
        "abstention_correctness_min": "GATE_ABSTENTION_MIN",
        "citation_validity_min": "GATE_CITATION_VALIDITY_MIN",
    }
    out = {k: float(v) for k, v in data.items()}
    for key, env_var in env_map.items():
        if env_var in os.environ and os.environ[env_var].strip():
            out[key] = float(os.environ[env_var])
    return out


def evaluate_gate(
    candidate: dict[str, Any],
    baseline: dict[str, Any] | None,
    thresholds: dict[str, float],
) -> dict[str, Any]:
    l2_c = candidate["level2_component"]
    l3_c = candidate["level3_e2e"]

    checks: list[dict[str, Any]] = []

    # 1. Recall@5 drop vs baseline (or floor if no baseline)
    r5_c = float(l2_c["recall@5"])
    if baseline is not None:
        r5_b = float(baseline["level2_component"]["recall@5"])
        drop = round(r5_b - r5_c, 4)
        max_drop = float(thresholds.get("recall5_max_drop_pp", 0.02))
        checks.append(
            {
                "rule": "recall@5_max_drop_vs_baseline",
                "actual": f"{r5_c:.4f} (baseline={r5_b:.4f}, drop={drop:+.4f})",
                "threshold": f"drop <= {max_drop:.4f}",
                "pass": drop <= max_drop,
            }
        )
    else:
        min_r5 = float(thresholds.get("recall5_min", 0.70))
        checks.append(
            {
                "rule": "recall@5_min",
                "actual": f"{r5_c:.4f}",
                "threshold": f">= {min_r5:.4f}",
                "pass": r5_c >= min_r5,
            }
        )

    # 2. Faithfulness minimum
    faith_c = float(l3_c["faithfulness"])
    faith_min = float(thresholds.get("faithfulness_min", 0.80))
    checks.append(
        {
            "rule": "faithfulness_min",
            "actual": f"{faith_c:.4f}",
            "threshold": f">= {faith_min:.4f}",
            "pass": faith_c >= faith_min,
        }
    )

    # 3. p95 latency maximum
    p95_c = float(l3_c["latency_p95_ms"])
    p95_max = float(thresholds.get("p95_latency_max_ms", 45000.0))
    checks.append(
        {
            "rule": "p95_latency_max_ms",
            "actual": f"{p95_c:.2f} ms",
            "threshold": f"<= {p95_max:.2f} ms",
            "pass": p95_c <= p95_max,
        }
    )

    # 4. Abstention correctness not lower than baseline
    abs_c = float(l3_c["abstention_correctness"])
    if baseline is not None:
        abs_b = float(baseline["level3_e2e"]["abstention_correctness"])
        min_delta = float(thresholds.get("abstention_correctness_min_delta", 0.0))
        delta = round(abs_c - abs_b, 4)
        checks.append(
            {
                "rule": "abstention_correctness_vs_baseline",
                "actual": f"{abs_c:.4f} (baseline={abs_b:.4f}, delta={delta:+.4f})",
                "threshold": f"delta >= {min_delta:+.4f}",
                "pass": delta >= min_delta,
            }
        )
    else:
        abs_min = float(thresholds.get("abstention_correctness_min", 0.80))
        checks.append(
            {
                "rule": "abstention_correctness_min",
                "actual": f"{abs_c:.4f}",
                "threshold": f">= {abs_min:.4f}",
                "pass": abs_c >= abs_min,
            }
        )

    # 5. Citation validity minimum
    cit_c = float(l3_c["citation_validity"])
    cit_min = float(thresholds.get("citation_validity_min", 0.90))
    checks.append(
        {
            "rule": "citation_validity_min",
            "actual": f"{cit_c:.4f}",
            "threshold": f">= {cit_min:.4f}",
            "pass": cit_c >= cit_min,
        }
    )

    passed = all(c["pass"] for c in checks)
    return {"passed": passed, "checks": checks, "thresholds": thresholds}


def print_gate_report(report: dict[str, Any]) -> None:
    status = "PASS" if report["passed"] else "FAIL"
    print("\n=== RELEASE GATE EVALUATION ===")
    for chk in report["checks"]:
        mark = "PASS" if chk["pass"] else "FAIL"
        print(
            f"  [{mark}] {chk['rule']:36s} | actual={chk['actual']} | threshold={chk['threshold']}"
        )
    print(f"GATE RESULT: {status}")
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply Part C2 release gate thresholds."
    )
    parser.add_argument("--candidate", required=True, help="Candidate eval result JSON")
    parser.add_argument("--baseline", default=None, help="Baseline eval result JSON")
    parser.add_argument(
        "--config", default="eval/gate_thresholds.yaml", help="Thresholds YAML"
    )
    args = parser.parse_args(argv)

    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    baseline = (
        json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        if args.baseline
        else None
    )
    thresholds = load_thresholds(Path(args.config))

    report = evaluate_gate(
        candidate=candidate, baseline=baseline, thresholds=thresholds
    )
    print_gate_report(report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    # Windows consoles default to cp1252; traces/summaries contain non-ASCII text.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
