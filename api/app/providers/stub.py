"""Deterministic stub provider for tests / CI — no network, no model.

generate(): parses the delimited <context ...> blocks in the prompt and
returns a canned grounded Answer citing the FIRST retrieved chunk
(source/section/page taken from the block attributes). With no context
blocks it returns the abstention JSON. embed(): deterministic
hash-based 768-dim unit vectors (same text -> same vector).
"""

import hashlib
import json
import math
import re

from ..config import settings
from .base import LLMProvider

_CONTEXT_RE = re.compile(
    r'<context id="\d+" source="([^"]*)" section="([^"]*)" page="(\d+)">', re.DOTALL
)


class StubProvider(LLMProvider):
    def generate(self, prompt: str) -> str:
        match = _CONTEXT_RE.search(prompt)
        if not match:
            return json.dumps(
                {
                    "reasoning": "No retrieved context was supplied.",
                    "answer": "The corpus does not cover this question.",
                    "citations": [],
                    "answered_from_context": False,
                    "confidence": "low",
                }
            )
        source, section, page = match.group(1), match.group(2), int(match.group(3))
        return json.dumps(
            {
                "reasoning": "The first retrieved passage directly covers the question.",
                "answer": f"According to the retrieved passage, see {source} section {section}.",
                "citations": [{"source": source, "section": section, "page": page}],
                "answered_from_context": True,
                "confidence": "high",
            }
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vec = [0.0] * settings.EMBED_DIM
            for token in text.lower().split():
                h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
                vec[h % settings.EMBED_DIM] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            vectors.append([v / norm for v in vec])
        return vectors
