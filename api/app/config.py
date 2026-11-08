"""Central configuration for the RAHBAR API.

Every value comes from the environment (populated in Kubernetes from the
shared ConfigMap / Secret) with the assignment defaults below, so the API
and the indexer can never silently disagree about the pinned model.
No secrets are hard-coded here; LLM_API_KEY is read only from the env.
"""

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Embedding pin — MUST match the indexer / Chroma collection metadata.
    EMBED_MODEL: str = "nomic-embed-text"
    # Reads EMBED_DIMENSION (the ConfigMap key, k8s/base/configmap.yaml)
    # with EMBED_DIM as a fallback alias for older env/configs.
    EMBED_DIMENSION: int = Field(
        default=768, validation_alias=AliasChoices("EMBED_DIMENSION", "EMBED_DIM")
    )
    CHROMA_COLLECTION: str = "rahbar_corpus"
    CHROMA_HOST: str = "chroma"
    CHROMA_PORT: int = 8000

    # Semantic cache (Redis).
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    CACHE_THRESHOLD: float = 0.96

    # Retrieval / generation (ConfigMap values).
    TOP_K: int = 5
    RELEVANCE_FLOOR: float = 0.35
    TEMPERATURE: float = 0.2  # ConfigMap; valid range 0.0-0.3 (facts + JSON)

    # LLM provider selection.
    LLM_PROVIDER: str = "ollama-host"  # ollama-host | ollama-incluster | hosted | stub
    LLM_MODEL: str = "llama3.2:3b"
    OLLAMA_HOST: str = "host.minikube.internal:11434"
    # Seconds to wait for one generation. CPU-only Ollama needs ~60-200 s for a
    # ~2000-token prompt (measured, docs/PIPELINE.md); the in-cluster overlay raises it.
    LLM_TIMEOUT_S: int = 120
    # >0 pins Ollama num_thread (needed in-cluster: Ollama sees the host core
    # count, not the pod CPU quota, and over-subscribed threads run ~13x slower).
    OLLAMA_NUM_THREAD: int = 0
    # Context window sent to Ollama. Five ~2000-char chunks + instructions exceed the 4096
    # default and the evidence would be cut off silently; 8192 fits with room for the answer.
    LLM_NUM_CTX: int = 8192
    # Hosted provider: base URL + key from env/Secret only, never logged.
    LLM_HOSTED_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""

    API_PORT: int = 8000
    UI_ORIGIN: str = "http://localhost:3000"

    @property
    def EMBED_DIM(self) -> int:
        """Backwards-compatible alias for EMBED_DIMENSION."""
        return self.EMBED_DIMENSION

    @field_validator("TEMPERATURE")
    @classmethod
    def _temperature_in_range(cls, v: float) -> float:
        # Assignment sec. 3.4: generation temperature must be 0.0-0.3.
        # Anything else is a configuration error — fail loudly at startup
        # instead of serving ungrounded, high-temperature answers.
        if not 0.0 <= v <= 0.3:
            raise ValueError(f"TEMPERATURE must be 0.0-0.3, got {v!r}")
        return v


settings = Settings()
