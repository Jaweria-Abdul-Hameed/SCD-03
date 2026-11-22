"""Store stage — vectors + metadata into ChromaDB (assignment sec. 3.1).

Collection: ``rahbar_corpus`` on ``CHROMA_HOST:CHROMA_PORT``
(default ``chroma:8000`` in-cluster).

Embedding-pin guardrail (assignment sec. 4.4)
----------------------------------------------
On collection creation the indexer writes the model name and vector
dimension into the Chroma **collection metadata**::

    {"model_name": "nomic-embed-text",
     "embed_model": "nomic-embed-text",
     "embedding_dimension": 768}

The API compares that metadata with its own ``EMBED_MODEL`` at
startup/readiness and refuses readiness (0/1 READY) on mismatch.
See ``get_or_create_collection()`` — the pin is written there, and
nowhere else, so a collection can never exist without its pin.

Metadata schema (graded — every chunk carries ALL of these)
-----------------------------------------------------------
* ``source``: str — document file / page name, e.g. ``"academic-rules-handbook-2026-06.pdf"``
* ``section``: str — numbered clause / heading, e.g. ``"4.2"``
* ``page``: int — 1-based page number the chunk starts on
* ``doc_version``: str — e.g. ``"2026-06"`` (current) / ``"2023-08"`` (old)
* ``superseded``: bool — True for the older version of the same policy

Superseded rule
---------------
The older version of the same policy (Undergraduate Academic Rules,
**Aug 2023**, ``doc_version="2023-08"``) gets ``superseded=True``;
the current version (Academic Rules Handbook, **Jun 2026**,
``doc_version="2026-06"``) gets ``superseded=False``. Retrieval
filters out ``superseded: true`` by default, so the retriever cannot
faithfully return a repealed clause (failure mode E). The rule is
implemented in ``superseded_for()`` and enforced — not assumed —
by ``validate_metadata()``.

Cache invalidation (assignment sec. 3.3)
-----------------------------------------
On successful index completion the Redis semantic cache is flushed
(``rahbar:cache:*``). If Redis is unreachable the Job logs a warning
and still succeeds — a stale cache is a correctness risk, but
crashing the Job would leave no index at all; the warning is
visible in Job logs and the reindex CronJob re-attempts it weekly.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys

# --- Shared constants (must match the ConfigMap / api) -------------------
COLLECTION_NAME = os.environ.get("CHROMA_COLLECTION", "rahbar_corpus")
CHROMA_HOST = os.environ.get("CHROMA_HOST", "chroma")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8000"))
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
CACHE_KEY_PATTERN = "rahbar:cache:*"

# Superseded rule: (doc_version -> superseded). The Aug 2023 version
# of the Academic Rules is repealed by the Jun 2026 Handbook.
SUPERSEDED_VERSIONS = {"2023-08"}
CURRENT_VERSIONS = {"2026-06"}

REQUIRED_METADATA_FIELDS = ("source", "section", "page", "doc_version", "superseded")


def _log(level: str, event: str, **fields: object) -> None:
    record = {"level": level, "stage": "store", "event": event, **fields}
    print(
        json.dumps(record),
        file=sys.stderr if level in ("warning", "error") else sys.stdout,
    )


def superseded_for(doc_version: str, source: str = "") -> bool:
    """Superseded-marking rule: Aug 2023 policy -> True, Jun 2026 -> False.

    Any version explicitly listed in ``SUPERSEDED_VERSIONS`` is
    superseded. Unknown versions default to False (current until
    proven old) — but the caller must still pass an explicit
    ``superseded`` value; this helper only *derives* it when the
    orchestrator asks for the rule instead of a stored flag.
    """
    return doc_version in SUPERSEDED_VERSIONS


def validate_metadata(metadata: dict) -> dict:
    """Enforce the graded metadata schema; raise on any violation.

    Every chunk MUST carry source (str), section (str), page (int),
    doc_version (str) and superseded (bool — a real bool, not the
    string "true"/"false" and not a missing key). A chunk that fails
    validation is rejected before any write, so a bad chunk can never
    reach Chroma and poison retrieval/citations.
    """
    for field in REQUIRED_METADATA_FIELDS:
        if field not in metadata or metadata[field] is None:
            raise ValueError(
                f"Chunk metadata missing required field {field!r}: {metadata!r}. "
                f"Required fields: {list(REQUIRED_METADATA_FIELDS)}"
            )
    if not isinstance(metadata["source"], str) or not metadata["source"]:
        raise ValueError(f"metadata 'source' must be a non-empty str: {metadata!r}")
    if not isinstance(metadata["section"], str) or not metadata["section"]:
        raise ValueError(f"metadata 'section' must be a non-empty str: {metadata!r}")
    if not isinstance(metadata["page"], int) or isinstance(metadata["page"], bool):
        raise ValueError(f"metadata 'page' must be an int: {metadata!r}")  # noqa: TRY004 — unit test asserts ValueError
    if metadata["page"] < 1:
        raise ValueError(f"metadata 'page' must be >= 1: {metadata!r}")
    if not isinstance(metadata["doc_version"], str) or not metadata["doc_version"]:
        raise ValueError(
            f"metadata 'doc_version' must be a non-empty str: {metadata!r}"
        )
    if not isinstance(metadata["superseded"], bool):
        raise ValueError(  # noqa: TRY004 — unit test asserts ValueError
            f"metadata 'superseded' must be a bool (True/False), got "
            f"{type(metadata['superseded']).__name__}: {metadata!r}"
        )
    return metadata


def chunk_id(source: str, section: str, chunk_index: int) -> str:
    """Stable chunk id: sha256(source + section + chunk_index).

    Idempotent re-runs upsert the same ids, so re-indexing replaces
    chunks instead of duplicating them.
    """
    raw = f"{source}|{section}|{chunk_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def collection_metadata(model_name: str, dimension: int) -> dict:
    """The embedding-pin metadata written onto the Chroma collection."""
    return {
        "model_name": model_name,
        "embed_model": model_name,
        "dimension": dimension,
        "embedding_dimension": dimension,
        # Chroma defaults to squared-L2 distance. The API computes
        # similarity = 1 - distance and compares it with RELEVANCE_FLOOR,
        # which is only meaningful for COSINE distance. Without this key a
        # genuine cosine of 0.37 becomes 2*0.37-1 < 0 and every question
        # abstains (no citations).
        "hnsw:space": "cosine",
        # Approximate search: Chroma's default search ef (10) returned a top-5 that
        # differed from the exact top-5 for 3 of 19 test questions (one golden
        # question lost its relevant chunk). 480 vectors cost nothing to search
        # wider, so use ef=100 (query) / 200 (build).
        "hnsw:search_ef": 100,
        "hnsw:construction_ef": 200,
    }


def get_or_create_collection(client, model_name: str, dimension: int):
    """Get-or-create `rahbar_corpus` WITH the embedding pin in its metadata.

    EMBEDDING-PIN GUARDRAIL (assignment sec. 4.4): the collection is
    created with metadata {"model_name", "embed_model",
    "embedding_dimension"} recording exactly which model produced
    its vectors. The API reads this metadata at readiness and refuses
    to become ready if it disagrees with its own EMBED_MODEL.
    """
    metadata = collection_metadata(model_name, dimension)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME, metadata=metadata
    )
    # If the collection already existed with different metadata, the
    # pin must be corrected, not silently left stale: Chroma stores
    # metadata at creation, so a pre-existing collection whose pin
    # disagrees is a hard error — re-indexing under a new model
    # requires deleting/recreating the collection, never mixing vectors.
    existing = getattr(collection, "metadata", None) or {}
    if not existing:
        # Pre-existing collection with EMPTY {} metadata: Chroma did not
        # apply the pin at creation (or an older run created it bare).
        # Write the pin into it now instead of silently skipping it —
        # otherwise the API readiness check sees no pin and refuses
        # traffic forever. If the client cannot modify collection
        # metadata, fail loudly telling the operator to delete/recreate.
        if hasattr(collection, "modify"):
            collection.modify(metadata=metadata)
            _log(
                "info",
                "collection_pin_written_to_empty_metadata",
                collection=COLLECTION_NAME,
                metadata=metadata,
            )
            existing = dict(metadata)
        else:
            raise ValueError(
                f"Embedding pin missing: existing collection {COLLECTION_NAME!r} "
                f"has empty metadata and this Chroma client cannot modify "
                f"collection metadata — delete/recreate the collection "
                f"(e.g. delete the Chroma PVC / collection) and re-run the "
                f"indexer Job so the pin {metadata!r} is written at creation."
            )
    existing_dim = (
        existing.get("embedding_dimension")
        if existing.get("embedding_dimension") is not None
        else existing.get("dimension")
    )
    if existing and existing.get("model_name") not in (None, model_name):
        raise ValueError(
            f"Embedding pin conflict: existing collection {COLLECTION_NAME!r} "
            f"was built with model_name={existing.get('model_name')!r} "
            f"(dimension={existing_dim!r}), but this "
            f"indexer run uses model_name={model_name!r}. Refusing to mix "
            f"vectors from different models — delete/recreate the collection."
        )
    if existing and existing_dim not in (None, dimension):
        raise ValueError(
            f"Embedding pin conflict: existing collection {COLLECTION_NAME!r} "
            f"has embedding_dimension={existing_dim!r}, "
            f"expected {dimension}. Refusing to mix vector dimensions."
        )
    _log("info", "collection_ready", collection=COLLECTION_NAME, metadata=metadata)
    return collection


def get_chroma_client(
    host: str | None = None,
    port: int | None = None,
    max_retries: int = 15,
    retry_delay: float = 2.0,
):
    """ChromaDB HttpClient to CHROMA_HOST:CHROMA_PORT with retry for readiness."""
    import time

    import chromadb  # lazy: keeps the module importable without the dep

    target_host = host or CHROMA_HOST
    target_port = port or CHROMA_PORT

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            client = chromadb.HttpClient(host=target_host, port=target_port)
            client.heartbeat()
            return client
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < max_retries:
                _log(
                    "warning",
                    "chroma_connect_retry",
                    attempt=attempt,
                    max_retries=max_retries,
                    error=str(e),
                )
                time.sleep(retry_delay)
    if last_err is not None:
        raise last_err
    return chromadb.HttpClient(host=target_host, port=target_port)


def store_chunks(
    chunks: list[dict],
    embeddings: list[list[float]],
    metadatas: list[dict],
    model_name: str,
    dimension: int,
    client=None,
) -> int:
    """Validate metadata, then upsert chunks + vectors into Chroma.

    ``chunks``: [{"text", "section", "page", "chunk_index", "source",
    "doc_version", "superseded"}]; ``metadatas`` may be omitted per
    chunk — if so it is built from the chunk dict and validated the
    same way. Returns the number of chunks upserted.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(f"chunks ({len(chunks)}) != embeddings ({len(embeddings)})")
    if metadatas is not None and len(metadatas) != len(chunks):
        raise ValueError(f"chunks ({len(chunks)}) != metadatas ({len(metadatas)})")
    if client is None:
        client = get_chroma_client()
    collection = get_or_create_collection(client, model_name, dimension)

    ids, documents, vectors, metas = [], [], [], []
    for i, chunk in enumerate(chunks):
        meta = (
            dict(metadatas[i])
            if metadatas is not None
            else {
                "source": chunk["source"],
                "section": chunk["section"],
                "page": chunk["page"],
                "doc_version": chunk["doc_version"],
                "superseded": chunk["superseded"],
            }
        )
        # SUPERSEDED-METADATA ENFORCEMENT: every chunk is validated
        # here, before any write — a chunk missing `superseded` (or
        # any other required field, or with a non-bool superseded)
        # raises ValueError and aborts the store; nothing is upserted.
        validate_metadata(meta)
        if len(embeddings[i]) != dimension:
            raise ValueError(
                f"Chunk {i} embedding dimension {len(embeddings[i])} != "
                f"pinned dimension {dimension}; refusing to store."
            )
        ids.append(
            chunk_id(meta["source"], meta["section"], chunk.get("chunk_index", i))
        )
        documents.append(chunk["text"])
        vectors.append(embeddings[i])
        metas.append(meta)
    collection.upsert(ids=ids, documents=documents, embeddings=vectors, metadatas=metas)
    _log(
        "info",
        "store_done",
        collection=COLLECTION_NAME,
        chunks=len(ids),
        model_name=model_name,
        dimension=dimension,
    )
    return len(ids)


