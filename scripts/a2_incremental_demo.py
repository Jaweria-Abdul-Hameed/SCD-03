#!/usr/bin/env python3
"""Part A2 end-to-end demo: unchanged / changed / deleted / superseded / rollback.

Runs the REAL ingestion pipeline (indexer/pipeline: A1 verification + A2
incremental update) and the REAL rollback CLI code against a real ChromaDB
(local PersistentClient) with real ``nomic-embed-text`` embeddings from Ollama.
Nothing is simulated: every count below is read back from the vector store.

Steps (each prints counts and the chunk count by document id):
  1. initial ingest of 3 Batch B documents
  2. re-run on the unchanged corpus           -> chunks_embedded == 0
  3. edit one document                        -> only that document's chunks replaced
  4. delete one document                      -> 0 orphan chunks for its source
  5. add a newer version (same doc_id)        -> old version archived + superseded=True
  6. rollback to the archived version         -> old version active again

It needs the full ``chromadb`` package (not ``chromadb-client``). On Windows without
C++ build tools, ``chromadb<1`` cannot build ``chroma-hnswlib``; use the prebuilt wheels:
    pip install --only-binary=:all: "chromadb>=1,<2" requests PyMuPDF pypdf pydantic

Usage (Ollama on the host, nothing else needed):
    OLLAMA_HOST=127.0.0.1:11434 python scripts/a2_incremental_demo.py

Writes eval/results/a2_incremental_demo_<UTC timestamp>.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "indexer"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEMO_DOCS = (
    "b01_merit_scholarship_guidelines.md",
    "b02_research_grant_policy.md",
    "b03_fyp_handbook_2026.md",
)

NEWER_B01 = """---
source: b01_merit_scholarship_guidelines_2027.md
title: FAST-NUCES Merit and Need-Based Scholarship Guidelines 2027
version: 2027-01
page_count: 1
doc_id: merit_scholarship_guidelines
---

# 1.1 Revised Merit Award Criteria (Spring 2027 onwards)

From Spring 2027 the merit award is decided by the Scholarship Committee once per academic
year instead of every semester. Only the top 2 percent of each batch qualify, the SGPA floor
rises to 3.80, and the waiver is capped at 75 percent of tuition. Students on probation or
with any pending disciplinary case are ineligible regardless of grades.

# 1.2 Qarz-e-Hasna Repayment Changes

