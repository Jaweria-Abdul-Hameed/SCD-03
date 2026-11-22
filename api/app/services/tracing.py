"""Structured JSONL trace emitter (Part D1 & Paper Table 2 Traceability / §6.1 Black-box recorder).

Every query emits one JSON line containing all 16 mandatory fields to:
1. stdout (structured log line readable via ``kubectl logs``)
2. TRACE_FILE (when configured, e.g. ``/traces/traces.jsonl`` on a PVC)
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import settings


def compute_prompt_hash(prompt: str) -> str:
    return hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()


def build_trace_record(
    *,
    trace_id: str,
    user_query: str,
    rewritten_query: str | None,
    retrieved_chunks: list[dict],
    filters_applied: dict[str, Any],
    reranked_order: list[dict[str, Any]],
    full_prompt: str,
    response_dict: dict[str, Any],
    citations: list[dict[str, Any]],
    guardrail_actions: list[dict[str, Any]],
    latency_per_stage: dict[str, float],
    cache_hit: bool,
) -> dict[str, Any]:
    """Build one complete 16-field RAGOps JSONL trace record."""
    compact_chunks = []
    for ch in retrieved_chunks:
        meta = ch.get("metadata") or {}
        compact_chunks.append(
            {
                "chunk_id": ch.get("id", ""),
                "document_id": meta.get("source", ""),
                "document_version": meta.get("doc_version", ""),
                "section": meta.get("section", ""),
                "page": meta.get("page", 1),
                "superseded": meta.get("superseded", False),
                "score": round(float(ch.get("similarity", 0.0)), 6),
                "text": ch.get("text", ""),
            }
        )

    return {
        "record_type": "ragops_trace",
        "trace_id": trace_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "user_query": user_query,
        "rewritten_query": rewritten_query,
        "embedding_model": settings.EMBED_MODEL,
        "embedding_version": settings.EMBED_VERSION,
        "collection_name": settings.CHROMA_COLLECTION,
        "collection_version": settings.COLLECTION_VERSION,
        "retrieved_chunks": compact_chunks,
        "filters_applied": filters_applied,
        "reranked_order": reranked_order,
        "prompt_hash": compute_prompt_hash(full_prompt) if full_prompt else None,
        "full_prompt": full_prompt,
        "model": settings.LLM_MODEL,
        "parameters": {
            "provider": settings.LLM_PROVIDER,
            "temperature": settings.TEMPERATURE,
            "seed": settings.LLM_SEED,
            "num_ctx": settings.LLM_NUM_CTX,
            "top_k": settings.TOP_K,
            "relevance_floor": settings.RELEVANCE_FLOOR,
            "cache_threshold": settings.CACHE_THRESHOLD,
            "prompt_template": settings.PROMPT_TEMPLATE,
        },
        "response": response_dict,
        "citations": citations,
        "guardrail_actions": guardrail_actions,
        "latency_per_stage": {k: round(float(v), 3) for k, v in latency_per_stage.items()},
        "cache_hit": bool(cache_hit),
    }


def emit_trace(record: dict[str, Any]) -> None:
    """Emit JSONL trace to stdout and optionally append to TRACE_FILE on PVC."""
    line = json.dumps(record, ensure_ascii=False)
    print(line, file=sys.stdout, flush=True)
    trace_file = (settings.TRACE_FILE or "").strip()
    if trace_file:
        try:
            path = Path(trace_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except Exception as exc:  # noqa: BLE001 — disk issue must not fail live query
            print(
                json.dumps(
                    {
                        "event": "trace_file_write_failed",
                        "trace_file": trace_file,
                        "error": str(exc),
                    }
                ),
                file=sys.stderr,
                flush=True,
            )
