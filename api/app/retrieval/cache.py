"""Redis semantic cache (assignment §3.3).

Key: rahbar:cache:<sha256(normalised question)>. Value: JSON with the
query embedding + the cached Answer. A hit is cosine similarity >=
CACHE_THRESHOLD (env, default 0.96) against a stored embedding — so
paraphrases hit, different questions do not. Exact-key lookup is tried
first; otherwise stored embeddings are scanned (rahbar:cache:*).

SKIP caching for: follow-ups, abstentions (answered_from_context=False),
out-of-scope / validation-failed answers — enforced by callers via
cacheable(), and by cache_set() refusing non-cacheable answers.
invalidate() deletes rahbar:cache:* — called by the indexer on re-index.

CACHE CAVEAT (known trade-off, documented not hidden):
a cache hit returns the stored Answer WITHOUT re-running retrieval, so it
bypasses the relevance floor and the superseded filter for that question:
an answer cached while a document was current stays served until the
cache is invalidated, even if the underlying chunk has since been
superseded. That is why the indexer invalidates the whole cache on every
successful re-index (store.invalidate_semantic_cache) — and why
invalidation failure is only a WARNING, not a Job failure: crashing the
Job would leave no index at all, while a stale cache entry is bounded
(it is only served for a question similar enough to hit it, and the next
re-index retries invalidation). Operators should treat a
"cache_invalidation_failed" warning as a prompt to check Redis, not as
ignorable noise.
"""

import hashlib
import json
import math

import redis

from ..config import settings
from ..schemas import Answer

CACHE_PREFIX = "rahbar:cache:"

_client = None


def get_redis_client():
    global _client
    if _client is None:
        _client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _client


def _cache_key(question: str) -> str:
    normalised = " ".join(question.strip().lower().split())
    return CACHE_PREFIX + hashlib.sha256(normalised.encode()).hexdigest()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def cacheable(answer: Answer) -> bool:
    """Never cache abstentions / out-of-scope answers (a cached mistake
    is served to everyone)."""
    return bool(answer.answered_from_context)


def cache_get(question: str, query_embedding: list[float]) -> Answer | None:
    client = get_redis_client()
    # Fast path: exact question.
    raw = client.get(_cache_key(question))
    if raw:
        entry = json.loads(raw)
        if (
            cosine_similarity(query_embedding, entry["embedding"])
            >= settings.CACHE_THRESHOLD
        ):
            return Answer.model_validate(entry["answer"])
    # Semantic path: scan stored embeddings for a paraphrase hit.
    for key in client.scan_iter(match=CACHE_PREFIX + "*"):
        if key == _cache_key(question):
            continue
        entry = json.loads(client.get(key))
        if (
            cosine_similarity(query_embedding, entry["embedding"])
            >= settings.CACHE_THRESHOLD
        ):
            return Answer.model_validate(entry["answer"])
    return None


def cache_set(question: str, query_embedding: list[float], answer: Answer) -> bool:
    if not cacheable(answer):
        return False
    client = get_redis_client()
    client.set(
        _cache_key(question),
        json.dumps(
            {
                "embedding": query_embedding,
                "answer": answer.model_dump(),
            }
        ),
    )
    return True


def invalidate() -> int:
    """Delete all semantic-cache entries (indexer calls this on re-index)."""
    client = get_redis_client()
    keys = list(client.scan_iter(match=CACHE_PREFIX + "*"))
    if keys:
        return int(client.delete(*keys))
    return 0
