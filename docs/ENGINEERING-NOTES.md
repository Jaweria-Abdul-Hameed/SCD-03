# ENGINEERING-NOTES — RAHBAR (assignment sec. 7)

Answering all seven required questions, each pointing to our own files
and line numbers. A generic answer scores zero, so every answer names the
failure, the object that prevents it, and the exact line.

> **STATUS OF THE NUMBERS AND LINE REFERENCES (updated 2026-11-08).** Every number in this
> file comes from a real run on the live minikube stack and is backed by a committed file under
> `docs/evidence/live/` or by `eval/results.json` / `eval/baseline.json`; where something was
> reasoned rather than measured it says so. Line references were re-checked against the files as
> committed (table at the end). The AI assistant used for this project (Claude Code) is named in
> `docs/AI-USAGE.md`; it helped write code, tests and these notes, and every answer below was checked
> against command output or file contents.

Shared constants used throughout: namespace `rahbar`;
`EMBED_MODEL=nomic-embed-text` (768 dims); images tagged only with
`${{ github.sha }}`, never the floating latest tag.

---

## Q1. Your API has 3 replicas and one Chroma volume. What exactly breaks if you move indexing into API startup? Name the failure, the object that prevents it, and the line in your manifest.

**Answer — all four failures (full reasoning: `docs/adr/0001-indexer-as-job.md`):**

| # | Failure if indexing moves into API startup | Object that prevents it | Manifest / code line |
|---|---|---|---|
| 1 | **Three pods race to write one volume.** Three concurrent writers on one Chroma PVC, each halfway through a different document, leave an index that no document produced — duplicate chunk IDs and interleaved embeddings. Specifically, Chroma relies on an embedded SQLite database for metadata and WAL management. SQLite relies on POSIX advisory file locking, which fails across multiple container pods mounting the same volume, triggering `sqlite3.OperationalError: database is locked` or silent database corruption. | The indexer **`Job`** — Kubernetes runs it once, to completion, as a single writer; the API only reads. | `k8s/base/indexer-job.yaml:8` — `kind: Job` (and `k8s/base/indexer-job.yaml:16` — `backoffLimit: 3`, `k8s/base/indexer-job.yaml:26` — `restartPolicy: OnFailure`) |
| 2 | **Every restart re-indexes.** A rolling update, an OOMKill, a node drain, or a readiness blip each pays the full extraction + OCR + embedding cost again, × 3 replicas. | The same `Job` + weekly `CronJob`: indexing runs once, and again when the material changes — never on pod restart. | `k8s/base/reindex-cronjob.yaml:4` — `kind: CronJob`, `k8s/base/reindex-cronjob.yaml:12` — `schedule: "0 3 * * 0"` (weekly, Sunday 03:00) |
| 3 | **Readiness becomes a lie.** Either the pod reports ready before the index exists and serves empty retrievals, or it takes minutes to report ready and the kubelet kills it halfway, so a rolling update swaps three working pods for three still chunking PDFs. | The API's honest `/readyz`: 200 only when Chroma is reachable, the collection is non-empty, Redis is up, and the embedding pin matches; otherwise 503. | `k8s/base/api-deployment.yaml:89` — `readinessProbe` on `/readyz`; `api/app/routes/health.py:30` — `def readyz()` |
| 4 | **You cannot re-index without a redeploy.** A changed document or a fixed chunker needs a rebuild — the Lecture 05 Friday failure. | The `CronJob` + manual re-index command, with no redeploy: `kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar`. | `k8s/base/reindex-cronjob.yaml:4` — `kind: CronJob` |

The API itself is the negative control: `api/Dockerfile:10` starts only
`uvicorn app.main:app` — there is no indexing step in the entrypoint —
and the app lifespan in `api/app/main.py:35–68` runs an embedding-pin
*check* only (with lines 51–66 logging any pin conflict), and the comment
at `api/app/main.py:36` stating "do NOT index. /readyz enforces readiness (503) on mismatch."
Furthermore, on completion the indexer Job executes event-driven cache invalidation
via `invalidate_semantic_cache()` (`indexer/pipeline/store.py:324`), flushing stale
semantic cache entries from Redis so newly indexed documents are immediately reflected in answers.
If indexing ever appears in API startup, the check that catches it is
`scripts/check_submission.py` (the "no indexing at API startup" audit)
and AUDITOR 2 in the verification phase — it is a −10 automatic
deduction (sec. 8).

---

## Q2. Your readiness probe depends on Chroma; your liveness probe does not. What happens to a 3-replica deployment if you swap them and Chroma is slow for 90 seconds?

