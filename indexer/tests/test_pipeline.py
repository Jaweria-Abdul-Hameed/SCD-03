"""Indexer pipeline tests — pytest, no network / no model needed.

All external services are mocked: Ollama (fake ``requests`` module),
ChromaDB (fake client/collection) and Redis are never touched.
Run:  ``python -m pytest indexer/tests/test_pipeline.py -v``
from the repo root, or ``pytest`` inside the indexer image.
"""

import os
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import chunk as chunk_mod
from pipeline import clean as clean_mod
from pipeline import embed as embed_mod
from pipeline import store as store_mod

# ---------------------------------------------------------------- fixtures

CLAUSE_DOC = """4.2 Registration after failing a prerequisite

A student who fails a prerequisite may register for the course only
with the written permission of the Head of Department. This rule is
a single numbered clause and must not be cut in half by chunking.

1.21 Attendance

A student must attend at least 80 percent of the lectures in a
course to be eligible to sit the final examination.
"""

LONG_DEFINITION = (
    "5.1 Generative AI policy. "
    + "Students may use generative AI tools for brainstorming and drafting, "
    "but the submitted work must be their own original contribution, "
    "all AI assistance must be disclosed in an appendix, "
    "and verbatim AI output submitted as one's own work is plagiarism. " * 6
)


# ---------------------------------------------------------------- chunking


def test_chunker_never_splits_a_short_clause():
    """A numbered clause that fits in the target size stays in one chunk."""
    chunks = chunk_mod.chunk_document(
        {"source": "handbook.pdf", "text": CLAUSE_DOC}, chunk_size=512, chunk_overlap=64
    )
    assert chunks, "expected at least one chunk"
    clause_text = "A student who fails a prerequisite may register for the course"
    holders = [c for c in chunks if clause_text in c["text"]]
    assert len(holders) == 1, (
        f"clause split or lost across chunks: {len(holders)} holders"
    )
    assert holders[0]["section"].startswith("4.2"), holders[0]["section"]


def test_chunker_keeps_long_definition_together_when_it_fits():
    chunks = chunk_mod.chunk_document(
        {"source": "handbook.pdf", "text": LONG_DEFINITION},
        chunk_size=512,
        chunk_overlap=64,
    )
    assert len(chunks) == 1
    assert "plagiarism" in chunks[0]["text"]


def test_chunk_overlap_is_present_and_whole_sentences():
    text = " ".join(f"Sentence number {i} states a clear rule here." for i in range(60))
    chunks = chunk_mod.chunk_document(
        {"source": "doc.pdf", "text": text}, chunk_size=64, chunk_overlap=16
    )
    assert len(chunks) >= 2
    # Overlap: the second chunk must start with whole sentences that
    # also appear at the end of the first chunk.
    first, second = chunks[0]["text"], chunks[1]["text"]
    shared = [s for s in chunk_mod.split_sentences(first) if s in second]
    assert shared, "no whole-sentence overlap between consecutive chunks"
    assert second.split(".")[0].strip(), "overlap must not start mid-sentence"


def test_chunk_size_bound_respected():
    text = " ".join(
        f"Sentence number {i} states a clear rule here." for i in range(120)
    )
    chunks = chunk_mod.chunk_document(
        {"source": "doc.pdf", "text": text}, chunk_size=64, chunk_overlap=16
    )
    for c in chunks:
        assert chunk_mod.estimate_tokens(c["text"]) <= 64 + 16, c["text"][:80]


def test_estimate_tokens_approx_four_chars():
    assert chunk_mod.estimate_tokens("a" * 40) == 10
    assert chunk_mod.estimate_tokens("") == 1


def test_storage_amplification_lecture_example():
    # Lecture example (assignment sec. 3.1): 150 / 120 = 1.25.
    assert chunk_mod.storage_amplification(150, 120) == pytest.approx(1.25)
    assert chunk_mod.storage_amplification(120, 120) == pytest.approx(1.0)
    assert chunk_mod.storage_amplification(0, 0) == 0.0


