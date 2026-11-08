#!/usr/bin/env python3
"""Retrieval-only recall@3/@5 for a chunking experiment (no LLM generation).

Runs INSIDE an api pod so it uses the API's own embed + ``retrieve()`` code:

    python scripts/recall_probe.py --prepare  > /tmp/probe_in.json   # local: golden + text->chunk-id map
    kubectl exec -i deploy/api -n rahbar -- python - "$(cat /tmp/probe_in.json)" < scripts/recall_probe.py

Why not run_eval.py for every config? A full eval needs one LLM generation per
question (30-60 s each on CPU Ollama); recall@k depends only on retrieval, so
the three chunking configs are compared on retrieval alone and the shipped
config is then evaluated end to end with run_eval.py.
"""

import json
import sys


def prepare() -> None:
    import argparse
    import importlib.util
    from pathlib import Path

    import chromadb
    import yaml

    spec = importlib.util.spec_from_file_location(
        "mapper", Path(__file__).with_name("map_golden_to_chunks.py")
    )
    mapper = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mapper)  # type: ignore[union-attr]
    ap = argparse.ArgumentParser()
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--port", type=int, default=8001)
    args = ap.parse_args()
    coll = chromadb.HttpClient(host="localhost", port=args.port).get_collection(
        "rahbar_corpus"
    )
    mapping = mapper.resolve(coll, mapper.QUOTES)
    golden = yaml.safe_load(Path("eval/golden.yaml").read_text(encoding="utf-8"))[
        "questions"
    ]
    out = {}
    for q in golden:
        if q["type"] == "must-abstain":
            continue
        out[q["id"]] = {
            "type": q["type"],
            "question": q["question"],
            "expected": mapping.get(q["id"], {}).get("chunk_ids", []),
        }
    out["_chunks"] = coll.count()
    print(json.dumps(out))


def probe() -> None:
    from app.providers import get_provider
    from app.retrieval.retriever import retrieve
    from app.services.chat import query_text

    data = json.loads(sys.argv[1])
    prov = get_provider()
    rows = {}
    for qid, q in data.items():
        if qid.startswith("_"):
            continue
        emb = prov.embed([query_text(q["question"])])[0]
        ids = [
            c["id"] for c in retrieve(q["question"], emb, include_old_versions=False)
        ]
        exp = q["expected"]
        r = {
            k: (len(set(ids[:k]) & set(exp)) / len(exp) if exp else None)
            for k in (3, 5)
        }
        rows[qid] = {"type": q["type"], "r3": r[3], "r5": r[5], "n_expected": len(exp)}
    types = sorted({r["type"] for r in rows.values()})

    def avg(sel: list[dict], key: str) -> float | None:
        vals = [r[key] for r in sel if r[key] is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    allr = list(rows.values())
    summary = {
        "chunks": data.get("_chunks"),
        "recall_at_3": avg(allr, "r3"),
        "recall_at_5": avg(allr, "r5"),
        "by_type": {
            t: {
                "recall_at_3": avg([r for r in allr if r["type"] == t], "r3"),
                "recall_at_5": avg([r for r in allr if r["type"] == t], "r5"),
                "n": len([r for r in allr if r["type"] == t]),
            }
            for t in types
        },
        "per_question": rows,
    }
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    if "--prepare" in sys.argv:
        prepare()
    else:
        probe()
