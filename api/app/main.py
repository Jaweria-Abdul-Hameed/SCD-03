"""FastAPI app wiring.

- Middleware adds X-Request-ID (from header or uuid4) to every response.
- JSON stdout structured logging (one line per request; the detailed
  per-request line with top_k / chunk ids / scores / abstention is
  emitted by services/chat.py).
- Startup check (§4.4): compares Chroma collection metadata vs
  EMBED_MODEL and LOGS the conflict. Readiness will refuse (0/1 READY);
  the process does NOT crash and does NOT index anything at startup —
  this module never imports indexer code.
- CORS for the UI origin only.
"""

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response

from .config import settings
from .metrics import http_requests_total, request_latency_seconds
from .routes import chat as chat_routes
from .routes import health as health_routes
from .routes import metrics as metrics_routes

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("rahbar.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Embedding-pin startup check: log the conflict, do NOT crash,
    # do NOT index. /readyz enforces readiness (503) on mismatch.
    try:
        from .retrieval.retriever import get_chroma_collection

        collection = get_chroma_collection()
        metadata = collection.metadata or {}
        model_name = metadata.get("model_name")
        # Same metadata-key fallback chain as api/app/routes/health.py
        # (/readyz): store.py writes "embedding_dimension", so it must be
        # in the chain or a correctly-pinned collection looks mismatched.
        dimension = metadata.get(
            "dimension",
            metadata.get("vector_dimension", metadata.get("embedding_dimension")),
        )
        if (
            model_name != settings.EMBED_MODEL
            or int(dimension or 0) != settings.EMBED_DIMENSION
        ):
            logger.error(
                json.dumps(
                    {
                        "event": "embedding_pin_mismatch",
                        "collection_model": model_name,
                        "collection_dimension": dimension,
                        "expected_model": settings.EMBED_MODEL,
                        "expected_dimension": settings.EMBED_DIMENSION,
                        "detail": "API will report not-ready until the index is rebuilt with the pinned model",
                    }
                )
            )
        else:
            logger.info(json.dumps({"event": "embedding_pin_ok", "model": model_name}))
    except Exception as exc:  # noqa: BLE001 — Chroma not up yet at boot: readiness will report it
        logger.warning(
            json.dumps({"event": "startup_pin_check_unavailable", "detail": str(exc)})
        )
    yield


app = FastAPI(title="RAHBAR — Grounded RAG", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.UI_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.monotonic()
    response: Response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    latency = time.monotonic() - started
    http_requests_total.labels(
        method=request.method, path=request.url.path, status=str(response.status_code)
    ).inc()
    request_latency_seconds.labels(path=request.url.path).observe(latency)
    logger.info(
        json.dumps(
            {
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "latency_ms": round(latency * 1000, 2),
            }
        )
    )
    return response


app.include_router(chat_routes.router)
app.include_router(health_routes.router)
app.include_router(metrics_routes.router)
