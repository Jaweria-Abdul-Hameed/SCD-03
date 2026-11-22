"""Part A RAGOps unit tests — verification, quarantine, data lake, incremental update & rollback."""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import __main__ as main_mod
from pipeline import datalake as dl_mod
from pipeline import rollback as rollback_mod
from pipeline import verify as verify_mod


class _InMemoryCollection:
    def __init__(self, name: str, metadata: dict | None = None) -> None:
        self.name = name
        self.metadata = dict(metadata or {})
        self.rows: dict[str, dict] = {}

    def upsert(self, ids, documents, embeddings, metadatas):
        for i, cid in enumerate(ids):
            self.rows[cid] = {
                "id": cid,
                "document": documents[i],
                "embedding": embeddings[i],
                "metadata": dict(metadatas[i]),
            }

    def delete(self, ids=None, where=None):
        if ids:
            for cid in ids:
                self.rows.pop(cid, None)
        if where:
            to_del = [
                cid
                for cid, row in self.rows.items()
                if all(row["metadata"].get(k) == v for k, v in where.items())
            ]
            for cid in to_del:
                self.rows.pop(cid, None)

    def get(self, where=None, include=None):
        matched = []
        for cid, row in self.rows.items():
            if where is None:
                matched.append(row)
            elif "$and" in where:
                ok = all(
                    all(row["metadata"].get(k) == v for k, v in clause.items())
                    for clause in where["$and"]
                )
                if ok:
                    matched.append(row)
            else:
                if all(row["metadata"].get(k) == v for k, v in where.items()):
                    matched.append(row)
        return {
            "ids": [r["id"] for r in matched],
            "documents": [r["document"] for r in matched],
            "metadatas": [r["metadata"] for r in matched],
        }

    def update(self, ids, metadatas):
        for cid, meta in zip(ids, metadatas):
            if cid in self.rows:
                self.rows[cid]["metadata"] = dict(meta)

    def count(self):
        return len(self.rows)


class _InMemoryChromaClient:
    def __init__(self) -> None:
        self.collections: dict[str, _InMemoryCollection] = {}

    def get_or_create_collection(self, name: str, metadata: dict | None = None):
        if name not in self.collections:
            self.collections[name] = _InMemoryCollection(name, metadata)
        return self.collections[name]

    def get_collection(self, name: str):
        if name not in self.collections:
            raise ValueError(f"Collection {name} does not exist")
        return self.collections[name]


def _deterministic_embed(texts: list[str]) -> list[list[float]]:
    """Bag-of-words deterministic 768-dim embedding (high similarity for paraphrases)."""
    out = []
    for text in texts:
        vec = [0.0] * 768
        for tok in text.lower().split():
            # Strip punctuation
            clean = "".join(ch for ch in tok if ch.isalnum())
            if not clean:
                continue
            h = int(hashlib.sha256(clean.encode()).hexdigest(), 16)
            vec[h % 768] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out.append([v / norm for v in vec])
    return out


def _write_doc(path: Path, source: str, title: str, version: str, doc_id: str, body: str) -> None:
    content = (
        f"---\n"
        f"source: {source}\n"
        f"title: {title}\n"
        f"version: {version}\n"
        f"page_count: 1\n"
        f"doc_id: {doc_id}\n"
        f"---\n\n"
        f"{body}\n"
    )
    path.write_text(content, encoding="utf-8")