Repayment now starts twelve months after graduation and may be spread across six years.
Applications are submitted online through the Financial Aid portal with salary slips and
utility bills for the last three months.
"""


def _counts_by_document(client, collection_name: str) -> dict[str, dict[str, int]]:
    coll = client.get_collection(collection_name)
    rows = coll.get(include=["metadatas"])
    total: Counter[str] = Counter()
    active: Counter[str] = Counter()
    for m in rows["metadatas"] or []:
        src = str(m.get("source"))
        total[src] += 1
        if not m.get("superseded"):
            active[src] += 1
    return {s: {"chunks": total[s], "active_chunks": active[s]} for s in sorted(total)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "eval" / "results"))
    parser.add_argument(
        "--work-dir", default=None, help="Scratch dir (default: a new temp dir)"
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("OLLAMA_HOST", "127.0.0.1:11434")
    os.environ.setdefault("EMBED_MODEL", "nomic-embed-text")
    os.environ.setdefault("CHROMA_COLLECTION", "rahbar_a2_demo")

    import chromadb
    from pipeline import __main__ as main_mod
    from pipeline import rollback as rollback_mod
    from pipeline import store as store_mod

    work = Path(args.work_dir or tempfile.mkdtemp(prefix="rahbar_a2_demo_"))
    corpus = work / "corpus"
    batch_new = work / "batch_new"
    lake = work / "lake"
    for d in (corpus, batch_new, lake):
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
    for name in DEMO_DOCS:
        shutil.copy2(REPO_ROOT / "corpus" / "batch_b" / name, corpus / name)

    client = chromadb.PersistentClient(path=str(work / "chroma"))
    collection = store_mod.COLLECTION_NAME
    steps: list[dict] = []

    def ingest(label: str, src: Path, additive: bool = False) -> dict:
        res = main_mod.run_ingestion(
            corpus_dir=src,
            manifest=None,
            chunk_size=512,
            chunk_overlap=64,
            data_root=lake,
            client=client,
            additive=additive,
            skip_cache_invalidation=True,
        )
        by_doc = _counts_by_document(client, collection)
        step = {
            "step": label,
            "counts": res["counts"],
            "dispositions": {
                d["source"]: d.get("disposition") for d in res["documents"]
            },
            "chunks_by_document": by_doc,
        }
        steps.append(step)
        print(f"\n=== {label}")
        print("counts:", json.dumps(res["counts"]))
        print("dispositions:", json.dumps(step["dispositions"]))
        for src_name, c in by_doc.items():
            print(
                f"  {src_name:48s} chunks={c['chunks']:3d}  active={c['active_chunks']:3d}"
            )
        return step

    ingest("1_initial_ingest", corpus)
    s2 = ingest("2_unchanged_rerun", corpus)

    b03 = corpus / "b03_fyp_handbook_2026.md"
    b03.write_text(
        b03.read_text(encoding="utf-8")
        + "\n\n# 3.9 Late Submission Penalty\n\nFYP reports submitted after the deadline lose 10 percent of marks per day.\n",
        encoding="utf-8",
    )
    s3 = ingest("3_changed_b03", corpus)

    (corpus / "b02_research_grant_policy.md").unlink()
    s4 = ingest("4_deleted_b02", corpus)

    (batch_new / "b01_merit_scholarship_guidelines_2027.md").write_text(
        NEWER_B01, encoding="utf-8"
    )
    s5 = ingest("5_newer_version_of_b01", batch_new, additive=True)

    rb = rollback_mod.rollback_document(
        doc_id="merit_scholarship_guidelines",
        to_version="2026-09",
        data_root=lake,
        client=client,
        skip_cache_invalidation=True,
    )
    by_doc_rb = _counts_by_document(client, collection)
    steps.append(
        {
            "step": "6_rollback_b01_to_2026-09",
            "rollback": rb,
            "chunks_by_document": by_doc_rb,
        }
    )
    print("\n=== 6_rollback_b01_to_2026-09")
    print(json.dumps(rb))
    for src_name, c in by_doc_rb.items():
        print(
            f"  {src_name:48s} chunks={c['chunks']:3d}  active={c['active_chunks']:3d}"
        )

    checks = {
        "unchanged_rerun_embeds_zero": s2["counts"]["chunks_embedded"] == 0,
        "changed_doc_only_reembedded": s3["counts"]["docs_updated"] == 1
        and s3["counts"]["docs_skipped_unchanged"] == 2,
        "deleted_doc_has_zero_orphans": "b02_research_grant_policy.md"
        not in s4["chunks_by_document"],
        "newer_version_archives_old": s5["counts"]["docs_superseded_archived"] == 1
        and s5["chunks_by_document"]["b01_merit_scholarship_guidelines.md"][
            "active_chunks"
        ]
        == 0,
        "rollback_restores_old": by_doc_rb["b01_merit_scholarship_guidelines.md"][
            "active_chunks"
        ]
        > 0
        and by_doc_rb["b01_merit_scholarship_guidelines_2027.md"]["active_chunks"] == 0,
    }
    print("\n=== A2 CHECKS")
    for k, v in checks.items():
        print(f"  [{'PASS' if v else 'FAIL'}] {k}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = out_dir / f"a2_incremental_demo_{ts}.json"
    out.write_text(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "embed_model": os.environ["EMBED_MODEL"],
                "chromadb_version": chromadb.__version__,
                "collection": collection,
                "steps": steps,
                "checks": checks,
                "all_passed": all(checks.values()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        f"\nSaved -> {out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out}"
    )
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