def test_storage_amplification_grows_with_overlap():
    text = " ".join(f"Sentence number {i} states a clear rule here." for i in range(60))
    original = chunk_mod.estimate_tokens(text)
    small = chunk_mod.chunk_document(
        {"source": "d.pdf", "text": text}, chunk_size=64, chunk_overlap=32
    )
    large = chunk_mod.chunk_document(
        {"source": "d.pdf", "text": text}, chunk_size=64, chunk_overlap=8
    )
    amp_small = chunk_mod.storage_amplification(
        sum(chunk_mod.estimate_tokens(c["text"]) for c in small), original
    )
    amp_large = chunk_mod.storage_amplification(
        sum(chunk_mod.estimate_tokens(c["text"]) for c in large), original
    )
    assert amp_small >= amp_large


# ---------------------------------------------------------------- cleaning


def test_clean_preserves_clause_numbers():
    raw = "4.2 Registration after failing a prerequisite\n\nSome text here.\n12\n"
    cleaned = clean_mod.clean_text(raw)
    assert "4.2" in cleaned
    assert "Registration after failing a prerequisite" in cleaned
    assert "\n12\n" not in cleaned  # page-number-only line removed


def test_clean_rejoins_hyphenated_words():
    assert "registration" in clean_mod.clean_text("regis-\ntration is required.")
    # A real hyphen (well-known) is NOT rejoined: only end-of-line wraps.
    assert "well-known" in clean_mod.clean_text("a well-known rule.")


def test_clean_marks_tables_and_keeps_rows():
    raw = "Fee table\n\nTuition | Per credit hour\n1000 | 5000\n\nAfter the table."
    cleaned = clean_mod.clean_text(raw)
    assert "[TABLE]" in cleaned and "[/TABLE]" in cleaned
    assert "Tuition | Per credit hour" in cleaned
    assert "1000 | 5000" in cleaned


def test_cleaning_rules_documented():
    rules = clean_mod.cleaning_rules()
    assert len(rules) >= 3
    assert any("hyphen" in r for r in rules)
    assert "clause" in clean_mod.NOT_STRIPPED.lower()


# ---------------------------------------------------------------- embedding pin


class _FakeResponse:
    def __init__(self, embedding, model="nomic-embed-text"):
        self._embedding = embedding
        self._model = model

    def raise_for_status(self):
        return None

    def json(self):
        return {"model": self._model, "embedding": self._embedding}


def _install_fake_requests(dimension, model="nomic-embed-text"):
    fake = types.ModuleType("requests")

    def post(url, json=None, timeout=None):
        assert json["model"] == "nomic-embed-text", json
        return _FakeResponse([0.01] * dimension, model=model)

    fake.post = post
    sys.modules["requests"] = fake
    os.environ["LLM_PROVIDER"] = "ollama-host"
    return fake


def test_embed_refuses_wrong_dimension(monkeypatch):
    """Pin guardrail: a 512-dim vector from a wrong model must raise, never store."""
    _install_fake_requests(dimension=512)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    with pytest.raises(ValueError, match="dimension"):
        embed_mod.embed_texts(["hello world"])


def test_embed_accepts_pinned_dimension(monkeypatch):
    _install_fake_requests(dimension=768)
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    vectors = embed_mod.embed_texts(["hello world"])
    assert len(vectors) == 1 and len(vectors[0]) == 768


def test_embed_pin_accessors():
    assert embed_mod.get_model_name() == "nomic-embed-text"
    assert embed_mod.get_dimension() == 768


# ---------------------------------------------------------------- store / metadata


class _FakeCollection:
    def __init__(self):
        self.metadata = None
        self.upserted = None

    def upsert(self, ids, documents, embeddings, metadatas):
        self.upserted = {
            "ids": ids,
            "documents": documents,
            "embeddings": embeddings,
            "metadatas": metadatas,
        }


class _FakeClient:
    def __init__(self):
        self.collection = _FakeCollection()
        self.kwargs = None

    def get_or_create_collection(self, name, metadata=None):
        assert name == "rahbar_corpus"
        self.collection.metadata = metadata
        self.kwargs = {"name": name, "metadata": metadata}
        return self.collection