**Answer — a cluster-wide restart storm that turns "slow" into "down".**

Our (correct) split:

- **Liveness** — `api/app/routes/health.py:24` (`/healthz`): process alive
  only. It never touches Chroma, Redis, or the LLM.
  `k8s/base/api-deployment.yaml:83` — `livenessProbe`, `periodSeconds: 20`,
  `failureThreshold: 3`.
- **Readiness** — `api/app/routes/health.py:30` (`/readyz`): 200 only if
  Chroma is reachable, the collection is non-empty, Redis is up, and
  `EMBED_MODEL` matches the collection metadata; otherwise 503 naming the
  failed dependency. `k8s/base/api-deployment.yaml:89` — `readinessProbe`,
  `periodSeconds: 10`, `failureThreshold: 3`. A failed readiness probe
  removes the pod from the Service; it does **not** restart it.
- **Startup** — `k8s/base/api-deployment.yaml:77` — `startupProbe` on
  `/healthz`, `failureThreshold: 30`, `periodSeconds: 2`, so liveness and
  readiness wait while the pod finishes booting.

**If you swap them** (liveness → `/readyz`, readiness → `/healthz`) and
Chroma is slow for 90 seconds:

1. At ~60 seconds (3 failed liveness probes × the 20 s liveness period:
   `periodSeconds: 20` × `failureThreshold: 3` = 60 s, well inside the
   90 s slowness) the kubelet decides each API pod is dead and **kills
   and restarts it**.
2. The restart does not help — Chroma is still slow — so the fresh pod
   fails liveness again, and is killed again. All 3 replicas enter this
   loop at roughly the same time, because they share the same slow
   dependency.
3. Meanwhile the swapped readiness probe (`/healthz`) keeps reporting
   "ready" throughout, so the Service keeps sending traffic to pods that
   are about to be killed mid-request. Users see failed requests from pods
   the cluster itself is about to destroy.
4. Net effect: what was merely slow (Chroma answering in 90 s, after
   which every pod would have recovered untouched) is now **down** — a
   restart storm in which no pod ever stays alive long enough to serve.
   The `startupProbe` does not save you here: it only delays liveness
   *at boot*, and these pods keep re-booting into the same slow Chroma.

That is exactly why sec. 4.3 says: "If liveness depends on a dependency,
one slow dependency becomes a cluster-wide restart storm: every pod is
killed, none recovers, and what was merely slow is now down." Readiness
protects your users; liveness protects your pod — and only a probe that
checks nothing external can do the second job. None of the rollout
guarantees in sec. 4.6 (`maxSurge: 1`, `maxUnavailable: 0`,
`k8s/base/api-deployment.yaml:19`) work without this split, because a
rollout that kills its own new pods can never go green. This is further
reinforced by the `preStop` lifecycle hook (`sleep 5` in `k8s/base/api-deployment.yaml:71–76`):
when an old pod terminates during rolling updates, the Endpoint controller asynchronously
deregisters its IP from Service endpoints while kube-proxy updates node iptables; the 5-second
sleep ensures in-flight requests complete cleanly before SIGTERM arrives.

---

## Q3. While the model generates, what is your CPU-based HPA actually measuring? Which signal should scale this service, and what would you need to build to use it?

**Answer.**

**What the CPU HPA actually measures.** Our HPA is
`k8s/base/hpa.yaml:19` — `minReplicas: 3`, `k8s/base/hpa.yaml:20` —
`maxReplicas: 8`, `k8s/base/hpa.yaml:27` — CPU target
`averageUtilization: 70`. The HPA computes utilisation as
`usage / requests.cpu` — which is why every container must set
`requests.cpu`, or the HPA shows `<unknown>/70%` forever
(`k8s/base/api-deployment.yaml:59` - `requests.cpu: 100m`, right-sized from
`kubectl top`, see Q4).

**Measured while the 15 golden questions ran** (`docs/evidence/live/kubectl-top-during-eval.txt`,
354 samples, 4 s apart): the Ollama pod used on average **2.54 CPU cores** (max 3.98) while the three
api pods used on average **6 m each - 6 % of their 100 m request** (max 91 m). `kubectl get hpa`
(`docs/evidence/live/hpa.txt`) shows `cpu: 2%/70%`. The HPA saw about 1/400 of the CPU the request
actually consumed, because the work happens in a different pod.

