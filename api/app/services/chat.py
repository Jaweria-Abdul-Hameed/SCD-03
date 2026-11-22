"""Chat orchestration — the 8 query-pipeline steps + RAGOps Part D instrumentation.

1 validate -> 2 input rail & embed -> 3 cache check (skip follow-ups) ->
4 retrieve (superseded filtered) & reranked order -> 5 retrieval rail (D4) ->
6 augment & generate -> 7 validate / retry once / canned fallback ->
8 store turn + emit 16-field JSONL trace (D1) + update Prometheus metrics (D3).
"""

import json
import logging
import time
import uuid

from ..config import settings
from ..metrics import (
    abstentions_total,
    cache_hits_total,
    cache_misses_total,
    fallbacks_total,
    generation_latency_seconds,
    injection_attempts_flagged_total,
    queries_total,
    retrieval_latency_seconds,
    stage_latency_seconds,
    tokens_in_total,
    tokens_out_total,
    top1_retrieval_similarity,
)
from ..providers import get_provider
from ..retrieval.cache import cache_get, cache_set
from ..retrieval.retriever import max_similarity, retrieve
from ..schemas import Answer, ChatRequest, ChatResponse
from .grounding import (
    abstain_answer,
    build_augmented_prompt,
    is_heading_only,
    is_list_question,
    parse_answer,
    validate_answer,
)
from .guardrails import apply_retrieval_rail, scan_input_rail
from .tracing import build_trace_record, emit_trace

logger = logging.getLogger("rahbar.api")


def query_text(question: str) -> str:
    """nomic-embed-text needs the ``search_query: `` task prefix (indexer adds
    ``search_document: `` — see indexer/pipeline/embed.py ``document_text``)."""
    if settings.LLM_PROVIDER == "stub" or not settings.EMBED_MODEL.startswith("nomic"):
        return question
    return "search_query: " + question


def _approx_tokens(text: str) -> int:
    return max(1, len(text.split()))


def _observe_stage(stage: str, elapsed_s: float) -> float:
    stage_latency_seconds.labels(stage=stage).observe(elapsed_s)
    return elapsed_s * 1000.0


def _compact_retrieved(chunks: list[dict]) -> list[dict]:
    return [
        {
            "id": c.get("id", ""),
            "text": c.get("text", ""),
            "metadata": dict(c.get("metadata") or {}),
            "similarity": round(float(c.get("similarity", 0.0)), 6),
        }
        for c in chunks
    ]