def _chunk(i=0):
    return {
        "text": f"chunk text {i}",
        "section": "4.2",
        "page": 3,
        "chunk_index": i,
        "source": "handbook-2026-06.pdf",
        "doc_version": "2026-06",
        "superseded": False,
    }


def test_store_metadata_validation_rejects_chunk_missing_superseded():
    bad = {
        "source": "handbook.pdf",
        "section": "4.2",
        "page": 3,
        "doc_version": "2026-06",
    }  # no `superseded`
    with pytest.raises(ValueError, match="superseded"):
        store_mod.validate_metadata(bad)


def test_store_metadata_validation_rejects_non_bool_superseded():
    bad = {
        "source": "h.pdf",
        "section": "4.2",
        "page": 3,
        "doc_version": "2026-06",
        "superseded": "false",
    }  # string, not bool
    with pytest.raises(ValueError, match="superseded"):
        store_mod.validate_metadata(bad)


def test_store_metadata_validation_rejects_bad_page():
    bad = {
        "source": "h.pdf",
        "section": "4.2",
        "page": "3",
        "doc_version": "2026-06",
        "superseded": False,
    }
    with pytest.raises(ValueError, match="page"):
        store_mod.validate_metadata(bad)


def test_store_writes_pin_into_collection_metadata():
    client = _FakeClient()
    chunks = [_chunk(0)]
    store_mod.store_chunks(
        chunks,
        [[0.01] * 768],
        [
            {
                "source": "handbook-2026-06.pdf",
                "section": "4.2",
                "page": 3,
                "doc_version": "2026-06",
                "superseded": False,
            }
        ],
        model_name="nomic-embed-text",
        dimension=768,
        client=client,
    )
    assert client.kwargs["metadata"]["model_name"] == "nomic-embed-text"
    assert client.kwargs["metadata"]["embedding_dimension"] == 768
    assert client.kwargs["metadata"]["dimension"] == 768
    assert client.kwargs["metadata"]["embed_model"] == "nomic-embed-text"
    assert client.collection.upserted["metadatas"][0]["superseded"] is False


def test_store_rejects_mismatched_collection_pin():
    client = _FakeClient()
    client.collection.metadata = {
        "model_name": "other-model",
        "embedding_dimension": 512,
    }
    # Simulate a pre-existing collection built with another model:
    # get_or_create returns the collection whose metadata already disagrees.
    orig = client.get_or_create_collection

    def patched(name, metadata=None):
        coll = orig(name, metadata=metadata)
        coll.metadata = {"model_name": "other-model", "embedding_dimension": 512}
        return coll

    client.get_or_create_collection = patched
    with pytest.raises(ValueError, match="pin conflict"):
        store_mod.store_chunks(
            [_chunk(0)],
            [[0.01] * 768],
            [
                {
                    "source": "h.pdf",
                    "section": "4.2",
                    "page": 1,
                    "doc_version": "2026-06",
                    "superseded": False,
                }
            ],
            model_name="nomic-embed-text",
            dimension=768,
            client=client,
        )


def test_store_rejects_mismatched_collection_dimension_pin():
    client = _FakeClient()
    orig = client.get_or_create_collection

    def patched(name, metadata=None):
        coll = orig(name, metadata=metadata)
        coll.metadata = {"model_name": "nomic-embed-text", "dimension": 512}
        return coll

    client.get_or_create_collection = patched
    with pytest.raises(ValueError, match="pin conflict"):
        store_mod.store_chunks(
            [_chunk(0)],
            [[0.01] * 768],
            [
                {
                    "source": "h.pdf",
                    "section": "4.2",
                    "page": 1,
                    "doc_version": "2026-06",
                    "superseded": False,
                }
            ],
            model_name="nomic-embed-text",
            dimension=768,
            client=client,
        )


def test_superseded_rule_old_version_true_current_false():
    assert store_mod.superseded_for("2023-08") is True
    assert store_mod.superseded_for("2026-06") is False


def test_chunk_id_stable_and_idempotent():
    a = store_mod.chunk_id("handbook.pdf", "4.2", 0)
    b = store_mod.chunk_id("handbook.pdf", "4.2", 0)
    c = store_mod.chunk_id("handbook.pdf", "4.2", 1)
    assert a == b and a != c and len(a) == 64  # sha256 hex


