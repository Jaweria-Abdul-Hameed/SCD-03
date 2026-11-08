# AI-USAGE — RAHBAR (assignment sec. 8: honest attribution, not avoidance)

We used AI in this assignment. The rule is honest attribution, not
avoidance. This file names the tools, what they wrote or shaped, and what
we changed afterwards and why. A specific disclosure carries no penalty;
presenting AI-generated work as our own is plagiarism under the course
policy. **We understand the work in this repository and can explain it.**
Every design decision in the ADRs and ENGINEERING-NOTES was read,
checked against the assignment, and corrected by us before submission —
including the line references in ENGINEERING-NOTES, which are flagged
there as best-effort until verified against the landed files.

## Tools used

- **Muse / Meta AI agent (Boone)** — the main agent, working through
  specialised subagents under a Master Orchestrator. The orchestrator
  split the build into six builder agents and five verification auditors
  (see below); it assembled, checked, and handed over their output.
  No other AI tool was used for code or prose in this repository.
- No AI tool was used to generate the corpus: the documents are real
  public FAST-NUCES documents fetched by `scripts/fetch_corpus.py`
  (see `corpus/MANIFEST.md` for URLs and SHA-256 hashes). No lecture
  slides, no LLM-generated corpus, nothing paywalled.

## What each agent wrote or shaped

| Agent | Scope | What it produced |
|---|---|---|
| AGENT_CORPUS | Corpus & data sourcing | `scripts/fetch_corpus.py`, `corpus/MANIFEST.md` (SHA-256 per file), `docs/CORPUS.md` (7 properties + failure modes A–E) |
| AGENT_INDEXER | Offline ingestion & storage | `indexer/pipeline/{extract,clean,chunk,embed,store}.py`, `indexer/Dockerfile`, `docs/PIPELINE.md` (3 chunk configs × recall@5, storage amplification) |
| AGENT_API | Online query, caching & grounding | `api/app/{routes,services,retrieval,providers}/`, `api/app/schemas.py` (`Answer` / `Citation`), `api/Dockerfile`; `/healthz` vs `/readyz`, Redis semantic cache, abstention + citation validation, `/metrics` + JSON logging |
| AGENT_K8S | Kubernetes platform & security | `k8s/base/*`, `k8s/overlays/{dev,prod}/*` — namespace `rahbar`, Chroma StatefulSet + PVC, Redis Deployment + PVC, API Deployment (3 replicas, 3 probes, `maxSurge: 1` / `maxUnavailable: 0`), HPA (3–8), indexer Job + weekly CronJob, ConfigMap + placeholder Secret, default-deny NetworkPolicy, security contexts |
| AGENT_EVAL | Evaluation & benchmarking | `eval/golden.yaml` (15 questions: 8 ordinary / 2 version-sensitive / 2 exact-term / 2 must-abstain / 1 prompt-injection), `eval/run_eval.py`, `eval/baseline.json`, `docs/FAILURE-ANALYSIS.md` (4 of 6 stages broken on purpose) |
| AGENT_DEVOPS | CI/CD, ADR & documentation | `.github/workflows/{ci.yml,cd.yml}`, `docs/adr/0001–0004`, `docs/ENGINEERING-NOTES.md`, `docs/AI-USAGE.md` (this file), `docs/ARCHITECTURE.md`, `scripts/check_submission.py`, `README.md`, `Makefile`, `.gitignore`, `LICENSE` |
| Verification panel (AUDITORS 1–5) | Adversarial audit | Independent checks against the sec. 8 automatic deductions (secrets, StatefulSet/PVC, embedding pin, `needs:` + SHA tags, golden set + docs, submission checker). Findings were fed back and fixed; the audit scorecard is in the submission notes. |

## What we changed afterwards and why

1. **Line references in ENGINEERING-NOTES.** The AI-drafted notes first
   cited file:line numbers for files the parallel builders had not yet
   landed. We verified every reference against the landed files on
   2026-11-05 and corrected them (the verification table at the end of
   that file records the status of each). Reason: a confident-looking line
   number that points at the wrong line is worse than an honest
   "unverified" — the marker checks these.
