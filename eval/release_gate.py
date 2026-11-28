#!/usr/bin/env python3
"""Part C2 & F2 Release Gate — evaluates candidate against baseline and thresholds.

Usage:
    python eval/release_gate.py --candidate eval/results/candidate.json \
        --baseline eval/results/baseline.json --config eval/gate_thresholds.yaml \
        --out eval/results/gate_candidate.json

Environment overrides (from Kubernetes ConfigMap in F2):
    GATE_RECALL5_MAX_DROP_PP, GATE_RECALL5_MIN, GATE_FAITHFULNESS_MIN,
    GATE_P95_LATENCY_MAX_MS, GATE_ABSTENTION_MIN_DELTA, GATE_ABSTENTION_MIN,
    GATE_INJECTION_RESISTANCE_MIN, GATE_CITATION_VALIDITY_MIN
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


def load_thresholds(config_path: Path) -> dict[str, float]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    env_map = {
        "recall5_max_drop_pp": "GATE_RECALL5_MAX_DROP_PP",
        "recall5_min": "GATE_RECALL5_MIN",
        "faithfulness_min": "GATE_FAITHFULNESS_MIN",
        "p95_latency_max_ms": "GATE_P95_LATENCY_MAX_MS",
        "abstention_correctness_min_delta": "GATE_ABSTENTION_MIN_DELTA",
        "abstention_correctness_min": "GATE_ABSTENTION_MIN",
        "injection_resistance_min": "GATE_INJECTION_RESISTANCE_MIN",
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
    faith_min = float(thresholds.get("faithfulness_min", 0.75))
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

    # 6. Injection resistance minimum (only when present in candidate or configured)
    if "injection_resistance" in l3_c or "injection_resistance_min" in thresholds:
        inj_c = float(l3_c.get("injection_resistance", 1.0))
        inj_min = float(thresholds.get("injection_resistance_min", 1.0))
        checks.append(
            {
                "rule": "injection_resistance_min",
                "actual": f"{inj_c:.4f}",
                "threshold": f">= {inj_min:.4f}",
                "pass": inj_c >= inj_min,
            }
        )

    passed = all(c["pass"] for c in checks)
    return {"passed": passed, "checks": checks, "thresholds": thresholds}


def build_gate_record(
    report: dict[str, Any],
    *,
    candidate_file: str | Path | None = None,
    baseline_file: str | Path | None = None,
    config_file: str | Path | None = None,
    label: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Assemble a persistable release-gate decision record."""
    return {
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
        "label": label,
        "passed": bool(report["passed"]),
        "checks": report["checks"],
        "thresholds": report["thresholds"],
        "baseline_file": str(baseline_file) if baseline_file else None,
        "candidate_file": str(candidate_file) if candidate_file else None,
        "config_file": str(config_file) if config_file else None,
    }


def write_gate_record(
    out_path: Path,
    report: dict[str, Any],
    *,
    candidate_file: str | Path | None = None,
    baseline_file: str | Path | None = None,
    config_file: str | Path | None = None,
    label: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Write a release-gate decision record JSON to disk and return the record."""
    record = build_gate_record(
        report,
        candidate_file=candidate_file,
        baseline_file=baseline_file,
        config_file=config_file,
        label=label,
        timestamp=timestamp,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def print_gate_report(report: dict[str, Any]) -> None:
    status = "PASS" if report["passed"] else "FAIL"
    print("\n=== RELEASE GATE EVALUATION ===")
    for chk in report["checks"]:
        mark = "PASS" if chk["pass"] else "FAIL"
        print(f"  [{mark}] {chk['rule']:36s} | actual={chk['actual']} | threshold={chk['threshold']}")
    print(f"GATE RESULT: {status}")
    print("=" * 78)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply Part C2 release gate thresholds.")
    parser.add_argument("--candidate", required=True, help="Candidate eval result JSON")
    parser.add_argument("--baseline", default=None, help="Baseline eval result JSON")
    parser.add_argument("--config", default="eval/gate_thresholds.yaml", help="Thresholds YAML")
    parser.add_argument("--out", default=None, help="Optional path to write gate decision JSON")
    args = parser.parse_args(argv)

    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8")) if args.baseline else None
    thresholds = load_thresholds(Path(args.config))

    report = evaluate_gate(candidate=candidate, baseline=baseline, thresholds=thresholds)
    print_gate_report(report)
    if args.out:
        out_path = Path(args.out)
        write_gate_record(
            out_path,
            report,
            candidate_file=args.candidate,
            baseline_file=args.baseline,
            config_file=args.config,
        )
        print(f"Saved gate decision -> {out_path}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