def test_invalidate_cache_never_crashes_when_redis_down(monkeypatch):
    # No redis module / unreachable host must warn, not raise.
    monkeypatch.setitem(sys.modules, "redis", None)
    assert store_mod.invalidate_semantic_cache(host="127.0.0.1", port=6399) == 0


def test_invalidate_cache_calls_flushdb_and_returns_count(monkeypatch):
    class _FakeRedis:
        def __init__(self, *args, **kwargs):
            self.flushed = False

        def keys(self, pattern):
            return ["rahbar:cache:1", "rahbar:cache:2"]

        def flushdb(self):
            self.flushed = True

    fake_mod = types.ModuleType("redis")
    fake_mod.Redis = _FakeRedis
    monkeypatch.setitem(sys.modules, "redis", fake_mod)
    assert store_mod.invalidate_semantic_cache(host="127.0.0.1", port=6379) == 2


def test_invalidate_cache_falls_back_to_delete_when_flushdb_fails(monkeypatch):
    deleted_keys = []

    class _FakeRedis:
        def __init__(self, *args, **kwargs):
            pass

        def keys(self, pattern):
            return ["rahbar:cache:1"]

        def flushdb(self):
            raise RuntimeError("flushdb command disabled")

        def delete(self, *keys):
            deleted_keys.extend(keys)
            return len(keys)

    fake_mod = types.ModuleType("redis")
    fake_mod.Redis = _FakeRedis
    monkeypatch.setitem(sys.modules, "redis", fake_mod)
    assert store_mod.invalidate_semantic_cache(host="127.0.0.1", port=6379) == 1
    assert deleted_keys == ["rahbar:cache:1"]


# ---------------------------------------------------------------- text fixtures (.md/.txt)
def test_extract_text_file_is_single_page(tmp_path):
    from pipeline import extract as extract_mod

    doc = tmp_path / "doc.md"
    doc.write_text("# Clause 1.21\n\nAttendance is 80% minimum.\n", encoding="utf-8")
    pages = extract_mod.extract_text_file(doc)
    assert len(pages) == 1
    assert pages[0]["page"] == 1
    assert "80%" in pages[0]["text"]
    assert pages[0]["is_scanned"] is False and pages[0]["ocr_used"] is False


def test_extract_document_dispatches_by_suffix(tmp_path):
    from pipeline import extract as extract_mod

    txt = tmp_path / "notes.txt"
    txt.write_text("plain text fixture", encoding="utf-8")
    assert extract_mod.extract_document(txt)[0]["text"] == "plain text fixture"
    with pytest.raises(ValueError, match="Unsupported document type"):
        extract_mod.extract_document(tmp_path / "data.csv")


def test_discover_documents_finds_md_fixtures():
    from pipeline.__main__ import discover_documents

    repo = Path(__file__).resolve().parents[2]
    docs = discover_documents(repo / "eval" / "fixtures", None)
    names = [d.name for d in docs]
    # README.md is also a .md file in the fixtures dir and is indexed too.
    # WindowsPath compares parts case-insensitively ('doc1.md' before 'README.md'),
    # whereas PosixPath compares case-sensitively ('README.md' before 'doc1.md').
    # Comparing as a set ensures cross-platform determinism without depending on OS sort order.
    assert set(names) == {"README.md", "doc1.md", "doc2.md", "doc3.md"}


def test_index_document_indexes_markdown_fixture():
    from pipeline.__main__ import index_document

    repo = Path(__file__).resolve().parents[2]
    client = _FakeClient()
    stats = index_document(
        repo / "eval" / "fixtures" / "doc1.md",
        "2026-06",
        False,
        512,
        64,
        client=client,
        embed_fn=lambda texts: [[0.01] * 768 for _ in texts],
    )
    assert stats["chunks"] > 0 and stats["stored"] == stats["chunks"]
    assert client.collection.upserted["metadatas"][0]["page"] == 1
    assert client.collection.upserted["metadatas"][0]["superseded"] is False


# ---------------------------------------------------------------- embed model check / store empty pin
def test_embed_raises_on_model_mismatch(monkeypatch):
    _install_fake_requests(dimension=768, model="other-model")
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    with pytest.raises(ValueError, match="model mismatch"):
        embed_mod.embed_texts(["hello world"])


def test_embed_dimension_reads_embed_dimension_env(monkeypatch):
    _install_fake_requests(dimension=512)
    monkeypatch.setenv("EMBED_DIMENSION", "512")
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    vectors = embed_mod.embed_texts(["hello world"])
    assert len(vectors[0]) == 512
    assert embed_mod.get_dimension() == 512


class _FakeCollectionWithModify(_FakeCollection):
    def modify(self, metadata=None):
        self.metadata = dict(metadata or {})


class _FakeClientWithModify:
    def __init__(self):
        self.collection = _FakeCollectionWithModify()
        self.collection.metadata = {}  # pre-existing collection, EMPTY pin

    def get_or_create_collection(self, name, metadata=None):
        return self.collection


def test_store_writes_pin_into_empty_collection_metadata():
    client = _FakeClientWithModify()
    coll = store_mod.get_or_create_collection(client, "nomic-embed-text", 768)
    assert coll.metadata["model_name"] == "nomic-embed-text"
    assert coll.metadata["embedding_dimension"] == 768


def test_store_raises_when_empty_metadata_cannot_be_modified():
    client = _FakeClient()
    client.collection.metadata = {}  # empty pin, no modify() on this fake
    orig = client.get_or_create_collection

    def patched(name, metadata=None):
        coll = orig(name, metadata=metadata)
        coll.metadata = {}
        return coll

    client.get_or_create_collection = patched
    with pytest.raises(ValueError, match="delete/recreate"):
        store_mod.get_or_create_collection(client, "nomic-embed-text", 768)


def test_collection_uses_cosine_distance():
    # The API treats 1 - distance as cosine similarity; Chroma's default
    # (squared L2) would silently make every query fall below the floor.
    meta = store_mod.collection_metadata("nomic-embed-text", 768)
    assert meta["hnsw:space"] == "cosine"


def test_section_title_is_short_and_readable():
    long_line = "1.21 " + "A student must attend lectures " * 20
    title = chunk_mod.short_title(long_line)
    assert len(title) <= chunk_mod.MAX_TITLE_CHARS + 1
    assert title.startswith("1.21 A student")
    assert chunk_mod.short_title("1.21 Attendance") == "1.21 Attendance"


def test_version_pairs_mark_older_editions_superseded():
    from pipeline.__main__ import _version_from_filename as v

    assert v("EE_PLOs_before_2024_12.pdf") == ("pre-2024", True)
    assert v("EE_PLOs_2024_onwards_11.pdf") == ("2024+", False)
    assert v("Annual_Report_2019-20.pdf") == ("2019-20", True)
    assert v("Annual_Report_2023-24.pdf") == ("2023-24", False)
    assert v("Undergraduate_Academic_Rules_Aug_2023.pdf") == ("2023-08", True)
    # no explicit marker in the name: the caller applies the current-version default
    assert v("Academic_Rules_Handbook_2026.pdf") is None


def test_html_tables_kept_as_atomic_table_blocks(tmp_path):
    from pipeline import extract as extract_mod

    page = tmp_path / "fee.html"
    page.write_text(
        "<html><body><nav>MENU</nav><h1>Fee Structure</h1>"
        "<p>Tuition per credit hour</p>"
        "<table><tr><th>Program</th><th>Fee</th></tr>"
        "<tr><td>BBA / BS</td><td>Rs. 12,000</td></tr></table>"
        "<script>var x=1;</script><footer>FOOT</footer></body></html>",
        encoding="utf-8",
    )
    pages = extract_mod.extract_document(page)
    text = pages[0]["text"]
    assert "[TABLE]" in text and "[/TABLE]" in text
    assert "BBA / BS | Rs. 12,000" in text
    assert "MENU" not in text and "FOOT" not in text and "var x" not in text


