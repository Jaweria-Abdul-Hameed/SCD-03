# ADR 0004 — Embedding pin: indexer and API cannot silently disagree

- **Status:** Accepted
- **Date:** 2026-11-05
- **Context:** Assignment sec. 3.2 and 4.4. Indexing and querying must use
  the same embedding model. Vectors from two different models are mathematically
  non-comparable: dense embeddings reside in continuous latent vector spaces whose
  geometric coordinates, angles, and manifold structures are learned independently.
  Computing cosine similarity between vectors from different models (or even mismatched
  dimensions) yields meaningless, pseudo-random dot products in $[-1, 1]$ without triggering
  any mathematical or system exceptions. Retrieval silently returns irrelevant chunks,
  causing the LLM to hallucinate with confidence. A rule in a README is a sentence someone breaks
  in week nine; a guardrail makes the broken state unreachable.

## Decision

Pin the embedding model in **one** place and enforce it in **code** at two
points:

1. **Single source of truth — the ConfigMap.** `EMBED_MODEL=nomic-embed-text`
   lives in `k8s/base/configmap.yaml:15` and is read by both the indexer and
   the API from the same object. There is no second copy of the model name
   in code, in a Dockerfile, or in a workflow. The pinned model is
   `nomic-embed-text`, vector dimension **768** (`k8s/base/configmap.yaml:16`).
2. **Indexer writes the pin into the index.** When the indexer Job builds
   the collection, `indexer/pipeline/store.py:136` (`collection_metadata()`,
   applied in `get_or_create_collection()` at
   `indexer/pipeline/store.py:146`) writes `model_name` and
   the vector dimension into the Chroma **collection metadata**. The pin
   travels with the data, not just with the config.
3. **API checks the pin at readiness and refuses to serve on mismatch.**
   At startup (`api/app/main.py:35`, lifespan pin check) and on every
   `/readyz` probe, `api/app/routes/health.py:51–68`
   compares the collection metadata against its own `EMBED_MODEL` and `EMBED_DIMENSION`. On a
   mismatch it returns 503, the pod stays **0/1 READY**, and it logs
   exactly what conflicts (expected model/dimension vs. the metadata
   found). The pod is withheld from the Service — it is never allowed to
   serve garbage retrieval.

## Demonstration (sec. 4.4)

Change `EMBED_MODEL` in the ConfigMap, restart the API only, and show:

```bash
kubectl get pods -n rahbar        # api pod: 0/1 READY
kubectl logs deployment/api -n rahbar
# {"event": "embedding_pin_mismatch", "collection_model": "nomic-embed-text",
#  "collection_dimension": 768, "expected_model": "<new-model>", ...}
# and /readyz returns 503 with:
# "embedding pin mismatch: collection model_name='nomic-embed-text' dimension=768
#  != EMBED_MODEL='<new-model>' dim=768"
```

Without this guardrail, the same change would silently serve garbage:
the API would embed questions with the new model, retrieve against
vectors written by the old model, and return confident, well-written,
wrong answers with citations to chunks that are not actually relevant —
and nothing in the logs, metrics, or probes would say anything was wrong.

## Consequences

- **Positive:** the broken state is unreachable in production: a model
  change requires re-indexing with the new model (run the indexer Job),
  which rewrites the collection metadata, and only then does `/readyz`
  go green.
- **Positive:** the check is cheap and local — a metadata read on the
  readiness path, not a probe of the embedding provider on every request.
- **Accepted cost:** changing the embedding model is a two-step operation
  (edit ConfigMap **and** re-run the indexer Job), not a one-line edit.
  That friction is the point: a one-line silent breakage is exactly what
  this guardrail exists to prevent.
- **Accepted cost:** `/readyz` now depends on Chroma metadata, so a
  Chroma outage also holds the API out of traffic. That is correct:
  an API that cannot verify what it is retrieving from should not take
  traffic (see ENGINEERING-NOTES Q2 for the liveness/readiness split
  that keeps this from becoming a restart storm).
