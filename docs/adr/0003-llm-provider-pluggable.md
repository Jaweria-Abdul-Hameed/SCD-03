# ADR 0003 — LLM provider is pluggable behind one interface

- **Status:** Accepted
- **Date:** 2026-11-05
- **Context:** Assignment sec. 3.5: the provider sits behind an interface
  selected by `LLM_PROVIDER` in the ConfigMap. At least one mode must be
  fully supported; a swap must be one file. The default must be the
  lowest-memory option on minikube.

## Decision

Define a single provider interface in `api/app/providers/base.py`
(one abstract class: `generate(prompt, schema, temperature) -> Answer`-shaped
JSON, plus a `health()` check). Every provider is one file implementing it:

- `api/app/providers/ollama.py` — **ollama-host (default)**. Ollama
  runs on the operator's laptop; the cluster reaches it at
  `host.minikube.internal:11434`. Lowest memory use on minikube, because
  no model weights live inside the cluster. Requires Ollama to listen on
  all interfaces (`OLLAMA_HOST=0.0.0.0 ollama serve`) and the models pulled
  (`ollama pull llama3.2:3b`, `ollama pull nomic-embed-text`).
- `api/app/providers/hosted.py` — hosted endpoint (Groq / Google AI
  Studio / OpenRouter free tier). The key lives in a Kubernetes Secret (`rahbar-secret`),
  injected via `envFrom: - secretRef: name: rahbar-secret, optional: true` in
  `k8s/base/api-deployment.yaml`. The `optional: true` flag is vital: it allows the
  API pod to boot without error in the default `ollama-host` mode where no secret exists.
  When hosted mode is enabled, the secret is created imperatively via:
  `kubectl create secret generic rahbar-secret -n rahbar --from-literal=LLM_API_KEY="$KEY"`.
  The placeholder file `k8s/base/rahbar-secret.yaml` is excluded from `kustomization.yaml`
  and protected by `.gitignore` (`*-secret.yaml`).
- `api/app/providers/stub.py` — deterministic stub provider used by
  `pytest` and CI: no network, no model download, no key. This is what
  makes the 60% coverage gate and the CI test job hermetic.
- **`ollama-incluster` (bonus, implemented and used for the reference run)** -
  `k8s/overlays/incluster-ollama/{kustomization,ollama}.yaml` on top of the prod overlay.
  `LLM_PROVIDER=ollama-incluster` selects the same `ollama.py` provider (it only differs in
  `OLLAMA_HOST=ollama:11434`), so a swap is still one ConfigMap key. What the overlay adds:
  - a `Deployment` (replicas 1, strategy `Recreate`: one RWO volume) + `PersistentVolumeClaim`
    `ollama-models` (10 Gi) + `ClusterIP` Service, image **pinned** `ollama/ollama:0.32.1`
    (never the floating latest), non-root `10001`, `readOnlyRootFilesystem`, all capabilities
    dropped, its own ServiceAccount without a token;
  - `startupProbe` with `failureThreshold: 30` (weights load for minutes; a liveness probe
    would kill the pod halfway) and separate liveness/readiness;
  - NetworkPolicies: `api` and `indexer` may reach `ollama:11434` (api egress, indexer
    egress) and only they may enter it; the `ui` cannot (live test:
    `docs/evidence/live/networkpolicy-live-test.txt`);
  - **memory:** request 3 Gi, limit 5 Gi. Measured: the two models are about 3 Gi
    (llama3.2:3b 2.6 GB + nomic-embed-text 0.4 GB), the working set 4.7 Gi including
    reclaimable page cache. It needs the 8 GB / 6 CPU minikube. Two settings were found
    necessary by measurement, not by documentation: `OLLAMA_NUM_THREAD=4` (Ollama starts one
    thread per HOST core - 24 here - and is throttled to 1.2 tokens/s; 4 threads give 15.6) and
    `LLAMA_ARG_CACHE_RAM=0` (the llama.cpp prompt cache grew the pod to 5.7 Gi and got it
    OOMKilled);
  - `LLM_TIMEOUT_S=400`: a 3 000-token prompt takes 30-60 s of prompt evaluation plus
    generation on CPU.
  Models are pulled once into the PVC: `kubectl exec deploy/ollama -n rahbar -- ollama pull
  nomic-embed-text` and `... pull llama3.2:3b`. The host-Ollama mode stays the default of the
  base manifests.

Selection is exactly one ConfigMap key: `LLM_PROVIDER`. The chat route
(`api/app/routes/chat.py`) never imports a concrete provider; it asks the
factory in `api/app/providers/__init__.py` for the configured one.

## Why this shape

- **A swap is one file.** Adding a provider means writing one new file
  that implements `base.py` and adding its name to the factory. No route,
  schema, retrieval, or caching code changes — the `Answer` schema is the
  contract on both sides, and every provider is validated by the same
  Pydantic model after generation, with one retry and then a safe canned
  response (sec. 3.4).
- **The default is the cheapest correct one.** ollama-host keeps the
  6 GB minikube profile working. In-cluster Ollama is an overlay for
  operators with 8 GB to spare, not the default that breaks a laptop.
- **Tests stay hermetic.** The stub provider is what lets `pytest` run in
  CI with no network and no model — if generation code imported Ollama
  directly, every test would need a live model.

## Consequences

- **Multi-Tier Validation & Fallback Strategy (Assignment §3.4):**
  Providers are constrained at multiple layers to guarantee that ungrounded prose or malformed
  JSON never escapes as an HTTP 500:
  1. *Provider Enforcement:* `response_format` JSON schema on hosted; `format="json"` on Ollama.
  2. *Pydantic Schema Validation:* Raw output is parsed and validated against `Answer` (`parse_answer()`: `reasoning`, `answer`, `citations`, `answered_from_context`, `confidence`).
  3. *Citation Grounding Verification:* `validate_answer()` verifies that every citation in `citations` exists in the retrieved `chunks`. Unretrieved citations are dropped or downgraded to abstention.
  4. *Retry Loop:* On any parsing or validation failure, generation is retried once with the augmented prompt.
  5. *Safe Canned Refusal Fallback:* If the second attempt fails, or if an unhandled network error occurs, the API returns a safe canned fallback (`abstain_answer()`, `answered_from_context: false`, `confidence: "low"`). The user never sees an unhandled 500 error.
- Every provider must support the strongest structured-output enforcement
  it offers (`format=` on Ollama, JSON mode / response schema on hosted)
  **and** still be validated by Pydantic afterwards: structure can be
  guaranteed, truth cannot.
- Temperature is a ConfigMap value (`temperature`, 0.0–0.3), not a
  per-provider default, so a provider swap cannot silently change the
  grounding behaviour.
- The embedding model is pinned **separately** from the generation
  provider (see ADR 0004): changing `LLM_PROVIDER` never changes
  `EMBED_MODEL`, and vice versa.
