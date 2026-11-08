"""POST /chat — validated question in, validated grounded Answer out."""

import time

from fastapi import APIRouter, Request

from ..schemas import ChatRequest, ChatResponse
from ..services.chat import handle_chat

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, http_request: Request):
    request_id = getattr(http_request.state, "request_id", "unknown")
    started = time.monotonic()
    response = handle_chat(request, request_id)
    response.latency_ms = (time.monotonic() - started) * 1000
    return response
