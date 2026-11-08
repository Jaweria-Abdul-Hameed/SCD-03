"""Retrieval: embed the query with the SAME pinned model, query Chroma.

Superseded chunks are filtered out by default (where={"superseded": False})
unless include_old_versions=True — this is the metadata fix for failure
mode E (outdated source); a prompt alone cannot fix it.
Chroma returns cosine *distances*; similarity = 1 - distance.
"""

import chromadb

from ..config import settings

_client = None


def get_chroma_client():
    global _client
    if _client is None:
        _client = chromadb.HttpClient(
            host=settings.CHROMA_HOST, port=settings.CHROMA_PORT
        )
    return _client


def get_chroma_collection():
    return get_chroma_client().get_collection(settings.CHROMA_COLLECTION)


def retrieve(
    query: str,
    query_embedding: list[float],
    top_k: int | None = None,
    include_old_versions: bool = False,
) -> list[dict]:
    """Return top_k chunks as dicts: id, text, metadata, similarity (0-1)."""
    k = top_k if top_k is not None else settings.TOP_K
    collection = get_chroma_collection()
    where = None if include_old_versions else {"superseded": False}
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    chunks: list[dict] = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    for i, chunk_id in enumerate(ids):
        distance = dists[i] if i < len(dists) and dists[i] is not None else 1.0
        similarity = max(0.0, min(1.0, 1.0 - float(distance)))
        chunks.append(
            {
                "id": chunk_id,
                "text": docs[i] if i < len(docs) else "",
                "metadata": metas[i] if i < len(metas) else {},
                "similarity": similarity,
            }
        )
    return chunks


def max_similarity(chunks: list[dict]) -> float:
    return max((c["similarity"] for c in chunks), default=0.0)
