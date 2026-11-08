# ADR 0001 — Indexing is a Kubernetes Job, not an API startup task

- **Status:** Accepted
- **Date:** 2026-11-05
- **Deciders:** RAHBAR team (Mohsin Khan and partner)
- **Context:** RAHBAR has two paths that never share a process: an indexer that
  writes the vector store on demand, and an API that only reads it on every
  question (assignment sec. 3). The API runs as 3 replicas behind one
  Chroma volume. Indexing on API startup looks obvious — the pod that needs
  the index builds it — and it is wrong. This ADR records why, in the
  assignment's own four failure modes (sec. 4.2), so a future reader does not
  reintroduce the bug by "simplifying" the deployment.

## Decision

Indexing runs **only** as a Kubernetes `Job` (`k8s/base/indexer-job.yaml`)
and a weekly `CronJob` (`k8s/base/reindex-cronjob.yaml`) using the indexer
image. The API image contains **no** indexing code path in its startup:
no `indexer` import, no `run_indexing()` call, no entrypoint step that
writes to Chroma. The API's readiness probe (`/readyz`) checks that the
collection exists and is non-empty and reports not-ready otherwise, so a pod
is withheld from the Service until there is something to retrieve.

Re-indexing is one command, with no redeploy and no downtime:

```bash
kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar
```

## The four failure modes of indexing in API startup

### 1. Three pods race to write one volume — concurrent writers corrupt the index

With 3 API replicas and indexing in startup, three pods race to write one
volume. Three concurrent writers on one Chroma PVC, each halfway through a
different document, leave an index that no document produced: duplicate
chunk IDs, half-written collections, and embeddings from two different
passes interleaved in one collection. There is no lock that makes this safe
— Chroma's persistent client is not designed for three writers racing over
the same on-disk store — and the corruption is silent: retrieval returns
nonsense and no error appears anywhere. The object that prevents it is the
`Job`: Kubernetes runs it once, to completion, as a single writer, while
the API only ever reads.

### 2. Every restart re-indexes — a rolling update, an OOMKill, a node drain, or a readiness blip pays the full cost again

Indexing is the expensive path: PDF extraction, OCR of the scanned policy,
structure-aware chunking, and one embedding call per chunk over 40+ pages.
If that work lives in API startup, every restart re-indexes. A rolling
update, an OOMKill, a node drain, or a readiness blip each pays the full
extraction and embedding cost again — minutes of CPU and embedding calls
per pod, times three replicas, on every deploy. A Job pays that cost once,
when the material changes, which is exactly the cadence the RAG lecture
states: "indexing runs once, and again when the material changes; querying
runs on every question."

### 3. Readiness becomes a lie — ready before the index exists serves empty retrievals, or minutes to ready and the kubelet kills it halfway

There are only two ways to wire a probe around startup indexing, and both
lie. Either the pod reports ready before the index exists and serves empty
retrievals — users get confident-looking abstentions (or worse, hallucinated
answers from an empty context) while the index is still being built — or
it takes minutes to report ready and Kubernetes kills it halfway, so a
rolling update swaps three working pods for three that are still chunking
PDFs, and the rollout never completes. With a Job, readiness is honest:
`/readyz` returns 200 only when Chroma is reachable, the collection is
non-empty, and the embedding pin matches; otherwise 503, and the pod is
withheld from the Service without being restarted (see
`api/app/routes/health.py`).

### 4. You cannot re-index without a redeploy — a configuration change that needs a rebuild

If indexing only happens at startup, the only way to pick up a changed
document, a fixed chunker, or a corrected corpus is to redeploy the API —
a configuration change that needs a rebuild. That is the Friday failure
from Lecture 05: the system cannot evolve its data without also shipping
new code. With a Job + CronJob, re-indexing is decoupled from releases:
`kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar`
re-indexes in place, the weekly CronJob re-indexes on schedule, and the
indexer Job also invalidates the Redis semantic cache on completion so
stale cached answers are not served from the old index (assignment
sec. 3.3).

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Index in API startup, guarded by a lock file / leader election | Still pays the full cost on every restart; a lock only serialises the corruption in mode 1, it does not remove modes 2–4. Leader election adds a whole distributed-systems problem to save one Job manifest. |
| Index in an `initContainer` on the API Deployment | Same race (three pods, three initContainers, one volume) and same re-index-on-restart cost; also blocks pod startup for minutes, which reintroduces mode 3. |
| A long-running indexer Deployment | A Deployment is for a service that should always be up. Indexing is batch work that should run once and exit; a Deployment would idle, get restarted, and re-index — modes 2 and 4 again. |
| Manual `kubectl exec` indexing inside the Chroma pod | Unrepeatable, unaudited, and not in CI. The Job is the repeatable version of exactly this, with logs, a completion condition, and a CronJob schedule. |

## Consequences

- **Positive:** one writer, one reader; honest readiness; re-index without
  redeploy; the indexer Job's completion is an observable, CI-checkable
  event (`kubectl wait --for=condition=complete job/indexer -n rahbar`).
- **Positive:** the API can scale to 3–8 replicas (HPA) without any
  indexing cost, because scaling a reader is free.
- **Negative / accepted:** a fresh cluster serves nothing until the indexer
  Job has run once — `/readyz` stays 503 and the API stays 0/1 READY until
  then. That is the intended behaviour, and the README's apply order
  makes the Job an explicit, visible step rather than a hidden side effect.
- **Negative / accepted:** the indexer Job needs its own image, PVC access
  mode, and resource limits (notably memory — see ENGINEERING-NOTES Q4);
  that is one more object to maintain, and it is the correct price for
  correctness.