def handle_chat(request: ChatRequest, request_id: str) -> ChatResponse:
    started = time.monotonic()
    trace_id = request_id if request_id and request_id != "unknown" else str(uuid.uuid4())
    queries_total.inc()

    chunks: list[dict] = []
    guardrail_actions: list[dict] = []
    stage_ms: dict[str, float] = {
        "guardrail_ms": 0.0,
        "embed_ms": 0.0,
        "cache_ms": 0.0,
        "retrieve_ms": 0.0,
        "rerank_ms": 0.0,
        "generate_ms": 0.0,
        "validate_ms": 0.0,
        "total_ms": 0.0,
    }
    filters_applied = (
        {"superseded": None, "include_old_versions": True}
        if request.include_old_versions
        else {"superseded": False, "include_old_versions": False}
    )

    # Input Rail (I)
    t_rail0 = time.monotonic()
    input_action = scan_input_rail(request.question)
    guardrail_actions.append(input_action)
    if input_action.get("triggered"):
        injection_attempts_flagged_total.labels(rail="input").inc()
    stage_ms["guardrail_ms"] += (time.monotonic() - t_rail0) * 1000.0

    rewritten = query_text(request.question)
    provider = get_provider()

    # Step 3: embed with the pinned model
    t0 = time.monotonic()
    query_embedding = provider.embed([rewritten])[0]
    emb_s = time.monotonic() - t0
    retrieval_latency_seconds.observe(emb_s)
    stage_ms["embed_ms"] = _observe_stage("embed", emb_s)

    # Step 2: semantic cache check — skipped for follow-ups & explicit old-version queries
    use_cache = not request.follow_up and not request.include_old_versions
    if use_cache:
        t_c0 = time.monotonic()
        try:
            cached = cache_get(request.question, query_embedding)
        except Exception:  # noqa: BLE001 — cache down must not fail the request
            cached = None
        c_s = time.monotonic() - t_c0
        stage_ms["cache_ms"] = _observe_stage("cache", c_s)
        if cached is not None:
            cache_hits_total.inc()
            total_s = time.monotonic() - started
            stage_ms["total_ms"] = _observe_stage("total", total_s)
            emit_trace(
                build_trace_record(
                    trace_id=trace_id,
                    user_query=request.question,
                    rewritten_query=rewritten if rewritten != request.question else None,
                    retrieved_chunks=[],
                    filters_applied=filters_applied,
                    reranked_order=[],
                    full_prompt="",
                    response_dict=cached.model_dump(),
                    citations=[c.model_dump() for c in cached.citations],
                    guardrail_actions=guardrail_actions,
                    latency_per_stage=stage_ms,
                    cache_hit=True,
                )
            )
            return ChatResponse(
                answer=cached,
                request_id=request_id,
                trace_id=trace_id,
                cache_hit=True,
                latency_ms=stage_ms["total_ms"],
                guardrail_actions=guardrail_actions,
            )
        cache_misses_total.inc()

    # Step 4: retrieve top_k, superseded filtered unless explicitly asked
    t0 = time.monotonic()
    chunks = retrieve(
        request.question,
        query_embedding,
        include_old_versions=request.include_old_versions,
    )
    ret_s = time.monotonic() - t0
    retrieval_latency_seconds.observe(ret_s)
    stage_ms["retrieve_ms"] = _observe_stage("retrieve", ret_s)

    # Rerank / score ordering telemetry (deterministic cosine-score sort)
    t_rk0 = time.monotonic()
    chunks = sorted(chunks, key=lambda c: float(c.get("similarity", 0.0)), reverse=True)
    reranked_order = [
        {"rank": idx + 1, "chunk_id": c.get("id", ""), "score": round(float(c.get("similarity", 0.0)), 6)}
        for idx, c in enumerate(chunks)
    ]
    stage_ms["rerank_ms"] = _observe_stage("rerank", time.monotonic() - t_rk0)

    top1_sim = max_similarity(chunks)
    if chunks:
        top1_retrieval_similarity.observe(top1_sim)

    # Retrieval Rail (R) — D4: inspect retrieved chunks for injected instructions
    t_rrail0 = time.monotonic()
    sanitized_chunks, retrieval_actions = apply_retrieval_rail(
        chunks, mode=settings.RETRIEVAL_RAIL_MODE
    )
    for act in retrieval_actions:
        guardrail_actions.append(act)
        if act.get("triggered"):
            injection_attempts_flagged_total.labels(rail="retrieval").inc()
    rrail_s = time.monotonic() - t_rrail0
    stage_ms["guardrail_ms"] += rrail_s * 1000.0
    stage_latency_seconds.labels(stage="guardrail").observe(stage_ms["guardrail_ms"] / 1000.0)

    # Abstention: nothing retrieved clears the relevance floor (§3.4)
    if not sanitized_chunks or max_similarity(sanitized_chunks) < settings.RELEVANCE_FLOOR:
        guardrail_actions.append(
            {
                "rail": "relevance_floor",
                "triggered": True,
                "action": "abstain_below_floor",
                "top1_similarity": round(top1_sim, 4),
                "relevance_floor": settings.RELEVANCE_FLOOR,
                "reason": f"max_similarity={top1_sim:.4f} < RELEVANCE_FLOOR={settings.RELEVANCE_FLOOR}",
            }
        )
        floor_answer = abstain_answer()
        abstentions_total.inc()
        total_s = time.monotonic() - started
        stage_ms["total_ms"] = _observe_stage("total", total_s)
        emit_trace(
            build_trace_record(
                trace_id=trace_id,
                user_query=request.question,
                rewritten_query=rewritten if rewritten != request.question else None,
                retrieved_chunks=chunks,
                filters_applied=filters_applied,
                reranked_order=reranked_order,
                full_prompt="",
                response_dict=floor_answer.model_dump(),
                citations=[],
                guardrail_actions=guardrail_actions,
                latency_per_stage=stage_ms,
                cache_hit=False,
            )
        )
        return ChatResponse(
            answer=floor_answer,
            request_id=request_id,
            trace_id=trace_id,
            cache_hit=False,
            latency_ms=stage_ms["total_ms"],
            retrieved_chunk_ids=[c["id"] for c in chunks],
            retrieved_chunks=_compact_retrieved(chunks),
            guardrail_actions=guardrail_actions,
        )

    # Steps 5-6: augment + generate
    prompt = build_augmented_prompt(
        request.question, sanitized_chunks, template=settings.PROMPT_TEMPLATE
    )
    tokens_in_total.inc(_approx_tokens(prompt))
    t0 = time.monotonic()
    raw = provider.generate(prompt)
    gen_s = time.monotonic() - t0
    generation_latency_seconds.observe(gen_s)
    stage_ms["generate_ms"] = _observe_stage("generate", gen_s)

    # Step 7: validate, retry ONCE on failure, then safe canned fallback
    t_val0 = time.monotonic()
    answer: Answer | None = None
    for attempt in range(2):
        try:
            answer = validate_answer(parse_answer(raw), sanitized_chunks)
            break
        except Exception:  # noqa: BLE001 — model validation or parse error triggers retry
            if attempt == 0:
                t_retry0 = time.monotonic()
                raw = provider.generate(prompt)
                extra_s = time.monotonic() - t_retry0
                generation_latency_seconds.observe(extra_s)
                stage_ms["generate_ms"] += extra_s * 1000.0
            else:
                answer = None

    if (
        answer is not None
        and is_list_question(request.question)
        and is_heading_only(answer)
    ):
        try:
            retry_raw = provider.generate(
                prompt
                + "\n\nIMPORTANT: your previous answer was only a heading. Write the "
                "complete answer now: one '- ' bullet line per relevant rule or item "
                "in the evidence, stating what it says."
            )
            retry = validate_answer(parse_answer(retry_raw), sanitized_chunks)
            if retry.answered_from_context and len(retry.answer) > len(answer.answer):
                answer = retry
        except Exception:  # noqa: BLE001, S110 — keep the first (valid) answer
            pass

    if answer is None:
        fallbacks_total.inc()
        answer = abstain_answer(
            "Model output failed validation twice; returning a safe fallback."
        )
        guardrail_actions.append(
            {
                "rail": "output",
                "triggered": True,
                "action": "canned_fallback_after_validation_failure",
                "reason": "Model JSON/schema validation failed twice",
            }
        )
        logger.warning(
            json.dumps({"request_id": request_id, "trace_id": trace_id, "event": "generation_fallback"})
        )
    else:
        guardrail_actions.append(
            {
                "rail": "output",
                "triggered": not answer.answered_from_context,
                "action": "abstain" if not answer.answered_from_context else "grounded_pass",
                "citations_kept": len(answer.citations),
                "reason": answer.reasoning[:180],
            }
        )
    stage_ms["validate_ms"] = _observe_stage("validate", time.monotonic() - t_val0)

    tokens_out_total.inc(_approx_tokens(answer.answer))
    if not answer.answered_from_context:
        abstentions_total.inc()

    # Step 8: cache only if safe (not follow-up, not old-version, not abstention)
    if use_cache:
        try:
            cache_set(request.question, query_embedding, answer)
        except Exception:  # noqa: BLE001, S110
            pass

    total_s = time.monotonic() - started
    stage_ms["total_ms"] = _observe_stage("total", total_s)

    emit_trace(
        build_trace_record(
            trace_id=trace_id,
            user_query=request.question,
            rewritten_query=rewritten if rewritten != request.question else None,
            retrieved_chunks=chunks,
            filters_applied=filters_applied,
            reranked_order=reranked_order,
            full_prompt=prompt,
            response_dict=answer.model_dump(),
            citations=[c.model_dump() for c in answer.citations],
            guardrail_actions=guardrail_actions,
            latency_per_stage=stage_ms,
            cache_hit=False,
        )
    )
    return ChatResponse(
        answer=answer,
        request_id=request_id,
        trace_id=trace_id,
        cache_hit=False,
        latency_ms=stage_ms["total_ms"],
        retrieved_chunk_ids=[c["id"] for c in chunks],
        retrieved_chunks=_compact_retrieved(sanitized_chunks),
        guardrail_actions=guardrail_actions,
    )
