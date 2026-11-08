# ARCHITECTURE — RAHBAR

One page: the system, the data flow, and why Chroma is a StatefulSet.

## System diagram (text)

```
                          ┌─────────────────────────────────────────────┐
                          │  minikube cluster  (namespace: rahbar)     │
                          │                                             │
  User ──► Ingress ──► ┌──┴───┐      ┌──────────┐      ┌────────────┐  │
                       │  UI  │─────►│   API    │─────►│   Chroma   │  │
                       │ nginx│      │ FastAPI  │ read │ StatefulSet│  │
                       │ 1+   │      │ 3 repl.  │ only │ 1 replica  │  │
                       └──┬───┘      └──┬───┬───┘      │ + PVC      │  │
                          │             │   │          └────────────┘  │
                          │             │   │          ┌────────────┐  │
                          │             │   └─────────►│   Redis    │  │
                          │             │   cache      │ Deployment │  │
                          │             │              │ + PVC      │  │
                          │             │              └────────────┘  │
                          │             │          ┌────────────┐      │
                          │             └─────────►│ LLM provider│     │
                          │              generate  │ ollama-host │     │
                          │              (host)    │ (default)   │     │
                          │                        └────────────┘      │
                          │                                             │
                          │  ┌──────────┐   writes   ┌────────────┐  │
                          │  │ Indexer  │───────────►│   Chroma   │  │
                          │  │ Job /    │  (only     │  (same     │  │
                          │  │ CronJob  │   writer)  │   store)   │  │
                          │  │ weekly   │            └────────────┘  │
                          │  └──────────┘   also invalidates Redis    │
                          │       ▲           cache on completion      │
                          │       │                                    │
                          └───────┴────────────────────────────────────┘
                         ConfigMap (one shared pin — see below)
                      EMBED_MODEL=nomic-embed-text (768 dims) · top_k
                      relevance_floor · cache_threshold · temperature
                      LLM_PROVIDER · CHROMA_HOST
```

## The rule in one line

**One writer, one reader, one shared pin** (assignment sec. 3): only the
indexer Job writes to Chroma, the API only reads it, and both read
`EMBED_MODEL` from the same ConfigMap — with the pin also written into
the Chroma collection metadata by the indexer and checked by the API at
readiness (ADR 0004).

## Request flow (every question)

1. UI → API `POST /chat` (question, 3–500 chars, validated).
2. Semantic-cache check in Redis (cosine ≥ `cache_threshold`); skipped
   for follow-ups, abstentions, and validation failures.
3. Embed the question with the pinned model; retrieve top-k from Chroma,
   filtering out `superseded: true` chunks by default.
4. Augment (instructions, numbered evidence, question) → generate at
   temperature 0.0–0.3 with the schema-constrained `Answer` model.
5. Validate with Pydantic, retry once, then a safe canned response.
   Abstain honestly (`answered_from_context: false`) when nothing clears
   the relevance floor; every citation must match a retrieved chunk.
6. Store the turn; cache the answer only if it is safe to cache.

Indexing flow (on demand, never on query): the Job extracts (with OCR
fallback for the scanned PDF), cleans, structure-aware chunks, embeds
with the pinned model, stores vectors + metadata
(`source, section, page, doc_version, superseded`) in Chroma, and
invalidates the Redis cache. Re-index without a redeploy:
`kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar`.

## Why Chroma is a StatefulSet, not a Deployment

Chroma is `k8s/base/chroma-statefulset.yaml` — a `StatefulSet` with
`volumeClaimTemplates` — and this is a deliberate, graded choice
(sec. 4.1, −8 if done as a Deployment with no PVC):

- **Stable identity and stable storage.** A StatefulSet gives the pod a
  stable name (`chroma-0`) and a stable PVC that survives pod deletion
  and rescheduling: delete the pod and the *same* volume, with the
  *same* index, is re-attached to its replacement. A Deployment with an
  ad-hoc PVC can lose that binding — a new pod can start against an
  empty volume, and the API's `/readyz` would (correctly) report an
  empty collection while the "real" index sits orphaned on a detached
  volume. For a vector store, losing the volume *is* losing the system.
- **One writer, one replica, ordered startup.** The StatefulSet runs
  exactly 1 replica (`replicas: 1`), which is the physical expression
  of "one writer": there is no second Chroma pod that could race the
  indexer. A Deployment invites scaling the store by changing a number;
  scaling Chroma that way does not scale retrieval, it duplicates the
  index.
- **Volume lifecycle owned by the workload.** `volumeClaimTemplates`
  creates the PVC as part of the StatefulSet, so the claim's lifecycle
  follows the StatefulSet instead of being a separate, forgettable
  object. The volume is the state; the manifest that owns the state
  should own the claim.
- **The same logic applies to Redis** (Deployment + PVC): the cache is
  persistent across restarts, but losing it is always safe — it is
  rebuilt from live questions, never from a backup. That asymmetry
  (index = must survive; cache = may be rebuilt) is why Chroma gets the
  stronger StatefulSet guarantee and Redis gets a Deployment + PVC.

## The LLM runtime: host Ollama (default) or Ollama in the cluster (overlay)

`LLM_PROVIDER` selects the mode (ADR 0003). The base manifests default to `ollama-host`
(Ollama on the laptop, reached at `host.minikube.internal:11434`, no weights in the cluster).
`k8s/overlays/incluster-ollama` adds Ollama as a `Deployment` + PVC (`ollama-models`) +
`ClusterIP` Service with its own NetworkPolicies (api and indexer in; ui blocked): the whole
system - writer, reader, vector store, cache and model - then runs inside one minikube, which is
the mode used for the measurements in this repository. It is a Deployment (not a StatefulSet)
on purpose: the weights are re-downloadable and the pod is stateless apart from a model cache,
`strategy: Recreate` guards the single RWO volume, and unlike Chroma nothing is lost if the
claim is recreated (`ollama pull` restores it).

## Security posture (summary)

Namespace `rahbar` everywhere, never `default`. All Services are
ClusterIP — Chroma and Redis are never NodePort/LoadBalancer. Default-deny
NetworkPolicy, then allow only: Ingress → UI; UI/Ingress → API;
API/Indexer → Chroma; API/Indexer → Redis (cache reads & Job invalidation);
API/Indexer → LLM provider (Ollama on host for generation & embedding); DNS (UDP/TCP 53)
to kube-system. UI → Chroma is explicitly blocked. Every container runs
as non-root, read-only root filesystem, all capabilities dropped, and
pods that never call the API server set `automountServiceAccountToken: false`.
Zero-downtime rolling updates are enforced by `maxSurge: 1`, `maxUnavailable: 0`,
and a `preStop` hook (`sleep 5`) ensuring in-flight requests drain before termination.
Secrets are created from the command line, never committed; committed
manifests hold placeholders only (`*-secret.yaml` is gitignored). The
placeholder file `k8s/base/rahbar-secret.yaml` is kept in the repo as a
documented reference ONLY — it is deliberately NOT listed in
`k8s/base/kustomization.yaml` resources (a clean clone lacks it, so
listing it would make `kustomize build` fail). Apply the overlay first,
then create the real Secret with
`kubectl create secret generic rahbar-secret -n rahbar
--from-literal=LLM_API_KEY=...` (see README apply order) — and never
apply the placeholder afterwards, or it would overwrite the real Secret.
Full detail: `docs/adr/0001–0004`, `docs/ENGINEERING-NOTES.md`.