def delete_document_chunks(
    source: str,
    chunk_ids: list[str] | None = None,
    client=None,
) -> int:
    """Delete all chunks for ``source`` by IDs and metadata filter (0 orphans)."""
    if client is None:
        client = get_chroma_client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:  # noqa: BLE001 — collection does not exist yet
        return 0

    deleted = 0
    if chunk_ids:
        try:
            collection.delete(ids=chunk_ids)
            deleted += len(chunk_ids)
        except Exception as exc:  # noqa: BLE001
            _log("warning", "delete_by_ids_failed", source=source, error=str(exc))

    try:
        existing = collection.get(where={"source": source}, include=[])
        remaining_ids = existing.get("ids") or []
        if remaining_ids:
            collection.delete(where={"source": source})
            deleted = max(deleted, len(remaining_ids))
    except Exception as exc:  # noqa: BLE001
        _log("warning", "delete_by_where_failed", source=source, error=str(exc))

    _log("info", "document_chunks_deleted", source=source, deleted=deleted)
    return deleted


def set_document_superseded(
    source: str,
    superseded: bool,
    doc_version: str | None = None,
    client=None,
) -> int:
    """Flip ``superseded`` metadata on stored chunks for archiving or rollback."""
    if client is None:
        client = get_chroma_client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:  # noqa: BLE001
        return 0

    where: dict = {"source": source}
    if doc_version is not None:
        where = {"$and": [{"source": source}, {"doc_version": doc_version}]}

    got = collection.get(where=where, include=["metadatas"])
    ids = got.get("ids") or []
    metas = got.get("metadatas") or []
    if not ids:
        return 0
    updated_metas = []
    for m in metas:
        nm = dict(m or {})
        nm["superseded"] = bool(superseded)
        updated_metas.append(nm)
    collection.update(ids=ids, metadatas=updated_metas)
    _log(
        "info",
        "document_superseded_updated",
        source=source,
        doc_version=doc_version,
        superseded=bool(superseded),
        chunks=len(ids),
    )
    return len(ids)


