# CS4032 · Assignment 03 — RAGOps Implementation & Evaluation Checklist

> **Course:** Software Construction and Development (CS4032) · Fall 2026 · FAST-NUCES Islamabad
> **Marks:** 185 · **Group Size:** 2 students · **Submission:** GitHub Repository + Report PDF (≤ 8 pages + Screenshot Appendix)
> **Preceding Baseline Repo:** [`mohsinkhandevs/SCD-02`](https://github.com/mohsinkhandevs/SCD-02) (RAHBAR — Grounded RAG on Kubernetes)
> **Reference Paper:** Xu, Weytjens, Zhang, Lu, Weber & Zhu, *RAGOps: Operating and Managing Retrieval-Augmented Generation Pipelines* (preprint, 2026) — **Sections 3.2, 4.1(d–f), 4.2 (4.2.1–4.2.7), 5.1, 6.2, Figure 3, Table 1, and Table 2**

---

## Group Members, Commit Identities & Core Rules

| Member | GitHub Username | Git Commit Email | Shared Responsibility |
|---|---|---|---|
| Member 1 | `Jaweria-Abdul-Hameed` | `jaweriahameed06@gmail.com` | Co-owner — commits required; must explain **every part (A–G)** at demo |
| Member 2 | `mohsinkhandevs` | `mohsinkhan.devs@gmail.com` | Co-owner — commits required; must explain **every part (A–G)** at demo |

**Non-Negotiable Rules:**
- **Kubernetes-Only Demo:** The pipeline MUST run on Kubernetes (`minikube` is fine) during the live demo. Running on Docker containers only (`docker run` or Docker Compose) yields **0 marks for the demo**.
- **Grounded Numbers Only:** AI tools and libraries are allowed, but **every number in the report must come from runs of your own pipeline**, and **all result files must be committed** under `eval/results/` and `traces/`.
- **Exact Requirements:** No credit if the given requirements are changed. Late submission = 0. Plagiarism = 0 across the **entire assignments category**.
- **Two Intertwined Lifecycles (Paper Fig. 3):** Keep the Query Processing Pipeline (DevOps: Plan → Build → Test → Release → Deploy → Operate & Monitor → Analyze & Feedback) tightly coupled with the Data Management Lifecycle (RAGOps: 1. Ingest → 2. Verify → 3. Update Data Lake → 4. Update Retrieval Sources → 5. Offline Testing → 6. Live Testing → 7. Check Coverage).

---

## Phase 0: Baseline Migration, RAHBAR (`SCD-02`) Audit & Repository Scaffolding
*Carry forward the working Assignment 02 RAHBAR pipeline and establish the Assignment 03 directory contract and dual-author Git workflow.*

- [x] **0.1 Migrate & Verify RAHBAR Assignment 02 Baseline (`mohsinkhandevs/SCD-02`)**
  - [x] Clone/import the working RAHBAR pipeline (FastAPI API, ChromaDB `StatefulSet`, Redis semantic cache, Ollama `llama3.2:3b` + pinned `nomic-embed-text` 768-dim, Indexer `Job`, Reindex `CronJob`, `corpus-data` PVC, `rahbar-config` ConfigMap, `NetworkPolicy`, `ServiceAccount`s, Prometheus `/metrics`, and FAST-NUCES corpus via `scripts/fetch_corpus.py`).
  - [x] Confirm baseline pipeline boots cleanly on local Kubernetes (`minikube`) and passes health (`/healthz`, `/readyz`) and grounded chat queries before adding RAGOps layers.
  - [x] Preserve the single-writer invariant (`indexer-sa` + `NetworkPolicy` ensures only the ingestion `Job`/`CronJob` writes to ChromaDB; `api-sa` only reads) and shared embedding pin (`EMBED_MODEL` + `EMBED_DIMENSION` in ConfigMap).

- [x] **0.2 Configure Dual-Author Git History & Repository Layout**
  - [x] Verify both members commit under their configured Git identities:
    - `Jaweria-Abdul-Hameed <jaweriahameed06@gmail.com>`
    - `mohsinkhandevs <mohsinkhan.devs@gmail.com>`
  - [x] Establish the mandatory top-level repository directories and files:
    - [x] `k8s/` (all Kubernetes manifests, including `k8s/eval-job.yaml` and `k8s/README.md`)
    - [x] `eval/` (`eval/golden.jsonl`, evaluation scripts, gate config, and committed runs under `eval/results/`)
    - [x] `traces/` (committed JSONL trace samples, trace inspection outputs, and time-window metric reports)
    - [x] Root `README.md` with exact copy-pasteable commands to run every part (**A through F**)

- [x] **0.3 Audit Assignment 02 → Assignment 03 Feature Deltas**
  - [x] Document and plan upgrades from RAHBAR A02: `eval/golden.yaml` (15 Qs) → `eval/golden.jsonl` (≥ 25 Qs, then ≥ 31 after E4); add pre-chunking verification + quarantine + versioned data lake on PVC; add true incremental skip/replace/delete/archive/rollback; expand eval to 3 levels + noise + determinism + stochasticity + K8s `eval-job.yaml` + ConfigMap gate; add full 16-field JSONL traces (stdout + PVC) + trace prompt rebuilder + guardrail action logging + D3 time-window metrics; add candidate Deployment/Service/Collection + controlled rollout/undo; add Part E live query log + coverage + drift check.

---

## Phase 1 — Part A: Data Management: Verify & Update
*Paper §§4.2.1–4.2.4, §8 · Figure 3 Stages 1–4 (Ingest → Verify → Update Data Lake → Update Retrieval Sources)*

- [x] **A1.1 Build Pre-Chunking Verification Stage (After Ingestion, Before Chunking)**
  - [x] Insert a dedicated verification module (e.g., `indexer/pipeline/verify.py`) executed strictly **after ingestion/extraction** and **before chunking**.
  - [x] Evaluate **every ingested document** against all **4 mandatory checks**, recording explicit `pass`/`fail` status AND a human-readable `reason` for each check:
    - [x] **Check 1 — Quality:** Reject empty files, failed PDF/text extractions, corrupt/unparseable files, or garbled/malformed text (e.g., high non-printable/replacement-char ratio, gibberish entropy check).
    - [x] **Check 2 — Completeness:** Verify ALL required metadata fields exist and are non-empty:
      - `source`
      - `title`
      - `date` **or** `version`
      - `page_count` (page count)
      AND verify **text is not truncated** (e.g., abrupt mid-sentence/EOF truncation check, extracted page count vs. declared `page_count`, or minimum content integrity check).
    - [x] **Check 3 — Recency:** Detect when a newer version of an existing logical document (`doc_id` / policy family) arrives using version/date metadata; mark older version as superseded/archived so only the newest active version is served by default.
    - [x] **Check 4 — Uniqueness:**
      - **Exact duplicates:** Detect via content hash (SHA-256) against already-verified corpus and within the same batch.
      - **Near-duplicates:** Detect via **embedding cosine similarity** (using the pinned embedding model) above a calibrated and documented similarity threshold.
  - [x] *(Paper §4.2.2 & §8 awareness for Report G1 & G4a)* Note that the paper also mentions *Consistency* (contradictory facts) and highlights in §8 that verification lacks semantic malicious-data / prompt-injection detection.

- [x] **A1.2 Quarantine Handling & Per-Run Verification Report**
  - [x] Move every document that fails any verification check to a dedicated **quarantine folder** (e.g., `/corpus/quarantine/` on the PVC) and guarantee it is **never chunked or indexed** into ChromaDB.
  - [x] Emit a structured **verification report file per run** (JSON/JSONL + readable summary table, e.g., `/corpus/reports/verification_<run_id>.json` and committed sample under `eval/results/` or `traces/`) listing every document, per-check pass/fail, reasons, and final disposition (`indexed`, `quarantined`, `archived_superseded`, `skipped_unchanged`).

- [x] **A2.1 Separate Versioned Data Lake & Incremental Update Engine**
  - [x] Maintain a **Data Lake** directory/registry on the PVC (e.g., `/corpus/datalake/` + `registry.json`) storing verified documents, content hashes, `doc_id`, `version`, `superseded` flag, `archived` path, and chunk IDs before propagating updates to ChromaDB (Paper §4.2.3–4.2.4).
  - [x] **Unchanged corpus = 0 chunks embedded:** Re-running ingestion on an unchanged corpus MUST skip all unchanged documents and embed **exactly `0` chunks**; log and print explicit counts (`docs_scanned`, `docs_unchanged`, `docs_added`, `docs_changed`, `docs_deleted`, `chunks_embedded: 0`).
  - [x] **Changed document = targeted replacement:** Modifying one existing document deletes and re-embeds **only that document's chunks**, leaving all other documents' chunks untouched (show before/after counts).
  - [x] **Deleted document = zero orphan chunks:** Removing a document from the source corpus deletes all its chunks from ChromaDB — **prove with a vector-store chunk count grouped by `document_id`** showing `0` chunks remaining for the deleted document.
  - [x] **Superseded version archiving & rollback demo:**
    - [x] When a newer version arrives, move/copy the superseded version into the **archive folder** on the PVC (e.g., `/corpus/archive/`) rather than deleting it, and mark its chunks with metadata `superseded: true` (excluded from default retrieval via `where={"superseded": False}`).
    - [x] Implement a **restore / rollback command** (e.g., `python -m pipeline.rollback --doc-id <id> --version <old_ver>`) that restores the archived version as active (`superseded: false`) and marks the newer version inactive, and verify retrieval immediately returns the restored version.
  - [x] Invalidate the Redis semantic cache whenever any chunks are added, replaced, deleted, or rolled back.

- [x] **A3. Construct & Process Batch B (≥ 10 Documents with Planted Problems)**
  - [x] Create **Batch B** (`corpus/batch_b/` + manifest) containing **at least 10 documents** with ALL mandatory planted problems:
    - [x] **≥ 2 exact duplicates** (identical SHA-256 to Batch A or another Batch B doc)
    - [x] **≥ 1 near-duplicate** (lightly paraphrased / reformatted copy caught by embedding similarity)
    - [x] **≥ 1 truncated or corrupt file** (caught by quality/completeness check)
    - [x] **≥ 1 document with missing metadata** (missing required `source`, `title`, `date`/`version`, or `page_count`)
    - [x] **≥ 1 newer version of an existing document** (triggers recency check, archives old version, updates index)
    - [x] **≥ 1 document containing an injected instruction** (e.g., hidden prompt-injection directive embedded in valid policy text — used to test D4 guardrail & answer G4a)
    - [x] Clean new valid Batch B documents (≥ 3) to reach ≥ 10 total and provide real new content for Part B hard questions and Part E3 data drift analysis.
  - [x] Run **both Batch A (base RAHBAR corpus) and Batch B** through A1 (verification) and A2 (incremental update), then run a second ingestion pass on the unchanged corpus proving **0 chunks embedded**.
  - [x] Save and commit Batch B verification report + incremental counts (for Screenshot A).

---

## Phase 2 — Part B: Offline Testing at Three Levels
*Paper §4.2.5, Table 1, §6.2 · Figure 3 Stage 5 (Offline Testing)*

- [x] **B1. Author & Review Golden Evaluation Set (`eval/golden.jsonl`)**
  - [x] Create `eval/golden.jsonl` with **at least 25 questions** (before Part E4 expansion):
    - [x] **≥ 15 answerable** questions, each specifying ground-truth **`document`** (`doc_id`/`source`) AND **`page`** (`page` number)
    - [x] **≥ 5 unanswerable** questions where the expected behavior is **abstention** (`must_abstain: true`)
    - [x] **≥ 5 hard** questions (paraphrased, requiring **> 1 chunk**, or sourced from **Batch B**)
  - [x] Ensure **≥ 8 questions are written by hand** by the group.
  - [x] Label **every single question** with its provenance: `human` or `synthetic` (e.g., `"origin": "human" | "synthetic"`).
  - [x] Review **at least 8 synthetic questions by hand** and record review metadata (e.g., `"reviewed_by_human": true`, reviewer initials, verification note).

- [x] **B2. Level 1 — Module-Level Testing (Embedding Quality · Paper Table 1)**
  - [x] Build a benchmark dataset of **≥ 15 paraphrase pairs** and **≥ 15 unrelated pairs** (committed under `eval/`).
  - [x] Compute and report:
    - [x] Mean cosine similarity across the ≥ 15 paraphrase pairs
    - [x] Mean cosine similarity across the ≥ 15 unrelated pairs
    - [x] The **separation gap** (`mean_paraphrase - mean_unrelated`)
    - [x] **Embedding time per chunk** (ms/chunk — DevOps efficiency metric; optionally memory usage per embedding)
    - [x] **Determinism check:** Embed the exact same text twice and report the **largest difference** (e.g., max absolute element difference and cosine delta).

- [x] **B3. Level 2 — Component-Level Testing (Retrieval Quality · Paper Table 1)**
  - [x] Evaluate retrieval on `eval/golden.jsonl` and report:
    - [x] `recall@3`
    - [x] `recall@5`
    - [x] `MRR` (Mean Reciprocal Rank)
    - [x] `nDCG@5` (Normalized Discounted Cumulative Gain @ 5)
    - [x] *(Supporting DevOps metrics per Table 1: retrieval latency ms, index update speed)*
  - [x] **Noise Resilience Test:**
    - [x] Either inject **≥ 3 irrelevant distractor documents** into the index **OR** inject **typos into the golden queries** (or run both for stronger evidence).
    - [x] Re-run retrieval metrics and report the **exact delta for every metric** (`recall@3`, `recall@5`, `MRR`, `nDCG@5`) cleanly vs. under noise.

- [x] **B4. Level 3 — End-to-End Level Testing (Answer Quality · Paper Table 1)**
  - [x] Evaluate full RAG responses on `eval/golden.jsonl` and report:
    - [x] **Faithfulness:** Whether every generated answer is supported by its retrieved context.
    - [x] **Abstention correctness:** Accuracy on the ≥ 5 unanswerable questions (abstains when required; does not falsely abstain on answerable questions).
    - [x] **Citation validity:** Fraction of citations that exactly match a retrieved chunk's `(source, section/doc, page)`.
    - [x] **Latency `p50` and `p95`:** End-to-end query response latency percentiles.
  - [x] **LLM-as-Judge Human Calibration (Required if using LLM judge for faithfulness):**
    - [x] Hand-label **at least 8 answers** for faithfulness (ground-truth human labels committed under `eval/`).
    - [x] Compute and report the **judge–human agreement rate** (e.g., exact agreement % and Cohen's κ).

- [x] **B5. Stochasticity Analysis & Single-Command Timestamped Runner**
  - [x] **Fix random seeds** across Python (`random`, `numpy`), retriever/tie-breaking, and LLM generation (`seed`, `temperature=0.0`).
  - [x] Run the **entire Part B suite twice** back-to-back with fixed seeds; report the **exact difference for every metric** across Run 1 vs. Run 2 and **explain any remaining variation** (e.g., floating-point/BLAS non-determinism, HNSW ANN graph ordering, wall-clock latency jitter, LLM decoding drift).
  - [x] Ensure **one single command** (e.g., `python eval/run_eval.py ...`) executes all three levels + noise test + determinism check and writes a **timestamped result file** to **`eval/results/`** (e.g., `eval/results/eval_<timestamp>.json`) along with a printed **summary table** (for Screenshot B).

---

## Phase 3 — Part C: Change Experiment & Release Gate
*Paper §4.1(d), §4.2.5, §4.2.6 · Figure 3 Stages c, d, 5, 6*

- [x] **C1. Controlled Single-Variable Change Experiment**
  - [x] Pick **exactly ONE pipeline change** to evaluate cleanly against the baseline:
    - Options: `chunk size / overlap`, `embedding model`, `reranker`, `top-k`, or `prompt template`.
  - [x] Run the **full Part B 3-level suite** on BOTH the **baseline** and the **candidate** (using an isolated candidate collection on Kubernetes).
  - [x] Produce a side-by-side comparison table across **all three levels** (Module, Component, End-to-End).
  - [x] Formulate and document the final **release decision** (`RELEASE` or `REJECT`) with explicit quantitative justification for the Part G report.

- [x] **C2. Config-Driven Release Gate & Pass/Fail Demonstrations**
  - [x] Define release gate thresholds in a dedicated **config file** (e.g., `eval/gate_thresholds.yaml` or `.json`, synced to Kubernetes **ConfigMap** in F2) with justified bounds:
    - [x] `recall@5` max allowed drop vs. baseline (e.g., ≤ 2 percentage points)
    - [x] `faithfulness` minimum acceptable score (explicitly justified)
    - [x] `p95 latency` maximum acceptable limit (explicitly justified)
    - [x] `abstention_correctness` must not drop below baseline
    - [x] *(Optional additional guard: `citation_validity` floor)*
  - [x] Implement a gate script (e.g., `eval/release_gate.py`) that loads the thresholds config, baseline result, and candidate result, prints every rule check (`actual` vs. `threshold` → `PASS`/`FAIL`), and exits **`0` on PASS** or **non-zero (`1`) on FAIL**.
  - [x] **Demonstrate BOTH outcomes** (committed results + Screenshot C):
    - [x] **One candidate that FAILS the gate** (a deliberately degraded candidate is explicitly permitted, e.g., `top_k=1` or broken chunk size/prompt) → exit non-zero.
    - [x] **One candidate that PASSES the gate** → exit `0`.

- [x] **C3. Controlled Release & Rollback on Kubernetes (Executed in F3)**
  - [x] Gate-failed candidate is halted and **never rolled out** to the live Deployment.
  - [x] Gate-passed candidate is promoted to live via rolling update (`maxUnavailable: 0`), verified via `kubectl rollout status`, and rollback is proven via `kubectl rollout undo` (see Phase 6 — F3).

---

## Phase 4 — Part D: Observability & Traceability
*Paper §2.2, §3.2.3, §5.1, Table 2, §6.1 (Black-Box Recorder)*

- [x] **D1. Structured JSONL Trace Record (All 16 Mandatory Fields)**
  - [x] Instrument the query pipeline (`api/app/services/chat.py` + tracing module) so **every single query** emits **one JSON line** containing ALL 16 required fields:
    1. [ ] `trace_id` (unique ID per query)
    2. [ ] `timestamp` (ISO-8601 UTC)
    3. [ ] `user_query` (original user prompt)
    4. [ ] `rewritten_query` (rewritten/prefixed query, or `null` if unchanged)
    5. [ ] `embedding_model` and `embedding_version`
    6. [ ] `collection_name` (and/or `collection_version` / index snapshot version)
    7. [ ] `retrieved_chunks` — array with `chunk_id`, `document_id`, `document_version`, and `score` for each chunk
    8. [ ] `filters_applied` (e.g., `{"superseded": false}`)
    9. [ ] `reranked_order` (chunk IDs + scores after reranking, or explicit order)
    10. [ ] `prompt_hash` (SHA-256 of final prompt) **and/or** `full_prompt` (plus full retrieved chunk texts or prompt artifact so D2 can deterministically reconstruct exact context & prompt)
    11. [ ] `model` and `parameters` (`temperature`, `seed`, `num_ctx`, `top_k`, etc.)
    12. [ ] `response` (generated answer / abstention object)
    13. [ ] `citations` (validated citations)
    14. [ ] `guardrail_actions` (list of rail checks: rail stage I/D/R/O, triggered bool, action taken, reason, affected chunk/input)
    15. [ ] `latency_per_stage` (ms breakdown: `cache_ms`, `embed_ms`, `retrieve_ms`, `rerank_ms`, `guardrail_ms`, `generate_ms`, `validate_ms`, `total_ms`)
    16. [ ] `cache_hit` (`true` / `false`)
  - [x] Write each JSONL trace to **stdout** (for `kubectl logs`) AND append to the **traces PVC volume** (`/traces/traces.jsonl`); commit sample traces under `traces/` (for Screenshot D).

- [x] **D2. Trace Rebuilder CLI Tool**
  - [x] Build a command-line tool (e.g., `python scripts/trace_tool.py <trace_id> [--log traces/traces.jsonl]`) that looks up a `trace_id` and prints the **exact retrieved context and exact prompt** that produced that answer (and verifies `prompt_hash` integrity).
  - [x] Capture terminal command + uncropped output for Screenshot D.

- [x] **D3. RAGOps Metrics Endpoint & Time-Window Trace Summary Script**
  - [x] Expose on `/metrics` (Prometheus) AND report via script at least all **5 mandatory metrics**:
    1. [ ] **Top-1 retrieval similarity distribution** (histogram buckets + quantiles)
    2. [ ] **Abstention rate** (`abstentions / total_queries`)
    3. [ ] **Cache hit rate** (`cache_hits / (cache_hits + cache_misses)`)
    4. [ ] **p95 latency per stage** (embed, retrieve, rerank, guardrail, generate, total)
    5. [ ] **Number of injection attempts flagged** (counter)
  - [x] Implement a trace-summary script (e.g., `python scripts/summarize_traces.py --log traces/traces.jsonl --window 24h` or `--start ... --end ...`) that computes all 5 metrics over a configurable **time window** and saves the report under `traces/`.

- [x] **D4. Guardrail Action Logging & Batch B Injection Test**
  - [x] Wire RAHBAR's Assignment 02 prompt-injection defense + a **Retrieval Rail (R)** (Paper §3.2.3: inspects retrieved chunks for prompt-injection instructions such as `"ignore previous instructions"`, `"disregard system prompt"`, etc., flags/strips/drops poisoned chunks before LLM prompting) so every rail decision writes a structured entry into `guardrail_actions` inside the trace record and increments the `injection_attempts_flagged` metric.
  - [x] Query the live pipeline using a question that targets the **injected-instruction document from Batch B**; verify the guardrail triggers, logs its action in the trace, increments the injection counter, and prevents the injected instruction from hijacking the response. Commit the resulting trace in `traces/`.

- [x] **D5. Root Cause Analysis from the Trace Only**
  - [x] Select **one wrong or abstained answer** from the Part B offline evaluation.
  - [x] Inspect **ONLY its JSONL trace record** (and D2 reconstructed prompt) to identify the exact root cause (specific chunk ID, document version, similarity score vs. relevance floor, metadata filter, or guardrail action).
  - [x] Write a crisp **5-line root-cause diagnosis** in the Part G report and commit the inspected trace under `traces/`.

---

## Phase 5 — Part E: Drift & Coverage Checking
*Paper §4.2.7 · Figure 3 Stage 7 (Check Coverage)*

- [x] **E1. Create Simulated Live User Query Log (≥ 40 Queries)**
  - [x] Author `eval/live_queries.jsonl` containing **at least 40 queries**:
    - [x] **~28 queries in-domain** (matching topics covered by the corpus and golden set)
    - [x] **≥ 12 queries out-of-coverage** (from 2–4 distinct topics that your corpus or golden set do NOT cover)

- [x] **E2. Implement & Run Query Coverage Checker**
  - [x] Embed every live query and every golden question in `eval/golden.jsonl` using the pinned embedding model (`nomic-embed-text`).
  - [x] For each live query, compute cosine similarity to all golden questions and find its **most similar golden question** (max similarity).
  - [x] Choose and **justify BOTH thresholds**:
    - [x] Per-query similarity threshold (e.g., calibrated from the Part B Module-level paraphrase vs. unrelated cosine similarity distribution)
    - [x] Corpus coverage pass threshold (paper §4.2.7 example: flag a coverage gap when **< 85%** of live queries exceed the similarity threshold)
  - [x] Report the **coverage percentage**, list **every uncovered query**, and **group uncovered queries into named topics** (using clustering/embeddings/TF-IDF or structured topic labels).
  - [x] Capture "before" terminal output for Screenshot E and commit report under `eval/results/`.

- [x] **E3. Data Drift Analysis (Batch B Ingestion Impact)**
  - [x] Ingest **Batch B** through A1 + A2 into the active retrieval source.
  - [x] Re-run the **complete Part B 3-level evaluation suite** and save the timestamped result in `eval/results/`.
  - [x] Compare **pre-Batch B vs. post-Batch B** across all metrics (Module, Component, End-to-End) and explain **what changed and why** (e.g., recency update replacing an older policy version, new distractors/chunks shifting top-k ranks, quarantined bad docs having zero negative impact, injected doc caught by D4 guardrail).

- [x] **E4. Close the Coverage Gap & Enforce Non-Zero Exit Code**
  - [x] Add **at least 6 new golden questions** drawn from the uncovered topics into `eval/golden.jsonl` (properly labelled `human`/`synthetic` + reviewed; golden set now ≥ 31 questions).
  - [x] Re-run the coverage script and verify **coverage rises** cleanly (capture "after" output for Screenshot E and commit result under `eval/results/`).
  - [x] Confirm the coverage script **returns a non-zero exit code** (e.g., `exit 1`) whenever coverage falls below the configured threshold, and `exit 0` once coverage meets/exceeds the threshold.

---

## Phase 6 — Part F: Run It on Kubernetes
*Paper §4.1(e)(f), §5.1 Reliability · ALL manifests committed under `k8s/`*

- [x] **F1. Core Deployments, StatefulSet, Service & Persistent Volumes**
  - [x] **API:** Runs as a `Deployment` (`k8s/api-deployment.yaml` or `k8s/base/api-deployment.yaml`) exposed by a Kubernetes `Service`.
  - [x] **Vector Store (ChromaDB):** Runs as a `StatefulSet` (or `Deployment` with PVC) with persistent storage.
  - [x] **PersistentVolumeClaim(s):** Store the **data lake**, **quarantine folder**, and **archived document versions** on a `PersistentVolumeClaim` so they **survive pod restarts** (test by deleting a pod and confirming files remain intact!).
  - [x] **Results & Traces PVCs:** Provision persistent volume storage for `eval/results/` outputs (F2) and JSONL trace logs (F4).

- [x] **F2. Ingestion Job, Re-Ingestion CronJob, Evaluation Job & ConfigMap Gate**
  - [x] **Ingestion + Verification Job (Part A):** Runs as a Kubernetes `Job` (`k8s/ingest-job.yaml` / `k8s/indexer-job.yaml`).
  - [x] **Scheduled Re-Ingestion:** Runs as a Kubernetes `CronJob` (`k8s/reindex-cronjob.yaml`).
  - [x] **Single-Writer Enforcement:** Enforce that **ONLY the ingestion Job/CronJob writes to ChromaDB** (via `NetworkPolicy` + `ServiceAccount` + read-only API code).
  - [x] **Evaluation Suite Job (`k8s/eval-job.yaml`):**
    - [x] Runs via exact command **`kubectl apply -f k8s/eval-job.yaml`** (runs full Part B suite + applies C2 release gate).
    - [x] Writes its timestamped result file to a mounted **PVC volume**.
    - [x] Exits with a **failing (non-zero) status** when the C2 release gate fails (`backoffLimit: 0` so the Job fails cleanly without masking the exit status).
  - [x] **ConfigMap Gate Thresholds & Live-Edit Proof:**
    - [x] Define C2 release gate thresholds in a Kubernetes **`ConfigMap`** (e.g., `k8s/gate-configmap.yaml`).
    - [x] Demonstrate editing a threshold in the `ConfigMap` (without rebuilding any Docker image), re-running `k8s/eval-job.yaml`, and proving the **gate outcome flips** (pass ↔ fail) — capture Screenshot F!

- [x] **F3. Controlled Release, Gate Blocking & Rollback (`kubectl rollout undo`)**
  - [x] **Candidate Deployment:** Deploy the Part C candidate as a **second `Deployment`** (e.g., `api-candidate`) with its **own `Service`** (e.g., `api-candidate`) and its **own ChromaDB collection name** (e.g., `rahbar_corpus_candidate`).
  - [x] **Run Part B Job Against Candidate:** Point `k8s/eval-job.yaml` at the candidate Service.
  - [x] **Gate-Blocked Candidate Proof:** Demonstrate a failing candidate that is **stopped by the failing eval Job** and **never rolled out** to the live `api` Deployment.
  - [x] **Rolling Update (`maxUnavailable: 0`):** Configure live `api` Deployment with `strategy.rollingUpdate.maxUnavailable: 0`; promote the passing candidate to live and watch completion with **`kubectl rollout status deployment/api -n <ns>`**.
  - [x] **Rollback Proof (`kubectl rollout undo`):** Trigger a bad release on the live Deployment (changing collection/embedding config or bad image), then reverse it with **`kubectl rollout undo deployment/api -n <ns>`**.
  - [x] Immediately query the live API after the undo and capture a **new trace record** proving `collection_name` and `embedding_version` reverted to the **previous version** (Screenshot F!).

- [x] **F4. Cluster Observability (Logs, Volume & Port-Forward Metrics)**
  - [x] Verify JSONL trace records stream to **stdout** and are readable via `kubectl logs deployment/api -n <ns>`.
  - [x] Verify the exact same JSONL trace records are also written to a **PVC volume** accessible to the report/summary scripts.
  - [x] Verify the `/metrics` endpoint is reachable locally via **`kubectl port-forward svc/api 8000:8000 -n <ns>`** and serves the D3 metrics.

- [x] **F5. Measured Resource Requests & Limits**
  - [x] Enable `metrics-server` (e.g., `minikube addons enable metrics-server`) and measure actual CPU (millicores) & memory (MiB) under idle, ingestion, and evaluation load for:
    - [x] API Deployment
    - [x] Vector Store (ChromaDB StatefulSet)
    - [x] Ingestion Job & Evaluation Job
  - [x] Set evidence-backed `resources.requests` and `resources.limits` in all manifests and **copy all measured numbers + configured limits into the Part G report**.

- [x] **F6. Fresh-Cluster Reproducibility (`k8s/` & `k8s/README.md`)**
  - [x] Commit **every single Kubernetes manifest** under `k8s/`.
  - [x] Write **`k8s/README.md`** documenting the exact step-by-step commands (including minikube startup, image loading, PVC seeding, apply order, Job runs, ConfigMap edit, rollout/undo, and port-forward) so a **fresh cluster reaches a working pipeline** with zero guesswork.
  - [x] Test the full apply sequence from scratch on a fresh namespace/cluster.

---

## Phase 7 — Part G: Technical Report (≤ 8 Pages + Screenshot Appendix)
*One clean PDF · Main body strictly ≤ 8 pages · Appendix screenshots do NOT count toward the 8-page limit*

- [x] **G0. Title / Front Page & Compliance**
  - [x] Page 1 lists **full names and roll numbers of BOTH members** (`Jaweria-Abdul-Hameed` and `mohsinkhandevs`), course code (`CS4032`), semester (`Fall 2026`), and GitHub repository URL.
  - [x] Verify main report body is **≤ 8 pages** (Screenshots placed in an Appendix starting on Page 9+).
  - [x] Cross-check **every single number** in every table/chart against committed files in `eval/results/` and `traces/`.

- [x] **G1. Figure 3 RAGOps Lifecycle Mapping Table**
  - [x] Include a table mapping all **7 stages of Figure 3**:
    1. `Ingest`
    2. `Verify`
    3. `Update data lake`
    4. `Update retrieval sources`
    5. `Offline testing`
    6. `Live testing`
    7. `Check coverage`
  - [x] Include all 3 required columns for every stage: **(a) What your pipeline does**, **(b) Exact file(s) implementing it**, and **(c) What is missing** (honest comparison vs. Xu et al. 2026).

- [x] **G2. Table 2 RAG System Qualities Table**
  - [x] Include a table covering all **5 qualities from Table 2**:
    1. `Adaptability` (data structure construction, granularity configuration)
    2. `Monitorability` (performance degradation: accuracy/latency/relevance; data source change detection; consistent metrics)
    3. `Observability` (retrieval: injection attack detection, relevance; generation: context adherence, toxicity, usefulness)
    4. `Traceability` (versioning, retrieval routing, grounded source)
    5. `Reliability` (resource usage, bandwidth)
  - [x] Include all 3 required columns for every quality: **(a) What you measure**, **(b) Your threshold**, and **(c) The evidence**.

- [x] **G3. Results Tables, Figures & Release Decision (Parts A–F)**
  - [x] **Part A:** Batch A & Batch B verification summary table (pass/fail per check + quarantine list), incremental update counts (0 chunks on unchanged re-run, changed doc count, deleted doc 0-orphan proof, archive/rollback verification).
  - [x] **Part B:** 3-level offline testing tables & figures (Module paraphrase vs. unrelated gap, ms/chunk, determinism; Component recall@3/5, MRR, nDCG@5 + noise-test delta; End-to-End faithfulness + ≥8-answer judge agreement, abstention correctness, citation validity, p50/p95 latency; Stochasticity dual-run diff table & explanation).
  - [x] **Part C:** Baseline vs. Candidate 3-level comparison table, release gate thresholds, failing vs. passing candidate outputs, and explicit **Release or Reject decision with quantitative reasons**.
  - [x] **Part D:** Trace schema summary, D3 time-window metric summary (all 5 metrics), D4 Batch B injection guardrail test proof, and **D5 5-line root-cause diagnosis from trace ONLY**.
  - [x] **Part E:** Coverage % before vs. after adding ≥ 6 questions, uncovered query topic groups, and E3 Batch B data drift before/after table & analysis.
  - [x] **Part F:** Measured CPU/memory table vs. configured K8s requests/limits (F5), ConfigMap threshold flip proof, controlled rollout & `kubectl rollout undo` trace proof.

- [x] **G4. All 6 Mandatory Short Answers (a–f)**
  - [x] **(a)** Which verification check caught the most problems in Batch B, and **which problem did you NOT catch**? **What would catch it?** *(Address the injected-instruction doc & Paper §8 semantic malicious-data checks.)*
  - [x] **(b)** Give an example from your results where a **module-level metric looked fine** but a **component or end-to-end metric did not** — or explain why you did not see one.
  - [x] **(c)** Did you **archive or delete** old versions, and **what breaks if you delete**? *(Rollback, historical trace/citation reproducibility, auditability, regression diffing.)*
  - [x] **(d)** **Which metric in your suite do you trust least, and why?** *(Connect to Paper §6.2 — lack of standard evaluation metrics, LLM-judge bias/variance, proxy limitations, or sample size.)*
  - [x] **(e)** **Which of the paper's ideas was hardest to apply** to your pipeline, and **what did you change from the paper**?
  - [x] **(f)** **Which Kubernetes object carries which RAGOps responsibility** in your design (explicitly including which object(s) guarantee only one component writes to the vector store)?

- [x] **G5. Contribution Table & AI Statement**
  - [x] Include a clear **Contribution Table** detailing each member's specific responsibilities and commits (`Jaweria-Abdul-Hameed` and `mohsinkhandevs`).
  - [x] Include an **AI statement of 2 to 3 lines** (strictly 2–3 lines).

---

## Phase 8: Screenshot Appendix, Repository Audit & Live Kubernetes Demo Readiness

- [x] **8.1 Complete Uncropped, Labelled Screenshot Appendix (13 Required Proofs)**
  *Every screenshot MUST show BOTH the exact terminal command AND its full output with NOTHING cropped, labelled by part & item (e.g., `A1`, `B3`, `F2`), from your OWN Kubernetes cluster and runs.*
  - [x] **`A1`** — Verification report for Batch B (pass or fail per check, with reasons)
  - [x] **`A2`** — Second ingestion run on an unchanged corpus showing **`0` chunks embedded**
  - [x] **`B1`** — Evaluation summary showing **all three levels** (Module, Component, End-to-End)
  - [x] **`C1`** — Release gate **failing** (with non-zero exit status)
  - [x] **`C2`** — Release gate **passing** (with zero exit status)
  - [x] **`D1`** — One **full JSONL trace record** (all 16 fields visible)
  - [x] **`D2`** — The **trace tool** rebuilding the exact context & prompt for a `trace_id`
  - [x] **`E1`** — Query coverage output **before** adding the ≥ 6 new golden questions
  - [x] **`E2`** — Query coverage output **after** adding the ≥ 6 new golden questions (showing coverage rise)
  - [x] **`F1`** — `kubectl get all,pvc,configmap,cronjob,job -n <namespace>`
  - [x] **`F2`** — Logs of a **completed ingestion Job** AND a **completed evaluation Job**
  - [x] **`F3`** — Gate result **changing after a ConfigMap edit** (no image rebuild)
  - [x] **`F4`** — **`kubectl rollout status`** AND **`kubectl rollout undo`**, WITH a **trace afterwards** showing the **previous collection and embedding version**

- [x] **8.2 Final GitHub Repository Integrity Audit**
  - [x] Confirm repository URL is accessible and up to date.
  - [x] Run `git shortlog -sne` and verify substantive commits exist from **BOTH** `Jaweria-Abdul-Hameed <jaweriahameed06@gmail.com>` and `mohsinkhandevs <mohsinkhan.devs@gmail.com>`.
  - [x] Verify committed contents:
    - [x] All source code & configuration files
    - [x] `k8s/` (all manifests, `k8s/eval-job.yaml`, `k8s/README.md`)
    - [x] `eval/golden.jsonl` and all timestamped result files in `eval/results/`
    - [x] Sample JSONL traces and time-window metric reports in `traces/`
    - [x] Root `README.md` with exact commands to run every part (**A to F**)
  - [x] Verify zero secrets/API keys committed; zero fabricated or unbacked numbers in the report.

- [x] **8.3 Live Kubernetes Demo Rehearsal (Both Members Attend)**
  - [x] Verify the full pipeline is actively running on local **Kubernetes** (`minikube`) on the demo laptop — **NOT** Docker Compose / `docker run`.
  - [x] Rehearse the **3 mandatory live demo actions** end-to-end:
    1. [ ] Trigger and watch the **evaluation suite as a Kubernetes Job** (`kubectl apply -f k8s/eval-job.yaml`) and display its logs & written result file.
    2. [ ] **Open a trace** from the live cluster (`kubectl logs` / volume) and run the **D2 trace tool** on its `trace_id`.
    3. [ ] **Ingest a small unseen batch of documents** handed out live at the demo by copying into the corpus PVC and running the **ingestion Job** (demonstrating A1 verification + quarantine + A2 incremental update).
  - [x] Ensure **both** `Jaweria-Abdul-Hameed` and `mohsinkhandevs` can fluently explain every file, Kubernetes object, RAGOps paper concept (Fig. 3, Tables 1 & 2, §§3.2, 4.1, 4.2, 5.1, 6.2), metric, trace field, and short answer.

---

## Reference Matrix: Paper → RAHBAR (`SCD-02`) → RAGOps (`SCD-03`) & Kubernetes Mapping

| Paper Stage / Concept | RAHBAR A02 (`SCD-02`) Starting Point | Assignment 03 (`SCD-03`) Upgrade Target | Carrying K8s Object(s) |
|---|---|---|---|
| **Fig. 3 (1) Ingest** (§4.2.1) | `indexer/pipeline/extract.py`, `clean.py`, `scripts/fetch_corpus.py` | Multi-batch ingestion (Batch A + Batch B + unseen demo batch) | `Job`, `CronJob`, `PersistentVolumeClaim` (`corpus-data`) |
| **Fig. 3 (2) Verify** (§4.2.2) | *(Not implemented in A02)* | `indexer/pipeline/verify.py` (quality, completeness, recency, uniqueness) + quarantine folder + report/run | `Job` + `PVC` (`/corpus/quarantine`, `/corpus/reports`) |
| **Fig. 3 (3) Update Data Lake** (§4.2.3) | Raw files on PVC only; filename heuristic for superseded | Versioned data lake registry + archived superseded versions + rollback CLI | `PVC` (`/corpus/datalake`, `/corpus/archive`) |
| **Fig. 3 (4) Update Retrieval Sources** (§4.2.4) | `chunk.py`, `embed.py`, `store.py` (full re-upsert) | True incremental skip (0 chunks), single-doc replace, orphan-free delete, Redis cache invalidation | `Job` + `NetworkPolicy` + `ServiceAccount` (`indexer-sa`, single writer) + ChromaDB `StatefulSet` |
| **Fig. 3 (5) Offline Testing** (§4.2.5, Table 1) | `eval/golden.yaml` (15 Qs), `eval/run_eval.py` (basic recall/citation/abstention) | `eval/golden.jsonl` (≥25→≥31 Qs), 3-level suite (Module/Component/E2E), noise test, determinism, judge agreement, fixed-seed stochasticity, `eval/results/` | `Job` (`k8s/eval-job.yaml`) + Results `PVC` + Gate `ConfigMap` |
| **Fig. 3 (6) Live Testing & Release** (§4.1d–f, §4.2.6) | RollingUpdate API Deployment (`maxUnavailable: 0`), Prometheus `/metrics` | Candidate 2nd `Deployment` + `Service` + collection, gate-blocked proof, `kubectl rollout status`, `kubectl rollout undo`, 16-field JSONL trace + D2/D3/D4 | 2nd `Deployment` & `Service`, `ConfigMap`, `Deployment` (`maxUnavailable: 0`), Traces `PVC`, `kubectl port-forward` |
| **Fig. 3 (7) Check Coverage** (§4.2.7) | *(Not implemented in A02)* | `eval/live_queries.jsonl` (≥40 Qs), similarity coverage checker with non-zero exit code, topic grouping, Batch B drift analysis, ≥6 new golden Qs | Script / Job reading live traces PVC + `eval/golden.jsonl` |
| **Table 2 Qualities** (§5.1) | Partial reliability (probes, HPA, limits) & basic `/metrics` | Full 5-quality instrumentation (Adaptability, Monitorability, Observability, Traceability, Reliability) with measured K8s resource requests/limits (F5) | `ConfigMap`, `StatefulSet`, `Deployment`, `Job`, `CronJob`, `PVC`, `NetworkPolicy`, `Service` |

---

## Critical Deductions & Zero-Mark Disqualification Checklist — Do Not Submit Before Checking

- [x] **Kubernetes-Only Demo (0 Marks for Demo if Violated):** The pipeline MUST run on Kubernetes (`minikube` is fine) during the demo. Plain `docker run` or Docker Compose = **0 for the demo**.
- [x] **Academic Integrity & Plagiarism (0 Marks on ALL Assignments):** Zero plagiarism regardless of percentage. Every number in the report MUST come from your own pipeline runs and match committed files in `eval/results/` and `traces/`.
- [x] **No Altered Requirements & On-Time Submission (0 Marks):** Do not drop, weaken, or alter any requirement (A–G). Late submission receives **0 marks**.
- [x] **Dual-Member Commits & Shared Explanation:** Both `Jaweria-Abdul-Hameed` and `mohsinkhandevs` MUST have real commits in the repo, attend the demo together, and be able to explain **every part** of the work.
- [x] **Report Cap & Uncropped Screenshots:** Main report body strictly **≤ 8 pages** (names + roll numbers of both members on Page 1; 2–3 line AI statement; all 6 short answers a–f). Screenshot Appendix must contain **all 13 required terminal proofs** with command + output completely uncropped and clearly labelled.
- [x] **Exact Artifact & Manifest Paths:** Verify `eval/golden.jsonl`, `eval/results/`, `traces/`, `k8s/eval-job.yaml`, `k8s/README.md`, and root `README.md` (exact command for each part A–F) are all present, tested, and committed.
