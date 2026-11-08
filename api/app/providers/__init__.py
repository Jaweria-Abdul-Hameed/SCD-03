"""Provider factory — selection by LLM_PROVIDER env (assignment §3.5)."""

from ..config import settings
from .base import LLMProvider
from .hosted import HostedProvider
from .ollama import OllamaProvider
from .stub import StubProvider

__all__ = [
    "HostedProvider",
    "LLMProvider",
    "OllamaProvider",
    "StubProvider",
    "get_provider",
]


def get_provider() -> LLMProvider:
    provider = settings.LLM_PROVIDER.strip().lower()
    if provider in ("ollama-host", "ollama-incluster", "ollama"):
        return OllamaProvider()
    if provider == "hosted":
        return HostedProvider()
    if provider == "stub":
        return StubProvider()
    raise ValueError(f"Unknown LLM_PROVIDER: {settings.LLM_PROVIDER!r}")
