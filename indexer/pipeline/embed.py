"""Embed stage — one vector per chunk from the PINNED model only.

Pin (shared with the API via the ``rahbar`` ConfigMap, assignment
sec. 3.2 / 4.4):

* ``EMBED_MODEL = "nomic-embed-text"`` (env-overridable, same default
  in the indexer and the API — the ConfigMap is the single source
  of truth in the cluster; the env default here only covers local runs)
* dimension ``768`` — verified on EVERY response.

Guardrail: if Ollama returns a vector whose dimension is not 768,
or the model name does not match the pinned model, embedding
**raises** — it never falls back to a different model silently.
Vectors from two different models are not comparable and the
failure is silent (retrieval returns nonsense, no error anywhere),
so a silent fallback would be worse than a failed Job: the Job
fails loudly, the index is not poisoned, and the API's readiness
guardrail (which compares the same pin against the Chroma
collection metadata written by ``store.py``) can then refuse traffic.

Endpoint: ``POST http://{OLLAMA_HOST}/api/embeddings`` with
``{"model": EMBED_MODEL, "prompt": chunk_text}`` (Ollama embeddings
API). ``OLLAMA_HOST`` defaults to ``host.minikube.internal:11434``
(the ollama-host mode, assignment sec. 3.5).
"""

from __future__ import annotations

import json
import os
import sys
import time

PINNED_MODEL = "nomic-embed-text"
PINNED_DIMENSION = 768


def get_model_name() -> str:
    """The pinned embedding model name (env ``EMBED_MODEL``)."""
    return os.environ.get("EMBED_MODEL", PINNED_MODEL)


def get_dimension() -> int:
    """The pinned embedding dimension.

    Reads env EMBED_DIMENSION (the ConfigMap key, k8s/base/configmap.yaml),
    falling back to the legacy EMBED_DIM alias, then the 768 default for
    nomic-embed-text. Never hardcoded silently: a ConfigMap change to the
    dimension must be visible here, and the API reads the same key.
    """
    for key in ("EMBED_DIMENSION", "EMBED_DIM"):
        raw = os.environ.get(key)
        if raw:
            try:
                return int(raw)
            except ValueError:
                _log("warning", "embed_dimension_unparsable", key=key, value=raw)
    return PINNED_DIMENSION


def _log(level: str, event: str, **fields: object) -> None:
    record = {"level": level, "stage": "embed", "event": event, **fields}
    print(
        json.dumps(record),
        file=sys.stderr if level in ("warning", "error") else sys.stdout,
    )