def chunk_counts_by_document(client=None) -> dict[str, int]:
    """Return {source: chunk_count} across the vector store (orphan-check proof)."""
    if client is None:
        client = get_chroma_client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:  # noqa: BLE001
        return {}
    got = collection.get(include=["metadatas"])
    counts: dict[str, int] = {}
    for meta in got.get("metadatas") or []:
        src = str((meta or {}).get("source") or "unknown")
        counts[src] = counts.get(src, 0) + 1
    return dict(sorted(counts.items()))


def invalidate_semantic_cache(host: str | None = None, port: int | None = None) -> int:
    """Invalidate the Redis semantic cache (flush `rahbar:cache:*`).

    Called on successful index completion (assignment sec. 3.3).
    If Redis is unreachable, logs a warning and returns 0 — the Job
    must NEVER crash on cache failure (a stale cache is bad, no
    index at all is worse).
    """
    try:
        import redis  # lazy import

        client = redis.Redis(
            host=host or REDIS_HOST,
            port=port or REDIS_PORT,
            socket_connect_timeout=5,
            decode_responses=True,
        )
        keys = client.keys(CACHE_KEY_PATTERN)
        deleted = len(keys)
        try:
            client.flushdb()
        except Exception:  # noqa: BLE001 — flushdb command unsupported or restricted; fallback to pattern delete
            if keys:
                deleted = int(client.delete(*keys))
            else:
                deleted = 0
        _log(
            "info", "cache_invalidated", pattern=CACHE_KEY_PATTERN, keys_deleted=deleted
        )
        return int(deleted)
    except Exception as exc:  # noqa: BLE001 — Redis unreachable; stale semantic-cache entries may survive
        _log(
            "warning",
            "cache_invalidation_failed",
            pattern=CACHE_KEY_PATTERN,
            error=str(exc),
            hint="Redis unreachable; stale semantic-cache entries may survive — re-run will retry",
        )
        return 0


if __name__ == "__main__":
    _log(
        "info",
        "store_module",
        note="Use python -m pipeline as the Job entrypoint; see pipeline/__main__.py",
    )
