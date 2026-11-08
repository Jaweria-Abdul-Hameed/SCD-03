"""Chat orchestration — the 8 query-pipeline steps (assignment §3.2).

1 validate -> 2 cache check (skip follow-ups) -> 3 embed (same pinned
model) -> 4 retrieve (superseded filtered) -> 5 augment -> 6 generate ->
7 validate / retry once / canned fallback (NEVER HTTP 500 for bad model
JSON) -> 8 store turn + cache only if safe (not follow-up, not abstention).
One JSON log line per request is emitted here (see main.py middleware
for the request_id): top_k, retrieved chunk ids + scores, abstention flag.
"""

import json
import logging
import time

from ..config import settings
from ..metrics import (
    abstentions_total,
    cache_hits_total,
    cache_misses_total,
    fallbacks_total,
    generation_latency_seconds,
    retrieval_latency_seconds,
    tokens_in_total,
    tokens_out_total,
)
from ..providers import get_provider
from ..retrieval.cache import cache_get, cache_set
from ..retrieval.retriever import max_similarity, retrieve
from ..schemas import Answer, ChatRequest, ChatResponse
from .grounding import (
    abstain_answer,
    build_augmented_prompt,
    parse_answer,
    validate_answer,
)

logger = logging.getLogger("rahbar.api")


def query_text(question: str) -> str:
    """nomic-embed-text needs the ``search_query: `` task prefix (indexer adds
    ``search_document: `` — see indexer/pipeline/embed.py ``document_text``)."""
    if settings.LLM_PROVIDER == "stub" or not settings.EMBED_MODEL.startswith("nomic"):
        return question
    return "search_query: " + question


def _approx_tokens(text: str) -> int:
    return max(1, len(text.split()))


def handle_chat(request: ChatRequest, request_id: str) -> ChatResponse:
    started = time.monotonic()
    chunks: list[dict] = []

    provider = get_provider()
    # Step 3 (needed for the cache check too): embed with the pinned model.
    t0 = time.monotonic()
    query_embedding = provider.embed([query_text(request.question)])[0]
    retrieval_latency_seconds.observe(
        time.monotonic() - t0
    )  # embed is part of retrieval path

    # Step 2: cache check — skipped for follow-up questions.
    # Never read or write the cache for follow-ups, nor for an explicit old-version query: the cache key
    # is the question only, so a cached "current" answer would be served for "include old versions".
    use_cache = not request.follow_up and not request.include_old_versions
    if use_cache:
        try:
            cached = cache_get(request.question, query_embedding)
        except Exception:  # noqa: BLE001 — cache down must not fail the request
            cached = None
        if cached is not None:
            cache_hits_total.inc()
            _log(
                request_id,
                request,
                [],
                cache_hit=True,
                abstention=not cached.answered_from_context,
                latency_ms=(time.monotonic() - started) * 1000,
            )
            return ChatResponse(
                answer=cached,
                request_id=request_id,
                cache_hit=True,
                latency_ms=(time.monotonic() - started) * 1000,
            )
        cache_misses_total.inc()

    # Step 4: retrieve top_k, superseded filtered unless explicitly asked.
    t0 = time.monotonic()
    chunks = retrieve(
        request.question,
        query_embedding,
        include_old_versions=request.include_old_versions,
    )
    retrieval_latency_seconds.observe(time.monotonic() - t0)

    # Abstention: nothing retrieved clears the relevance floor (§3.4).
    if not chunks or max_similarity(chunks) < settings.RELEVANCE_FLOOR:
        floor_answer = abstain_answer()
        abstentions_total.inc()
        _log(
            request_id,
            request,
            chunks,
            cache_hit=False,
            abstention=True,
            latency_ms=(time.monotonic() - started) * 1000,
        )
        return ChatResponse(
            answer=floor_answer,
            request_id=request_id,
            cache_hit=False,
            latency_ms=(time.monotonic() - started) * 1000,
            retrieved_chunk_ids=[c["id"] for c in chunks],
        )

    # Steps 5-6: augment + generate (temperature from env, default 0.2).
    prompt = build_augmented_prompt(request.question, chunks)
    tokens_in_total.inc(_approx_tokens(prompt))
    t0 = time.monotonic()
    raw = provider.generate(prompt)
    generation_latency_seconds.observe(time.monotonic() - t0)

    # Step 7: validate, retry ONCE on failure, then safe canned fallback.
    answer: Answer | None = None
    for attempt in range(2):
        try:
            answer = validate_answer(parse_answer(raw), chunks)
            break
        except Exception:  # noqa: BLE001 — model validation or parse error triggers retry
            if attempt == 0:
                raw = provider.generate(prompt)  # one retry
            else:
                answer = None
    if answer is None:
        fallbacks_total.inc()
        answer = abstain_answer(
            "Model output failed validation twice; returning a safe fallback."
        )
        logger.warning(
            json.dumps({"request_id": request_id, "event": "generation_fallback"})
        )
    tokens_out_total.inc(_approx_tokens(answer.answer))
    if not answer.answered_from_context:
        abstentions_total.inc()

    # Step 8: cache only if safe (not a follow-up, not an old-version query, not an abstention).
    if use_cache:
        try:
            cache_set(request.question, query_embedding, answer)
        except Exception:  # noqa: BLE001, S110 — cache failure must not fail user request
            pass  # cache down must not fail the request

    latency_ms = (time.monotonic() - started) * 1000
    _log(
        request_id,
        request,
        chunks,
        cache_hit=False,
        abstention=not answer.answered_from_context,
        latency_ms=latency_ms,
    )
    return ChatResponse(
        answer=answer,
        request_id=request_id,
        cache_hit=False,
        latency_ms=latency_ms,
        retrieved_chunk_ids=[c["id"] for c in chunks],
    )


def _log(
    request_id: str,
    request: ChatRequest,
    chunks: list[dict],
    cache_hit: bool,
    abstention: bool,
    latency_ms: float,
) -> None:
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "path": "/chat",
                "top_k": settings.TOP_K,
                "chunk_ids": [c["id"] for c in chunks],
                "scores": [round(c["similarity"], 4) for c in chunks],
                "cache_hit": cache_hit,
                "abstention": abstention,
                "latency_ms": round(latency_ms, 2),
                "question": request.question,
            }
        )
    )