def test_a1_verification_catches_all_four_failure_modes(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    data_root = tmp_path / "lake"
    client = _InMemoryChromaClient()

    # Valid baseline document
    _write_doc(
        corpus_dir / "01_valid.md",
        "01_valid.md",
        "Valid Policy",
        "2026-06",
        "policy_alpha",
        "1.1 Attendance Policy.\n\nStudents must maintain 80 percent attendance in all courses.",
    )
    # 1. Quality fail: empty/too short
    _write_doc(
        corpus_dir / "02_empty.md",
        "02_empty.md",
        "Empty Policy",
        "2026-06",
        "policy_empty",
        "too short",
    )
    # 2. Completeness fail: missing metadata via sidecar
    (corpus_dir / "03_missing_meta.md").write_text(
        "# 2.1 Library Policy\n\nStudents may borrow up to four textbooks for fourteen days.",
        encoding="utf-8",
    )
    (corpus_dir / "03_missing_meta.md.meta.json").write_text(
        '{"source": "03_missing_meta.md", "page_count": 1}', encoding="utf-8"
    )
    # 3. Completeness fail: truncated
    _write_doc(
        corpus_dir / "04_truncated.md",
        "04_truncated.md",
        "Truncated Policy",
        "2026-06",
        "policy_trunc",
        "1.2 Grading Policy.\n\nAll students must complete assignments before the [TRUNCATED]",
    )
    # 4. Uniqueness fail: exact duplicate
    _write_doc(
        corpus_dir / "05_exact_dup.md",
        "05_exact_dup.md",
        "Duplicate Policy",
        "2026-06",
        "policy_dup",
        "1.1 Attendance Policy.\n\nStudents must maintain 80 percent attendance in all courses.",
    )
    # 5. Recency fail: stale older version after active newer version
    _write_doc(
        corpus_dir / "06_stale.md",
        "06_stale.md",
        "Stale Policy",
        "2024-01",
        "policy_alpha",
        "1.1 Old Attendance.\n\nStudents must maintain 75 percent attendance in all courses.",
    )

    report = main_mod.run_ingestion(
        corpus_dir=corpus_dir,
        manifest=None,
        chunk_size=256,
        chunk_overlap=32,
        data_root=data_root,
        client=client,
        embed_fn=_deterministic_embed,
        skip_cache_invalidation=True,
    )
    assert report["counts"]["docs_passed"] == 1
    assert report["counts"]["docs_quarantined"] == 5

    by_src = {d["source"]: d for d in report["documents"]}
    assert by_src["01_valid.md"]["disposition"] == "indexed"
    assert by_src["02_empty.md"]["checks"]["quality"]["pass"] is False
    assert by_src["03_missing_meta.md"]["checks"]["completeness"]["pass"] is False
    assert by_src["04_truncated.md"]["checks"]["completeness"]["pass"] is False
    assert by_src["05_exact_dup.md"]["checks"]["uniqueness"]["pass"] is False
    assert by_src["06_stale.md"]["checks"]["recency"]["pass"] is False

    # Quarantine directory has all 5 failed files, and Chroma only has 01_valid.md
    assert report["vector_store_chunks_by_document"] == {"01_valid.md": 1}
    q_files = list((data_root / "quarantine").rglob("*.md"))
    assert len(q_files) == 5


def test_a2_incremental_unchanged_changed_deleted_and_rollback(tmp_path: Path):
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    data_root = tmp_path / "lake"
    client = _InMemoryChromaClient()

    _write_doc(
        corpus_dir / "doc_a.md",
        "doc_a.md",
        "Document A",
        "2026-06",
        "doc_a",
        "1.1 Rule Alpha.\n\nStudents must register courses online before the deadline.",
    )
    _write_doc(
        corpus_dir / "doc_b.md",
        "doc_b.md",
        "Document B",
        "2026-06",
        "doc_b",
        "2.1 Rule Beta.\n\nTuition fees are refundable within ten days of classes starting.",
    )

    # Run 1: initial index
    r1 = main_mod.run_ingestion(
        corpus_dir=corpus_dir,
        manifest=None,
        chunk_size=256,
        chunk_overlap=32,
        data_root=data_root,
        client=client,
        embed_fn=_deterministic_embed,
        skip_cache_invalidation=True,
    )
    assert r1["counts"]["docs_added"] == 2
    assert r1["counts"]["chunks_embedded"] == 2

    # Run 2: unchanged corpus -> MUST embed 0 chunks
    r2 = main_mod.run_ingestion(
        corpus_dir=corpus_dir,
        manifest=None,
        chunk_size=256,
        chunk_overlap=32,
        data_root=data_root,
        client=client,
        embed_fn=_deterministic_embed,
        skip_cache_invalidation=True,
    )
    assert r2["counts"]["chunks_embedded"] == 0
    assert r2["counts"]["docs_skipped_unchanged"] == 2

    # Run 3: change doc_a only -> doc_b skipped, only doc_a re-embedded
    _write_doc(
        corpus_dir / "doc_a.md",
        "doc_a.md",
        "Document A",
        "2026-06",
        "doc_a",
        "1.1 Rule Alpha Updated.\n\nStudents must register courses online and pay tuition on time.",
    )
    r3 = main_mod.run_ingestion(
        corpus_dir=corpus_dir,
        manifest=None,
        chunk_size=256,
        chunk_overlap=32,
        data_root=data_root,
        client=client,
        embed_fn=_deterministic_embed,
        skip_cache_invalidation=True,
    )
    assert r3["counts"]["docs_updated"] == 1
    assert r3["counts"]["docs_skipped_unchanged"] == 1
    assert r3["counts"]["chunks_embedded"] == 1

    # Run 4: delete doc_b -> 0 orphan chunks remain for doc_b
    (corpus_dir / "doc_b.md").unlink()
    r4 = main_mod.run_ingestion(
        corpus_dir=corpus_dir,
        manifest=None,
        chunk_size=256,
        chunk_overlap=32,
        data_root=data_root,
        client=client,
        embed_fn=_deterministic_embed,
        skip_cache_invalidation=True,
    )
    assert r4["counts"]["docs_deleted"] == 1
    assert "doc_b.md" not in r4["vector_store_chunks_by_document"]
    assert r4["vector_store_chunks_by_document"] == {"doc_a.md": 1}

    # Run 5: newer version of doc_a arrives -> archives 2026-06, marks superseded=True
    batch_new = tmp_path / "batch_new"
    batch_new.mkdir()
    _write_doc(
        batch_new / "doc_a_v2.md",
        "doc_a_v2.md",
        "Document A v2",
        "2026-11",
        "doc_a",
        "1.1 Rule Alpha v2.\n\nRegistration closes forty-eight hours after add-drop week ends.",
    )
    r5 = main_mod.run_ingestion(
        corpus_dir=batch_new,
        manifest=None,
        chunk_size=256,
        chunk_overlap=32,
        data_root=data_root,
        client=client,
        embed_fn=_deterministic_embed,
        additive=True,
        skip_cache_invalidation=True,
    )
    assert r5["counts"]["docs_superseded_archived"] == 1
    coll = client.get_collection("rahbar_corpus")
    active_rows = coll.get(where={"superseded": False})
    assert [m["source"] for m in active_rows["metadatas"]] == ["doc_a_v2.md"]
    assert (data_root / "archive" / "doc_a" / "2026-06" / "doc_a.md").is_file()

    # Rollback to 2026-06
    rb = rollback_mod.rollback_document(
        doc_id="doc_a",
        to_version="2026-06",
        data_root=data_root,
        client=client,
        skip_cache_invalidation=True,
    )
    assert rb["restored"]["version"] == "2026-06"
    assert rb["archived"]["version"] == "2026-11"
    active_after_rb = coll.get(where={"superseded": False})
    assert [m["source"] for m in active_after_rb["metadatas"]] == ["doc_a.md"]


def test_batch_b_committed_corpus_verification_and_quarantine(tmp_path: Path):
    """Verify the real committed corpus/batch_b/ exercises every planted problem."""
    repo_root = Path(__file__).resolve().parents[2]
    batch_b = repo_root / "corpus" / "batch_b"
    assert batch_b.is_dir()

    data_root = tmp_path / "lake"
    client = _InMemoryChromaClient()

    # Seed an existing 2026-06 academic_rules_handbook so b10 supersedes it
    base_dir = tmp_path / "base"
    base_dir.mkdir()
    _write_doc(
        base_dir / "Academic_Rules_Handbook_2026.md",
        "Academic_Rules_Handbook_2026.pdf",
        "Academic Rules Handbook Jun 2026",
        "2026-06",
        "academic_rules_handbook",
        "1.21 Attendance.\n\n100 percent attendance is required; 80 percent minimum for undergraduate students.",
    )
    main_mod.run_ingestion(
        corpus_dir=base_dir,
        manifest=None,
        chunk_size=512,
        chunk_overlap=64,
        data_root=data_root,
        client=client,
        embed_fn=_deterministic_embed,
        skip_cache_invalidation=True,
    )

    report = main_mod.run_ingestion(
        corpus_dir=batch_b,
        manifest=None,
        chunk_size=512,
        chunk_overlap=64,
        data_root=data_root,
        client=client,
        embed_fn=_deterministic_embed,
        near_dup_threshold=0.72,  # lower for simple BoW fake embedder; live nomic uses 0.94
        additive=True,
        skip_cache_invalidation=True,
    )
    by_src = {d["source"]: d for d in report["documents"]}
    assert report["counts"]["docs_scanned"] == 11
    assert by_src["b04_exact_dup_scholarship.md"]["checks"]["uniqueness"]["pass"] is False
    assert by_src["b05_exact_dup_research_grant.md"]["checks"]["uniqueness"]["pass"] is False
    assert by_src["b06_near_dup_scholarship.md"]["checks"]["uniqueness"]["pass"] is False
    assert by_src["b07_corrupt_file.pdf"]["checks"]["quality"]["pass"] is False
    assert by_src["b08_truncated_policy.md"]["checks"]["completeness"]["pass"] is False
    assert by_src["b09_missing_metadata.md"]["checks"]["completeness"]["pass"] is False
    assert by_src["b10_academic_rules_handbook_nov2026.md"]["disposition"] == "indexed_superseding"
    assert by_src["b11_library_fine_addendum_injected.md"]["disposition"] == "indexed"