def _embed_one(text: str, model: str, host: str, timeout: int = 60) -> list[float]:
    """Embed one text via Ollama. Raises on dimension/model mismatch."""
    if os.environ.get("LLM_PROVIDER") == "stub":
        dim = get_dimension()
        import hashlib
        import math

        vec = [0.0] * dim
        for token in text.lower().split():
            h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
            vec[h % dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    import requests  # lazy: keeps the module importable without the dep

    url = f"http://{host}/api/embeddings"
    payload: dict = {"model": model, "prompt": text}
    # Ollama sizes its thread pool from the HOST core count, not the pod CPU
    # limit: 24 threads on a 5-CPU quota is throttled to ~1 token/s.
    # OLLAMA_NUM_THREAD (ConfigMap, ollama-incluster overlay) pins it.
    num_thread = int(os.environ.get("OLLAMA_NUM_THREAD", "0") or 0)
    if num_thread > 0:
        payload["options"] = {"num_thread": num_thread}
    resp = requests.post(url, json=payload, timeout=timeout)
    # nomic-embed-text in Ollama rejects inputs above ~2048 real tokens with
    # HTTP 500 "the input length exceeds the context length". chunk.py sizes by
    # len(text)//4, which UNDER-counts number-dense text (annual-report tables):
    # a 1024-"token" chunk can be 2100+ real tokens. Rather than fail the whole
    # Job, embed the longest prefix that fits and log it (the STORED text is
    # untouched; only that chunk's vector summarises its first part).
    while (
        getattr(resp, "status_code", 200) == 500
        and "context length" in getattr(resp, "text", "")
        and len(text) > 400
    ):
        text = text[: int(len(text) * 0.8)]
        payload["prompt"] = text
        _log("warning", "embed_input_truncated", chars=len(text), host=host)
        resp = requests.post(url, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    # PIN GUARDRAIL — model field: Ollama echoes the model it actually
    # used. If it names a different model, RAISE (never just warn):
    # vectors from two models are not comparable and a silent mismatch
    # would poison the index. (Absent "model" in the response — e.g. a
    # minimal mock — is not treated as a mismatch.)
    returned_model = data.get("model")
    if returned_model is not None and returned_model != model:
        raise ValueError(
            f"Embedding model mismatch: requested model={model!r} but Ollama "
            f"returned model={returned_model!r}. Refusing to index "
            "(no silent fallback)."
        )
    embedding = data.get("embedding")
    if not isinstance(embedding, list) or not embedding:
        raise ValueError(
            f"Ollama returned no embedding for model={model!r} (host={host})"
        )
    expected_dim = get_dimension()
    if len(embedding) != expected_dim:
        # PIN GUARDRAIL — never silently accept a wrong-dimension vector.
        raise ValueError(
            f"Embedding dimension mismatch: model={model!r} returned "
            f"dimension={len(embedding)}, expected pinned dimension="
            f"{expected_dim}. Refusing to index (no silent fallback)."
        )
    return [float(v) for v in embedding]


_TITLE_WORDS = {
    "EE": "Electrical Engineering (EE)",
    "PLOs": "Program Learning Outcomes (PLOs)",
}


def doc_title(source: str) -> str:
    """Human-readable title from the file name (``EE_PLOs_2024_onwards_11.pdf``)."""
    stem = source.rsplit(".", 1)[0].replace("_", " ")
    return " ".join(_TITLE_WORDS.get(w, w) for w in stem.split())


def document_text(source: str, section: str, text: str) -> str:
    """Text that is EMBEDDED (the stored chunk text is unchanged).

    nomic-embed-text is trained with task prefixes (``search_document: `` for
    indexed text, ``search_query: `` for questions); without them retrieval
    quality drops. A one-line contextual header (document title + section)
    lets a chunk such as the bare PLO list ("PLO-1 Engineering Knowledge...")
    be found by a question that says "Electrical Engineering".
    """
    if os.environ.get("LLM_PROVIDER") == "stub":
        return text  # stub hash embeddings have no task prefixes / headers
    prefix = "search_document: " if get_model_name().startswith("nomic") else ""
    header = f"{prefix}Document: {doc_title(source)}. Section: {section}."
    return header + chr(10) + text


def embed_texts(
    texts: list[str],
    model: str | None = None,
    host: str | None = None,
    batch_size: int = 16,
    max_retries: int = 3,
) -> list[list[float]]:
    """Embed ``texts`` in batches, with retries on transient failures.

    Retries cover network/5xx errors only. A dimension mismatch or a
    model mismatch is NOT retried — it is a configuration error and
    retrying it would only re-poison the index. No fallback model is
    ever substituted.
    """
    model = model or get_model_name()
    if model != PINNED_MODEL and os.environ.get("EMBED_MODEL"):
        # The env var is the operator's explicit choice (ConfigMap in
        # the cluster); the pin is that the indexer and API agree, and
        # store.py records whatever model actually ran in the
        # collection metadata so the API can refuse on mismatch.
        _log(
            "warning",
            "embed_model_differs_from_default_pin",
            model=model,
            pinned_default=PINNED_MODEL,
            note="Model recorded in Chroma collection metadata; API readiness will refuse on mismatch",
        )
    host = host or os.environ.get("OLLAMA_HOST", "host.minikube.internal:11434")
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        for text in batch:
            last_exc: Exception | None = None
            for attempt in range(1, max_retries + 1):
                try:
                    vectors.append(_embed_one(text, model, host))
                    last_exc = None
                    break
                except ValueError:
                    raise  # dimension/model error: fail loudly, do not retry
                except Exception as exc:  # noqa: BLE001 — transient error: retry with backoff
                    last_exc = exc
                    _log(
                        "warning",
                        "embed_retry",
                        attempt=attempt,
                        max_retries=max_retries,
                        error=str(exc),
                    )
                    time.sleep(2**attempt)
            if last_exc is not None:
                raise RuntimeError(
                    f"Embedding failed after {max_retries} attempts "
                    f"(model={model!r}, host={host}): {last_exc}"
                ) from last_exc
    _log(
        "info",
        "embed_done",
        model=model,
        dimension=get_dimension(),
        texts=len(texts),
        vectors=len(vectors),
    )
    return vectors


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Embed text(s) with the pinned model.")
    parser.add_argument("texts", nargs="+", help="Text(s) to embed")
    args = parser.parse_args()
    vectors = embed_texts(args.texts)
    print(
        json.dumps(
            {
                "model": get_model_name(),
                "dimension": get_dimension(),
                "count": len(vectors),
                "dimensions": [len(v) for v in vectors],
            }
        )
    )