But while the model generates, the API pod is **waiting**: it has sent the
augmented prompt to the LLM (Ollama on the host, or a hosted endpoint)
and is blocked on a network read. From the pod's point of view generation
is I/O-bound, so its CPU stays low — typically a few percent — even while
every request is slow and the queue of waiting users grows. The CPU-based
HPA therefore measures **the pod's own local compute (JSON parsing,
embedding the question, serialising the answer), not the work the service
is actually doing**. Under a generation-bound load spike it will sit at,
say, 15%/70% and scale nothing, while p95 latency climbs and requests
time out. It only scales when the *local* work grows — e.g. a flood of
embedding calls or cache misses — which is the wrong trigger for this
service. It is still worth having (it catches genuine CPU saturation and
it is the only autoscaling the assignment requires), but it is measuring
a proxy that goes quiet precisely when the system is busiest.

**Which signal should scale a generation service.** The honest signals
are demand-side, not CPU-side:

1. **In-flight requests / requests per second per pod** — how many
   `/chat` calls are concurrently waiting on generation. This is the
   direct measure of "more users than we can serve".
2. **Generation latency / queue wait time** — p95 time from receiving
   the question to first token / completed answer, or time spent waiting
   for the LLM. This is what the user feels.
3. **LLM-side saturation** (if you own the model): Ollama queue depth /
   active generation slots. With ollama-host we do not own that process,
   so (1) and (2) are the signals available to us.

