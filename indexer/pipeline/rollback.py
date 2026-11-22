"""Rollback CLI (Part A2) — restore an archived superseded document version.

Usage:
    python -m pipeline.rollback --doc-id academic_rules_handbook --to-version 2026-06
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import datalake as dl_mod
from . import store as store_mod


def rollback_document(
    doc_id: str,
    to_version: str,
    data_root: Path | str | None = None,
    client=None,
    skip_cache_invalidation: bool = False,
) -> dict:
    """Restore ``to_version`` for ``doc_id`` and mark any newer active version superseded."""
    lake = dl_mod.DataLakeStore(data_root)
    restored, demoted = lake.restore_version(doc_id=doc_id, target_version=to_version)

    if client is None:
        client = store_mod.get_chroma_client()

    demoted_chunks = 0
    if demoted is not None:
        demoted_chunks = store_mod.set_document_superseded(
            source=demoted["source"],
            superseded=True,
            doc_version=demoted["version"],
            client=client,
        )

    restored_chunks = store_mod.set_document_superseded(
        source=restored["source"],
        superseded=False,
        doc_version=restored["version"],
        client=client,
    )

    if not skip_cache_invalidation:
        store_mod.invalidate_semantic_cache()

    return {
        "doc_id": doc_id,
        "restored": {
            "source": restored["source"],
            "version": restored["version"],
            "superseded": False,
            "chunks_updated": restored_chunks,
        },
        "archived": (
            {
                "source": demoted["source"],
                "version": demoted["version"],
                "superseded": True,
                "chunks_updated": demoted_chunks,
            }
            if demoted
            else None
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Restore an archived superseded document version (Part A2 rollback)."
    )
    parser.add_argument("--doc-id", required=True, help="Logical document ID")
    parser.add_argument("--to-version", required=True, help="Archived version to restore")
    parser.add_argument(
        "--data-root",
        default=None,
        help="Data lake root directory (defaults to DATA_LAKE_ROOT env or 'corpus')",
    )
    parser.add_argument("--skip-cache-invalidation", action="store_true")
    args = parser.parse_args(argv)

    result = rollback_document(
        doc_id=args.doc_id,
        to_version=args.to_version,
        data_root=args.data_root,
        skip_cache_invalidation=args.skip_cache_invalidation,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
