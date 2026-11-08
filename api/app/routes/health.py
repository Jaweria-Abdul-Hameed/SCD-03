"""Probes (assignment §4.3).

GET /healthz — process liveness ONLY. Returns {"status": "ok"} without
touching Chroma, Redis or the LLM — no network calls at all. If liveness
depended on a dependency, one slow dependency would become a
cluster-wide restart storm.

GET /readyz — 200 ONLY if Chroma is reachable AND the collection is
non-empty AND Redis pings OK AND the collection metadata pin matches
(model_name == EMBED_MODEL and dimension == 768). Otherwise 503
naming the failed dependency / conflict in the body.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..config import settings
from ..retrieval.cache import get_redis_client
from ..retrieval.retriever import get_chroma_collection

router = APIRouter()


@router.get("/healthz")
def healthz():
    # Liveness only: no Chroma, no Redis, no LLM, no network calls.
    return {"status": "ok"}


@router.get("/readyz")
def readyz():
    # 1. Chroma reachable + collection non-empty + embedding pin matches.
    try:
        collection = get_chroma_collection()
        count = collection.count()
        metadata = collection.metadata or {}
    except Exception as exc:  # noqa: BLE001 — Chroma unreachable
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "dependency": "chroma", "detail": str(exc)},
        )
    if count == 0:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "dependency": "chroma",
                "detail": "collection is empty",
            },
        )
    model_name = metadata.get("model_name")
    dimension = metadata.get(
        "dimension",
        metadata.get("vector_dimension", metadata.get("embedding_dimension")),
    )
    if (
        model_name != settings.EMBED_MODEL
        or int(dimension or 0) != settings.EMBED_DIMENSION
    ):
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "dependency": "embedding_pin",
                "detail": f"embedding pin mismatch: collection model_name={model_name!r} dimension={dimension!r} "
                f"!= EMBED_MODEL={settings.EMBED_MODEL!r} dim={settings.EMBED_DIMENSION}",
            },
        )
    # 2. Redis reachable.
    try:
        if not get_redis_client().ping():
            raise ConnectionError("redis ping returned False")
    except Exception as exc:  # noqa: BLE001 — Redis unreachable
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "dependency": "redis", "detail": str(exc)},
        )
    return {
        "status": "ready",
        "collection_count": count,
        "embed_model": settings.EMBED_MODEL,
    }