2. **Q4 (indexer peak memory) and Q5 (recall@5 by type).** The draft
   contained plausible-looking numbers with no measurement behind them.
   We removed the invented peak entirely at that time (the draft marked it
   as not measured); the final Q4 quotes the measured peak (298 Mi) from
   `docs/evidence/live/kubectl-top-during-index.txt` and Q5 the live
   full-corpus recall@5 by type from `eval/results.json` (see the 2026-11-08 addendum).
   Reason: sec. 4.5 and sec. 5 require numbers justified by measurement,
   and an invented measurement is fabrication.
3. **Q7 (the >1-hour failure).** The draft read like a live-cluster war
   story. We rewrote it as a clearly labelled reconstructed/documented
   incident from the assignment's own sec. 9 trap table (NetworkPolicy
   blocks DNS on port 53), because no live incident of that length had
   actually happened. Reason: presenting a reconstructed trap as a lived
   incident would be dishonest, and the trap is the useful lesson either
   way.
4. **Workflows: least-privilege permissions and the gate.** We checked
   every job in `ci.yml` / `cd.yml` has its own `permissions:` block,
   that every publishing/deploying job has `needs:`, and that no
   the floating `latest` tag appears anywhere (verified by grepping for the floating latest tag).
   Reason: these are −6 automatic deductions (sec. 8), and a workflow
   that "looks right" but misses a `needs:` fails silently until the
   audit.
5. **Secrets hygiene.** We confirmed no real secret is committed: the
   Secret manifest holds placeholders only, `*-secret.yaml` is
   gitignored, the LLM key is created from the command line (README),
   and `scripts/check_submission.py` scans for secret patterns. Reason:
   a secret in Git history is −20 and requires rotation plus an incident
   note (sec. 8).
6. **Corpus verification.** We did not accept the AI's golden-set
   clause/section references blindly: every expected answer was checked
   against the fetched documents (G01 clause 4.2 -> 4.4/5.8/5.10, G12
   clause 5.4, G15 "no waiver rule exists" were corrections), and the
   chunk ids are resolved from verbatim quotes, not typed, because page counts and
   clause numbers shift between versions. Reason: a golden set written
   from chunks already retrieved gives a flattering, meaningless number
   (sec. 5.1).

## Statement of understanding

We (the submitters) read the assignment, the ADRs, the pipeline and
evaluation docs, and the workflows in this repository. We can explain:
why indexing is a Job and not API startup (ADR 0001, four failure
modes); why `/healthz` must not touch Chroma or Redis while `/readyz`
must (ENGINEERING-NOTES Q2); how the embedding pin is enforced in code
and what happens on a mismatch (ADR 0004, Q6); why the semantic cache is
Redis and when it is invalidated (ADR 0002); why exact-term recall is
the worst and what hybrid retrieval does about it (Q5); and what the CI
gate enforces and why (sec. 5.4, `ci.yml` e2e-eval job). Every
number that was once marked "not measured" has since been measured on the live
stack (2026-11-08 addendum below).

## Addendum (2026-11-06/07): CI/CD debugging with Claude Code

Tool: Claude Code (Claude Sonnet 5.5), used interactively against this repo and
the GitHub Actions logs. What it did: read the failing run logs with `gh`,
diagnosed the five root causes listed in `docs/evidence/ci_cd_green_runs.md`,
and wrote the fixes (workflow `sed` changes, `enableServiceLinks: false`, the
Chroma cosine setting, `eval/golden.fixture.yaml`, `eval/baseline.fixture.json`)
plus the regenerated `eval/results.json`. What we checked: every fix was
re-run in CI until both workflows were green, and the fixture eval gate was
reproduced locally against a real Chroma instance before pushing. Known
limits we state openly: the fixture golden set is calibrated to the stub
provider's lexical retrieval and proves the pipeline, not real retrieval
quality; full-corpus numbers and live-cluster evidence still come from a
minikube run.

## Addendum (2026-11-08): the autonomous overnight session (Claude Code, Claude Sonnet 5.5)

**Tools.** Claude Code (model Claude Sonnet 5.5) ran for several hours **without a human present**, with shell
(Git Bash and PowerShell), `kubectl`, `minikube`, `docker` and `gh` access to this repository, the local
minikube cluster and the GitHub repository, under explicit written permissions (what it may and may not
do: no secrets, no host-Ollama exposure, no invented measurements, no lowered gates).

**What it wrote or changed** (all in the commit history of `dev`):

