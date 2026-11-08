"""Ollama provider (ollama-host default, also ollama-incluster).

Chat via /api/chat with ``format=`` set to the Answer JSON schema and
temperature from env (default 0.2, range 0.0-0.3). Embeddings via
/api/embeddings with the pinned EMBED_MODEL (nomic-embed-text, dim 768).
"""

import requests

from ..config import settings
from ..schemas import Answer
from .base import LLMProvider


def _base_url(host: str) -> str:
    host = host.strip()
    return host if host.startswith(("http://", "https://")) else f"http://{host}"


def _strict_schema() -> dict:
    """Answer JSON schema with EVERY field required.

    Pydantic marks fields that have defaults (citations) as optional; a 3B model
    then happily omits ``citations`` and the answer is downgraded to an
    abstention (measured: the tuition-fee question). Requiring the key in the
    schema sent as ``format`` makes the constrained decoder emit it.
    """
    schema = Answer.model_json_schema()
    schema["required"] = list(schema.get("properties", {}))
    return schema


class OllamaProvider(LLMProvider):
    def __init__(self, host: str | None = None, model: str | None = None):
        self.base_url = _base_url(host or settings.OLLAMA_HOST)
        self.model = model or settings.LLM_MODEL
        self.temperature = settings.TEMPERATURE

    def _options(self) -> dict:
        opts: dict = {"temperature": self.temperature}
        if settings.OLLAMA_NUM_THREAD > 0:
            opts["num_thread"] = settings.OLLAMA_NUM_THREAD
        return opts

    def generate(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                # Strongest enforcement Ollama supports: JSON schema format.
                "format": _strict_schema(),
                "stream": False,
                "options": self._options(),
            },
            timeout=settings.LLM_TIMEOUT_S,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"]

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            resp = requests.post(
                f"{self.base_url}/api/embeddings",
                json={
                    "model": settings.EMBED_MODEL,
                    "prompt": text,
                    **(
                        {"options": {"num_thread": settings.OLLAMA_NUM_THREAD}}
                        if settings.OLLAMA_NUM_THREAD > 0
                        else {}
                    ),
                },
                timeout=60,
            )
            resp.raise_for_status()
            embedding = resp.json()["embedding"]
            # Pin guardrail (matching indexer/pipeline/embed.py): a vector
            # of the wrong dimension must raise, never be stored/used.
            if (
                not isinstance(embedding, list)
                or len(embedding) != settings.EMBED_DIMENSION
            ):
                raise ValueError(
                    f"Embedding dimension mismatch: Ollama returned "
                    f"dimension={len(embedding) if isinstance(embedding, list) else 'non-list'}, "
                    f"expected pinned dimension={settings.EMBED_DIMENSION}."
                )
            out.append(embedding)
        return out