def test_html_page_is_split_into_paragraphs_not_one_table_blob(tmp_path):
    """Regression: a page with a table used to be ONE 'paragraph containing
    [TABLE]' and therefore one giant chunk. Blocks are now blank-line
    separated, so the chunker packs by size and keeps each table whole."""
    from pipeline import chunk as chunk_mod
    from pipeline import extract as extract_mod

    body = "".join(
        f"<p>{f'Fee rule sentence number {i}. ' * 12}</p>" for i in range(30)
    )
    page = tmp_path / "fees.html"
    page.write_text(
        f"<html><body>{body}<table><tr><td>BBA / BS</td><td>Rs. 12,000</td></tr></table>"
        f"{body}</body></html>",
        encoding="utf-8",
    )
    pages = extract_mod.extract_document(page)
    chunks = chunk_mod.chunk_document({"source": "fees.html", "pages": pages}, 256, 32)
    assert len(chunks) > 3
    table_chunks = [c for c in chunks if "BBA / BS | Rs. 12,000" in c["text"]]
    assert len(table_chunks) >= 1
    assert all("[TABLE]" in c["text"] and "[/TABLE]" in c["text"] for c in table_chunks)


def test_embedding_text_has_nomic_prefix_and_document_header(monkeypatch):
    from pipeline import embed as embed_mod

    monkeypatch.setenv("EMBED_MODEL", "nomic-embed-text")
    out = embed_mod.document_text(
        "EE_PLOs_2024_onwards_11.pdf", "Introduction", "PLO-1 ..."
    )
    assert out.startswith(
        "search_document: Document: Electrical Engineering (EE) Program Learning Outcomes (PLOs)"
    )
    assert out.endswith("PLO-1 ...")


def test_embed_truncates_over_long_input_instead_of_failing_the_job(monkeypatch):
    """Ollama answers HTTP 500 'input length exceeds the context length' for a
    number-dense 1024-'token' chunk; the embedder retries on a shorter prefix."""
    fake = types.ModuleType("requests")
    seen = []

    class _TooLong:
        status_code = 500
        text = '{"error":"the input length exceeds the context length"}'

        def raise_for_status(self):
            raise RuntimeError("500")

    def post(url, json=None, timeout=None):
        seen.append(len(json["prompt"]))
        if len(json["prompt"]) > 3000:
            return _TooLong()
        return _FakeResponse([0.01] * 768)

    fake.post = post
    sys.modules["requests"] = fake
    os.environ["LLM_PROVIDER"] = "ollama-host"
    monkeypatch.delenv("EMBED_MODEL", raising=False)
    vectors = embed_mod.embed_texts(["x" * 5000])
    assert len(vectors[0]) == 768
    assert seen[0] == 5000 and seen[-1] <= 3000


def test_chunk_page_is_the_page_the_text_starts_on_not_the_first_page_with_the_header():
    """Regression: a running header repeated on every page (and text that is also in the
    table of contents) used to match the FIRST page, so chunks cited the cover page."""
    header = "NATIONAL UNIVERSITY OF COMPUTER AND EMERGING SCIENCES"
    pages = [
        {"page": 1, "text": f"{header}\n\nUndergraduate rules cover"},
        {"page": 2, "text": f"{header}\n\nContents\n3.1 Examination rules ........ 3"},
        {
            "page": 3,
            "text": f"{header}\n\n3.1 Examination rules\n\n"
            "Mobile phones are not allowed in the examination hall.\n\n"
            "3.2 Library rules\n\nSmoking is prohibited in the library.",
        },
        {
            "page": 4,
            "text": f"{header}\n\n3.3 Disciplinary rules\n\n"
            "Anyone found smoking on campus must pay a fine.",
        },
    ]
    doc = {"source": "t.pdf", "doc_version": "v1", "superseded": False, "pages": pages}
    chunks = chunk_mod.chunk_document(doc, chunk_size=40, chunk_overlap=8)
    by_text = {c["text"]: c["page"] for c in chunks}

    def page_of(fragment: str) -> int:
        hits = [p for t, p in by_text.items() if fragment in t]
        assert hits, fragment
        return hits[0]

    assert page_of("Mobile phones are not allowed") == 3
    assert page_of("Anyone found smoking on campus") == 4
    assert [c["page"] for c in chunks] == sorted(c["page"] for c in chunks)