- indexer: HTML extraction with atomic `[TABLE]` blocks and a regression fix for page-sized chunks;
  version-pair detection (`doc_version`, `superseded`); short section titles; nomic task prefixes and a
  document header for the embedded text; a retry for over-long embedder input; `hnsw:search_ef`;
  `OLLAMA_NUM_THREAD`;
- api: `retrieved_chunk_ids` in the response (true recall), a stricter `format` schema, citation
  canonicalisation / post-hoc attribution / flag reconciliation in `grounding.py`, `LLM_TIMEOUT_S`,
  `OLLAMA_NUM_THREAD`; relevance floor 0.64, cache threshold 0.96 and temperature 0.0 - each chosen from a
  measurement documented in `docs/PIPELINE.md`, `docs/adr/0002-semantic-cache-redis.md` and `k8s/base/configmap.yaml`;
- Kubernetes: the `incluster-ollama` overlay, right-sized requests/limits from `kubectl top`, ui rollout strategy;
- evaluation: `scripts/map_golden_to_chunks.py`, `scripts/recall_probe.py`, `scripts/cache_threshold_probe.py`,
  the live `eval/results.json` + `eval/baseline.json`;
- docs and scripts: the failure analysis with live measurements, ENGINEERING-NOTES Q3-Q7, PIPELINE, CORPUS
  verification, `docs/DEMO.md` and the PowerShell `demo-*.ps1` / `rebuild-from-scratch.ps1` scripts.

**What was verified, and how.** Each change was followed by `ruff`, `mypy` and the test suite (154 tests at
the end) and, for behaviour that unit tests cannot show, by measurement on the live stack: the retrieval
experiments (four chunk configurations), the full 15-question evaluation (repeated after every pipeline
change), `kubectl top` during indexing and evaluation, and the cluster demonstrations (rollout/undo, pod
deletion under load, embedding pin, manual re-index) whose raw output is committed under
`docs/evidence/live/`. Several of the assistant's own first fixes were wrong and were corrected by
measurement - e.g. it first blamed generation speed on a small CPU limit (the cause was Ollama's thread count),
and it first raised the Ollama memory limit to 7 Gi, after which every pod on the node restarted at once, most likely memory exhaustion (see Q7).

**Limits we state openly.** The assistant cannot take screenshots or record video, so the two PR-gate
screenshots of the assignment (greyed-out merge button, then green) must be taken by a human from the open
demo pull request; no demo video exists. The evaluation set is small (13 answerable questions): one question
moves recall@5 by 4-8 points, and the exact-term and injection rows are 2 and 1 questions. Retrieval quality
and the 3B model's counting/format reliability are weaker than a hosted model would be; the
fixes (prompt, schema, attribution) make the *pipeline* robust to that, they do not make the model larger.
We (the submitters) are responsible for being able to explain every file; the assistant's explanations in
`docs/ENGINEERING-NOTES.md` are written to be checked against the cited lines and evidence files.

## Addendum (2026-11-08, afternoon): the pre-submission verification (Claude Code, Claude Sonnet 5.5)

**Tools.** Claude Code (Claude Sonnet 5.5) with shell, `kubectl`, `minikube`, `docker`, `gh` and the built-in browser,
asked to verify the whole assignment end to end and fix real problems, with the same rules as before (no secrets, no
lowered gate, no push without asking).

**What it did.** Re-ran the static checks, the 154 tests, the live evaluation and `demo-check.ps1`; tested the
chatbot with about 40 questions through the UI path and compared each answer with the source text in Chroma; read the
failed CI logs. It changed: `ci.yml`/`cd.yml` (tool downloads no longer depend on GitHub release URLs, which were
returning HTTP 504), `indexer/pipeline/chunk.py` (wrong `page` metadata) with a test, `scripts/demo-check.ps1` (checks
that matched a number anywhere in the JSON), the evidence and the stale test counts. It tried two answer-quality
changes (a prompt rule for counts, and moving a citation to the best-supporting chunk), measured both on the live
stack, saw that they made answers worse (a PLO count of "4"; an old-version answer moved to the Prospectus) and
reverted them; the findings and the remaining weak answers are in `docs/evidence/final-verification-2026-11-08.md`.
The re-index with the new indexer was run by the assistant after the submitters approved it; the submitters still have to review these changes before submitting.

