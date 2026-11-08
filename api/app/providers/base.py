"""LLM provider interface (assignment §3.5). Swapping provider = one file."""

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Pluggable LLM provider. generate() returns raw text (ideally JSON
    matching the Answer schema); embed() returns one vector per input text,
    using the pinned EMBED_MODEL — never a different model."""

    @abstractmethod
    def generate(self, prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError
