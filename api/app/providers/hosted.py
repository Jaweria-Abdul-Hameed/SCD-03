"""Hosted provider (Groq / Google AI Studio / OpenRouter free tier).

API key comes ONLY from the LLM_API_KEY env var (Kubernetes Secret in
prod) and is never logged. Raises at construction if the key is missing,
so a misconfigured deploy fails loudly instead of serving unauthenticated.
"""

import requests

from ..config import settings
from ..schemas import Answer
from .base import LLMProvider


class HostedProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        key = api_key if api_key is not None else settings.LLM_API_KEY
        if not key:
            raise ValueError(
                "LLM_API_KEY is not set; hosted provider cannot start without it"
            )
        self._api_key = key  # never logged
        self.base_url = (base_url or settings.LLM_HOSTED_BASE_URL).rstrip("/")
        self.model = settings.LLM_MODEL

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def generate(self, prompt: str) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json={
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": settings.TEMPERATURE,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "Answer",
                        "schema": Answer.model_json_schema(),
                    },
                },
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Hosted embedding must still use the pinned model name; providers
        # that cannot serve it must not be used for embedding (use Ollama).
        resp = requests.post(
            f"{self.base_url}/embeddings",
            headers=self._headers(),
            json={"model": settings.EMBED_MODEL, "input": texts},
            timeout=60,
        )
        resp.raise_for_status()
        embeddings = [item["embedding"] for item in resp.json()["data"]]
        # Pin guardrail (matching indexer/pipeline/embed.py): wrong
        # dimension must raise, never be used for retrieval.
        for embedding in embeddings:
            if (
                not isinstance(embedding, list)
                or len(embedding) != settings.EMBED_DIMENSION
            ):
                raise ValueError(
                    f"Embedding dimension mismatch: hosted provider returned "
                    f"dimension={len(embedding) if isinstance(embedding, list) else 'non-list'}, "
                    f"expected pinned dimension={settings.EMBED_DIMENSION}."
                )
        return embeddings