Scaling on in-flight requests is the right default: a pod can usefully
handle N concurrent generations (bounded by the LLM's throughput), so
"scale when in-flight per pod exceeds N" tracks the real bottleneck.

**What you would need to build to use it.** A CPU HPA cannot see these
signals, so you need a custom-metrics pipeline:

1. **Expose the signal:** the API already exposes `/metrics` in
   Prometheus format (`api/app/routes/metrics.py:10` — `@router.get("/metrics")`;
   counters/histograms include request latency, retrieval latency,
   generation latency, cache hits, abstentions, token usage).
   **No in-flight gauge exists yet** — `/metrics` does NOT currently
   expose in-flight requests, and no `rahbar_chat_in_flight` gauge is
   implemented; that is future work, not a shipped feature. To use this
   signal you would add a gauge `rahbar_chat_in_flight` (incremented on
   `/chat` entry, decremented on exit) and use the existing
   `generation_latency_seconds` histogram, emitted per request with its
   `request_id`.
2. **Collect it:** a Prometheus instance scraping the API Service
   (ServiceMonitor / scrape config), plus the **metrics-server** addon
   for CPU (`minikube addons enable metrics-server` — already in the
   README apply order) and the **Prometheus Adapter** to expose
   Prometheus metrics through the Kubernetes custom-metrics API.
3. **Scale on it:** replace (or complement) the CPU HPA with a second
   HPA — or a KEDA `ScaledObject` — targeting the custom metric, e.g.
   `averageValue: 5` in-flight requests per pod, `minReplicas: 3`,
   `maxReplicas: 8`. KEDA is the smaller lift: it can scale on a
   Prometheus query directly without the adapter.
4. **Guard it:** keep the CPU HPA as a backstop (an HPA can have
   multiple metrics and scales on whichever fires first), keep
   `maxUnavailable: 0` so scaling never takes capacity away mid-spike,
   and load-test the threshold — a wrong in-flight target either scales
   on every bursty minute or never scales at all.

Until that pipeline exists, the honest statement is: our HPA scales on
local CPU, which is a weak proxy for a generation-bound service, and the
custom-metrics HPA above is the documented next step — not a claim that
CPU scaling already tracks generation load.

---

## Q4. `kubectl top pods` shows your indexer's peak memory. What is your limit, what is your margin, and which exit code do you get if you set it wrong?

**Answer - limit 1 Gi, measured peak 298 Mi, margin 726 Mi (71 % of the limit); wrong limit = exit code 137.**

- **Limit and request (the manifest):** `k8s/base/indexer-job.yaml:64-65` -
  `limits: cpu 1000m, memory 1Gi`; `k8s/base/indexer-job.yaml:61-62` - `requests:
  cpu 250m, memory 384Mi`. The weekly CronJob that re-runs the same image carries the
  identical numbers (`k8s/base/reindex-cronjob.yaml:56-61`).
- **Peak (measured, committed):** `docs/evidence/live/kubectl-top-during-index.txt` is
  `kubectl top pods -n rahbar --containers` sampled every 4 s (450 samples) during the
  final full-corpus run: 15 documents, 480 chunks, OCR of 41 scanned pages, about 21
  minutes at that time. Highest indexer sample: **298 Mi memory, 595 m CPU**. The
  earlier first full run (12 PDFs, 473 chunks,
  `docs/evidence/live/kubectl-top-during-index-run1.txt`) peaked at 289 Mi / 450 m.
  Machine-readable index summary: `docs/evidence/live/index_done.txt`
  (480 chunks, storage amplification 1.071).
- **Margin:** `margin = limit - peak = 1024 - 298 = 726 Mi` - the limit is **3.4x** the
  measured peak. That is deliberately generous: embedding the largest document
  (Annual Report 2023-24, 85 pages, 111 chunks) and the OCR pass hold text, page images
  and a batch of vectors at once, a new longer document is the normal way this Job
  grows, and a Job that dies of OOM at minute 19 of 21 wastes the whole run. The request
  (384 Mi) is set near the observed peak, not near the limit - a padded request is a
  billed request (sec. 4.5). The 2 Gi / 1 Gi values that were here before this
  measurement were guesses and have been replaced.
- **Exit code if you set it wrong: 137** (128 + SIGKILL 9). Over the memory limit the
  container is OOMKilled: `kubectl describe pod -l job-name=indexer -n rahbar` shows
  `Last State: Terminated  Reason: OOMKilled  Exit Code: 137`, the Job retries
  `backoffLimit: 3` times (`k8s/base/indexer-job.yaml:16`) and then fails. Over the CPU
  limit a container is only throttled, never killed. **We saw exactly this exit code on
  the Ollama pod during this work:** with a 5 Gi limit and the llama.cpp prompt cache
  growing (one 275 MiB entry per distinct prompt) the pod was OOMKilled
  (`Last State: Terminated, Reason: OOMKilled, Exit Code: 137`); the cache is now
  disabled (`LLAMA_ARG_CACHE_RAM=0`, `k8s/overlays/incluster-ollama/ollama.yaml`).

**Every other number, justified from the same measurements** (idle:
`docs/evidence/live/kubectl-top-idle.txt`; under the 15-question eval:
`docs/evidence/live/kubectl-top-during-eval.txt`):

| Container | Measured (idle / peak under load) | Request | Limit | Reasoning |
|---|---|---|---|---|
| api (x3) | 2 m, 77 Mi / 91 m, 86 Mi | 100m / 128Mi (`api-deployment.yaml:59-60`) | 500m / 256Mi | request near typical; limit 3x peak memory. HPA `cpu: 3%/70%` at idle - a real value because the request exists |
| ui (nginx) | 1 m, 4 Mi / 1 m, 6 Mi | 10m / 16Mi | 50m / 64Mi | static files |
| chroma | 3 m, 143 Mi / 7 m, 203 Mi (during indexing) | 50m / 256Mi | 500m / 512Mi | 480 vectors; limit 2.5x peak |
| redis | 3 m, 9 Mi / 4 m, 21 Mi | 20m / 32Mi | 100m / 64Mi | cache of a few answers |
| indexer (Job) | - / 595 m, 298 Mi | 250m / 384Mi | 1000m / 1Gi | see above |
| ollama | 1 m, 4.7 Gi / 3.98 cores, 3.0 Gi | 1 CPU / 3Gi | 5 CPU / 5Gi | idle working set 4.7 Gi includes about 1.6 Gi of reclaimable page cache; models are 3 Gi; peak during the eval 3.0 Gi with the llama.cpp prompt cache disabled |

The previous values (api 250m/512Mi, chroma 250m/512Mi, redis 100m/128Mi, ui 50m/64Mi) were
5-25x the measured use: the "8 % paradox" of sec. 4.5 in our own manifests.

---

## Q5. Using recall@5 by question type: where is it worst, why do embeddings struggle there, and which technique from the RAG lecture addresses it?

**Answer - with the real numbers of the live run on the full corpus (`eval/results.json`, committed; `eval/baseline.json` holds the same shipped numbers).**

Measured on 2026-11-08 on the live minikube stack (15 documents, 480 chunks, chunks 512/64, `TOP_K=5`,
in-cluster Ollama `llama3.2:3b` + `nomic-embed-text`). Recall uses the **true retrieved chunk ids**
the API echoes (`retrieved_chunk_ids`, `api/app/schemas.py`), against chunk ids resolved from verbatim
answer quotes (`scripts/map_golden_to_chunks.py`) - not a citation proxy.

| Question type (n) | recall@5 | recall@3 | Source |
|---|---|---|---|
| Ordinary (8) | **0.94** | 0.69 | `eval/results.json` -> `by_type.ordinary` |
| Version-sensitive (2) | **1.00** | 1.00 | `by_type.version-sensitive` |
| **Exact-term (2) - worst** | **0.50** | 0.50 | `by_type.exact-term` |
| Prompt-injection (1) | 0.33 | 0.33 | `by_type.prompt-injection` (n = 1, see below) |
| Must-abstain (2) | n/a - abstention correctness **1.00** | n/a | `by_type.must-abstain` |
| **Overall** | **0.83** | 0.68 | `eval/results.json` -> `recall_at_5` / `recall_at_3` |

Other gate metrics of the same run: citation validity **1.00** (11 of 11 citations match a retrieved chunk),
abstention correctness **1.00** (G13 hostel, G14 bus routes), injection not obeyed. Per-question recall is
`compute_recall` (`eval/run_eval.py:169`, called at `eval/run_eval.py:422-423`), aggregated by type in
`aggregate()` (`eval/run_eval.py:472`). The (size, overlap) behind the numbers was chosen by measurement
(`docs/PIPELINE.md`: 0.833 at 512/64 versus 0.577-0.654 for the other three).

**Where it is worst: exact-term questions - 0.50 against 0.94 for ordinary questions.** (The prompt-injection
row is numerically lower, 0.33, but it is a single question whose "relevant" passages are the closest
fee-refund and scholarship text because the corpus has no fee-waiver rule - that is a definitional miss, not an
exact-term effect, and n = 1 carries no statistical weight.) The two exact-term questions are G11 ("what does
**clause 4.4** say ...") and G12 ("**minimum CGPA** to remain in good academic standing"). G11 was found; G12 was
not: the logged top-5 for G12 were four chunks that are all *about CGPA* - the Grading page ("If Warning Count becomes
three ..."), the Prospectus GPA definition, the Handbook clause 1.25 ("Minimum CGPA of 2.00 is required for
**graduation**"), the Prospectus honours table and clause 5.7 - and **not** the chunk with clause 5.4 ("Minimum CGPA
required to avoid academic warning is 2.00"), which is the one the question names. The system then answered from
the nearest-looking CGPA text ("varies by program ... 2.00 ... 2.50") - a plausible, cited, wrong-clause answer.

**Why embeddings struggle there.** An embedding represents the *meaning* of a chunk. All of the chunks above mean
"CGPA / warning / 2.00", so their vectors are close to each other and to the question; the distinguishing token
("5.4" versus "1.25", "good standing" versus "graduation") is a handful of tokens inside a 2 000-character chunk and
barely moves the vector. Embeddings find passages *about* a topic and are poor at "the passage that *says* 4.4" or
"the sentence that has *this* number": they blur exact terms into semantic neighbours, and the right chunk lands just
outside the top 5 while five topical chunks fill it. This is failure mode 7 of the corpus table (sec. 2). The
chunk-size experiment shows the same thing from the other side: the 100/0 configuration, where a chunk is almost
nothing but a clause number and its sentence, scored exact-term recall 1.00 (and ordinary 0.56).

**Which lecture technique addresses it: hybrid retrieval - dense retrieval plus BM25 keyword search.** BM25 scores a
chunk by whether it literally contains the query's rare terms ("4.4", "5.4", "CGPA", "graduation"), weighted by how rare
they are in the corpus; a hybrid retriever runs both and fuses the rankings (e.g. reciprocal-rank fusion), so the chunk
that contains the exact clause number is promoted even when its dense rank is poor, while definitional questions keep
the semantic matching. The place to add it is the retrieval layer (`api/app/retrieval/retriever.py`), the only component
that sees the query terms and the retrieved set before the prompt is built. It was **not** implemented: with 13 scored
questions a 5-point recall change is one question, so the improvement could not be demonstrated reliably here, and
the measured finding is exactly what motivates it. Two cheaper measures that were taken instead: structure-aware
chunking keeps a clause number with its text (`indexer/pipeline/chunk.py`), and the embedded text carries a
document-title + section header (`indexer/pipeline/embed.py: document_text`).

---

## Q6. Someone changes EMBED_MODEL in the ConfigMap and restarts only the API. What does your system do, and what would it have done without your guardrail?

**Answer.**

**With the guardrail — the pod sits at 0/1 READY and says so in the log.**

1. The ConfigMap change: `k8s/base/configmap.yaml:17` -
   `EMBED_MODEL` is edited (e.g. `nomic-embed-text` → some other model)
   and only the API Deployment is restarted. The indexer Job is **not**
   re-run, so the Chroma collection still holds vectors written by
   `nomic-embed-text`, and its collection metadata still says so:
   `indexer/pipeline/store.py:136` — `collection_metadata()` writes
   `model_name` and the vector dimension into the Chroma collection
   metadata when the index is built (`indexer/pipeline/store.py:158`,
   `get_or_create_collection()`, metadata applied at
   `indexer/pipeline/store.py:168–170`).
2. At startup the API already logs the conflict without crashing:
   `api/app/main.py:51–66` — the lifespan pin check compares the collection
   metadata with `settings.EMBED_MODEL` and logs a JSON line with
   `"event": "embedding_pin_mismatch"`, naming both sides
   (`collection_model`, `collection_dimension`, `expected_model`,
   `expected_dimension`). And on every `/readyz` probe the same
   comparison runs: `api/app/routes/health.py:51–59` — the pin comparison
   in `readyz()`.
3. They disagree, so `/readyz` returns **503**, the pod stays
   **0/1 READY**, and it is withheld from the Service — it takes no
   traffic at all. The 503 body names the conflict (exact wording from
   `api/app/routes/health.py:65–66`):
   ```
   embedding pin mismatch: collection model_name=<old-model> dimension=<old-dim>
   != EMBED_MODEL=<new-model> dim=768
   ```
   Verify with: `kubectl get pods -n rahbar` (api `0/1`),
   `kubectl describe pod -l app=api -n rahbar` (readiness probe failing),
   `kubectl logs deployment/api -n rahbar` (the `embedding_pin_mismatch`
   event above).
4. The fix is the intended two-step operation: re-run the indexer Job
   with the new model (`kubectl create job --from=cronjob/reindex
   manual-reindex-1 -n rahbar`), which rewrites the collection metadata;
   only then does `/readyz` go green. Full design:
   `docs/adr/0004-embedding-pin.md`.

**Without the guardrail — it would silently serve garbage.**

With no pin check, the restarted API would embed every question with the
new model and retrieve against vectors written by the old model. Vectors
from two different models are not comparable (sec. 3.2), so retrieval
would return nonsense — top-k chunks that are semantically unrelated to
the question — and **no error would appear anywhere**: no probe failure,
no log line, no metric spike, because every component individually
"worked". The LLM would then write a fluent, well-cited answer from the
wrong passages, with citations to chunks that do not support the claims.
That is the silent failure sec. 4.4 exists to prevent: "A rule is a
sentence in a README that someone breaks in week nine; a guardrail makes
the broken state unreachable." The difference between the two behaviours
is the whole point of the demonstration in sec. 4.4 — change the model,
restart only the API, and show 0/1 READY with a log line naming the
conflict, *instead of* silently serving garbage.

---

## Q7. The failure. Something cost you more than an hour. Describe the symptoms, what you wrongly believed first, and the exact command, metric or log line that finally told you the truth.

**Answer - the incident that cost the most time was real and is in this repository's own history: the `api` Deployment crash-looped with `API_PORT=tcp://10.96.x.x:8000`. Two more real failures of the same size are described after it.** (Honest note on method: this project was built with an AI assistant, Claude Code - see `docs/AI-USAGE.md`. The assistant proposed most of the hypotheses below, including the wrong ones; the diagnosis in each case was settled by a log line or command output, quoted here.)

### 1. The api pods crash-looped in a cluster where nothing had changed in the app

- **Symptoms.** After the first deploy to the CI cluster and to minikube the three `api` pods
  went `Running` -> `Error` -> `CrashLoopBackOff` within seconds, `READY 0/1`, restart count
  climbing, while `chroma`, `redis` and `ui` were healthy. The same image started fine with
  `docker run` and passed all 130+ unit tests. `kubectl get pods -n rahbar` showed
  `CrashLoopBackOff`; `/readyz` was never reachable.
- **What we wrongly believed first.** That it was a configuration or code bug: a bad
  `Settings` field, a pydantic v2 validation quirk, a wrong base image, a missing `PYTHONPATH`
  in the Dockerfile. We re-checked the image, the settings class and the ConfigMap for more
  than an hour, because the crash happened *before* any request and a Python traceback
  looks like "our code".
- **The line that told the truth.** `kubectl logs deploy/api -n rahbar --previous` (the
  *previous* container - the current one had not produced output yet) ended with the
  pydantic `ValidationError` for field `API_PORT`: *Input should be a valid integer,
  unable to parse string as an integer*, `input_value='tcp://10.96.x.x:8000'`. That value is
  not ours: Kubernetes injects **service-link environment variables** for every Service in
  the namespace (`<NAME>_PORT=tcp://<clusterIP>:<port>`), and our Service is called `api`,
  so it set `API_PORT`, which collided with the app's integer setting
  (`api/app/config.py:51`, `API_PORT: int = 8000`). Confirmed with
  `kubectl exec ... env | grep PORT` on a pod that stayed alive.
- **Fix.** `enableServiceLinks: false` on every pod spec (`k8s/base/api-deployment.yaml:33`,
  and `chroma-statefulset.yaml:48`, `indexer-job.yaml:28`, `redis.yaml:60`,
  `reindex-cronjob.yaml:30`, `ui-deployment.yaml:29`) - configuration comes from the ConfigMap,
  never from injected variables. Recorded with the other CI/CD root causes in
  `docs/evidence/ci_cd_green_runs.md`.

### 2. Every question abstained: Chroma's default distance is squared-L2, not cosine

- **Symptoms.** Smoke test after the first successful deploy: `/readyz` 200, three Ready
  replicas, the index non-empty - and *every* ordinary question returned
  `answered_from_context: false` with no citations.
- **What we wrongly believed first.** That the embeddings were broken (the stub provider,
  the wrong model, a wrong dimension) or that the LLM refused - i.e. a generation-side
  problem - so the first hour went into the embedding and provider code.
- **The line that told the truth.** The per-request JSON log line (spec sec. 4.8,
  `api/app/services/chat.py`) printed the retrieved `scores` - and they were all below
  `RELEVANCE_FLOOR`, including for questions whose answer sat in the top chunk. Chroma
  collections default to **squared-L2** distance; the API computes
  `similarity = 1 - distance` (`api/app/retrieval/retriever.py:52`), which is only meaningful
  for cosine. A real cosine of 0.37 becomes `2*0.37-1 < 0`. Fix: create the collection with
  `"hnsw:space": "cosine"` (`indexer/pipeline/store.py:148`), re-index. Lesson: the log line
  that records *scores* is what makes retrieval failures visible; without it this would have
  been blamed on the model forever.

### 3. `chroma-0` stuck `Pending` in CI: `Insufficient cpu`

- **Symptoms.** `e2e-eval` timed out waiting for the Chroma rollout on every run.
- **Wrongly believed.** A broken StatefulSet / PVC / storage class in kind.
- **Truth.** `kubectl describe pod chroma-0` -> Events: `FailedScheduling ... 0/1 nodes are
  available: 1 Insufficient cpu`. The prod footprint (3 api x 250m + chroma + redis + the
  indexer + kube-system) does not fit a single kind node on a 2-vCPU GitHub runner. CI now
  renders one api replica and smaller requests; the manifests were later right-sized from
  `kubectl top` (Q4), which also removed the underlying padding.

### 4. During the final measurement run (live minikube): the answers took minutes, then the node died

These are the failures of the last night, found with measurements, not guesses:

- **Generation at 1.2 tokens/s - every eval question timed out.** First live eval: 15 of 15
  questions failed (read timeouts and HTTP 500). Wrong belief: "CPU Ollama is just slow, raise
  the timeout." The truth came from a direct test inside the cluster:
  `kubectl exec deploy/ollama -- nproc` printed **24** (the host's cores) while the pod's CPU
  limit is 3-5; Ollama had started 24 threads that the CFS quota throttled. Calling
  `/api/generate` with `options.num_thread` 4 gave **15.6 tokens/s versus 1.19** (13x); with
  2 threads 8.9. Fix: `OLLAMA_NUM_THREAD=4` in the in-cluster overlay, passed by the api provider
  and by the indexer's embedder (`api/app/providers/ollama.py:41`,
  `indexer/pipeline/embed.py:90`). The full index went from 21 minutes to about 4.
- **Chroma's index silently lost vectors after an unclean node stop.** After the minikube
  node's containers all restarted at once (at that moment Ollama's working set had grown to 5.7 Gi on an
  8 GiB node; node memory exhaustion is our diagnosis from the timing - no kernel log was captured), recall@5 fell from 0.833 to 0.654 with **no error anywhere**: the collection
  still reported 480 chunks, `/readyz` was 200. The line that told the truth was the
  comparison of an exact brute-force search with Chroma's approximate search for the fee
  question: the exact top-1 (the Fee Structure chunk, similarity 0.759) was **not in the
  approximate top-5**. A re-index restored 0.833. `scripts/demo-up.ps1` now runs exactly
  this exact-versus-approximate check on every start and re-indexes if it disagrees, and
  the collection is built with `hnsw:search_ef=100` (`indexer/pipeline/store.py`).
- **Ollama OOMKilled (exit 137)** at the 5 Gi limit; see Q4.

**Lesson carried forward.** In all of these the first hypothesis was about *our code or the
model*, and the truth was a platform behaviour that one command exposes: `--previous` logs
(service links), the logged retrieval scores (distance metric), `describe pod` Events
(scheduling), `nproc` inside the container (threads), exact-versus-approximate search
(vector index). Diagnose in the sec. 9 order - `kubectl get pods`, `describe pod`, `logs` -
then measure the component directly before editing code.

---

## Line-reference verification table

Re-verified 2026-11-08 against the committed files: each line number below was looked up by its content (not copied from an earlier version of this file).

| Reference | What it is |
|---|---|
| `k8s/base/indexer-job.yaml:8` | `kind: Job` |
| `k8s/base/indexer-job.yaml:16` | `backoffLimit: 3` |
| `k8s/base/indexer-job.yaml:29` | `restartPolicy: OnFailure` |
| `k8s/base/indexer-job.yaml:62` | indexer memory request 384Mi |
| `k8s/base/indexer-job.yaml:65` | indexer memory limit 1Gi |
| `k8s/base/reindex-cronjob.yaml:4` | `kind: CronJob` |
| `k8s/base/reindex-cronjob.yaml:12` | weekly schedule |
| `k8s/base/api-deployment.yaml:14` | `replicas: 3` |
| `k8s/base/api-deployment.yaml:18` | `maxSurge: 1` |
| `k8s/base/api-deployment.yaml:19` | `maxUnavailable: 0` |
| `k8s/base/api-deployment.yaml:33` | `enableServiceLinks: false` (Q7) |
| `k8s/base/api-deployment.yaml:34` | `terminationGracePeriodSeconds: 30` |
| `k8s/base/api-deployment.yaml:59` | `requests.cpu: 100m` |
| `k8s/base/api-deployment.yaml:71` | `preStop` sleep hook |
| `k8s/base/api-deployment.yaml:77` | `startupProbe` on `/healthz` |
| `k8s/base/api-deployment.yaml:83` | `livenessProbe` on `/healthz` |
| `k8s/base/api-deployment.yaml:89` | `readinessProbe` on `/readyz` |
| `k8s/base/chroma-statefulset.yaml:25` | `kind: StatefulSet` |
| `k8s/base/chroma-statefulset.yaml:112` | `volumeClaimTemplates` |
| `k8s/base/hpa.yaml:19` | `minReplicas: 3` |
| `k8s/base/hpa.yaml:20` | `maxReplicas: 8` |
| `k8s/base/hpa.yaml:27` | CPU `averageUtilization: 70` |
| `k8s/base/configmap.yaml:17` | `EMBED_MODEL: "nomic-embed-text"` |
| `k8s/base/configmap.yaml:21` | `TOP_K` |
| `k8s/base/configmap.yaml:27` | `RELEVANCE_FLOOR: "0.64"` |
| `k8s/base/configmap.yaml:31` | `CACHE_THRESHOLD: "0.96"` |
| `k8s/base/configmap.yaml:32` | `TEMPERATURE: "0.0"` |
| `k8s/base/configmap.yaml:33` | `LLM_PROVIDER` |
| `api/app/routes/health.py:24` | `/healthz` (liveness only) |
| `api/app/routes/health.py:30` | `/readyz` |
| `api/app/routes/metrics.py:10` | `/metrics` endpoint |
| `api/app/services/grounding.py:37` | `abstain_answer()` |
| `api/app/services/grounding.py:213` | `validate_answer()` (citations vs retrieved chunks) |
| `api/app/services/chat.py:98` | relevance-floor abstention check |
| `api/app/config.py:51` | `API_PORT: int = 8000` (Q7) |
| `api/app/providers/ollama.py:41` | `num_thread` option (Q7) |
| `indexer/pipeline/store.py:136` | `collection_metadata()` (pin writer) |
| `indexer/pipeline/store.py:148` | cosine distance (Q7) |
| `indexer/pipeline/store.py:158` | `get_or_create_collection()` |
| `indexer/pipeline/store.py:324` | `invalidate_semantic_cache()` (Redis) |
| `indexer/pipeline/embed.py:90` | `OLLAMA_NUM_THREAD` in the embedder (Q7) |
| `api/app/retrieval/retriever.py:52` | `similarity = 1 - distance` (Q7) |
| `eval/run_eval.py:169` | `compute_recall` |
| `eval/run_eval.py:422-423` | per-question recall@3 / recall@5 |
| `eval/run_eval.py:472` | `aggregate()` overall + by type |
| `docs/evidence/live/kubectl-top-during-index.txt` | Q4 indexer peak: 298 Mi / 595 m (450 samples) |
| `eval/results.json`, `eval/baseline.json` | Q5 numbers (live, full corpus) |
| `eval/golden.yaml` | 15 questions: 8 / 2 / 2 / 2 / 1 |
| `docs/adr/0001-indexer-as-job.md`, `docs/adr/0004-embedding-pin.md` | Q1, Q6 design |

