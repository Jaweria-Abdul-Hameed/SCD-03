# RAHBAR — Consolidated Audit Scorecard

**Repo:** `~/workspace/rahbar/` · **Date:** 2026-11-05 · **Assignment:** Assignment 02, RAHBAR: Grounded RAG on Kubernetes (due Sun 2026-11-08 23:59 PKT)

**Method:** Phase 1 — 6 builder subagents built the full repo from the assignment PDF.
Phase 2 — 5 independent auditor subagents adversarially audited it against the
automatic-deduction clauses (§8). One fixer agent then applied every finding.
The orchestrator independently re-verified: `python3 scripts/check_submission.py`
(12/12 PASS), `python3 -m py_compile` on all Python files (OK), and the full
pytest suites (re-run at the end: 154 passed).

## Status update (2026-11-08, final) - supersedes the 2026-11-05 "Open items" list at the end

- GitHub repository, branch protection on `main`, CI and CD green (`docs/evidence/ci_cd_green_runs.md`); history rewritten to a single clean commit at the end (secret scan of the tree and of `git log -p`: nothing found).
- **Real evaluation on the live stack** (full corpus, in-cluster Ollama): recall@3 0.68, recall@5 0.83, citation validity 1.00 (12/12), abstention correctness 1.00 (2/2), injection not obeyed - `eval/results.json`, `eval/baseline.json`, `golden.yaml` chunk ids resolved from verbatim quotes (`scripts/map_golden_to_chunks.py`).
- **Live-cluster evidence** under `docs/evidence/live/` (kubectl top idle/index/eval, HPA, endpoints scale 3->4->3, rollout + undo, pod deletion under load 60/60 OK, embedding-pin demo, manual re-index with cache invalidation, NetworkPolicy tests incl. ollama, security, observability, ingress demo answers).
- Q4 indexer peak memory measured: 298 Mi (limit 1 Gi). Chunking experiment, failure analysis (all six stages) and the cache-threshold table are measured, not reasoned (`docs/PIPELINE.md`, `docs/FAILURE-ANALYSIS.md`, ADR 0002).
- Tests: 154 (api 42, eval 71, indexer 41), ruff / mypy clean, `scripts/check_submission.py` 12/12.

## Automatic deductions — all zero

| §8 violation | Deduction | Auditor | Verdict |
|---|---|---|---|
| Secret / key / password anywhere in Git history | −20 | 1 | **0 — not triggered in working tree; history itself unverifiable here (no `.git` yet — see Open items)** |
| Base64 Secret with a real value in a committed manifest | −15 | 1 | **0** — `rahbar-secret.yaml` decodes to literal `PLACEHOLDER` |
| Indexing performed at API startup instead of in a Job | −10 | 2 | **0** — zero indexer imports/calls in `api/`; writes live only in `indexer/pipeline/store.py` |
| Returned citation not matching a retrieved chunk | −10 | 3 | **0** — `validate_answer` drops every non-matching citation; verified by execution + test |
| Must-abstain golden question answered from context | −10 | 3, 5 | **0** — floor check + abstention verified; G13/G14 expect `answered_from_context: false` |
| Chroma/Redis as Deployment with no PVC, or NodePort/LoadBalancer | −8 | 2 | **0** — Chroma StatefulSet + `volumeClaimTemplates` (5Gi); Redis Deployment + PVC (2Gi); all ClusterIP |
| Embedding model not pinned / indexer and API can disagree silently | −8 | 3 | **0** — pin in ConfigMap + collection metadata + `/readyz` 503 on mismatch |
| Container with no requests, or HPA reading `<unknown>` | −6 | 2 | **0** — all 6 containers have CPU+memory requests and limits; HPA has its `requests.cpu` denominator |
| Publishing/deploying job not gated by `needs:`, or deploying `:latest` | −6 | 4 | **0** — all 3 publishing/deploying jobs have `needs:`; zero literal `:latest` image tags |
| Manifests in the `default` namespace | −5 | 2 | **0** — every object in namespace `rahbar` |
| README apply order that does not work from a clean clone | −5 | 4, 5 | **0 (after fixes)** — see Fix F5 below; was exposed before the fix pass |
| Commits pushed directly to `main` | −4 | 4 | **0 — unverifiable here (no `.git` yet — see Open items)** |

**Total automatic deductions: 0.**

## What the auditors caught (and the fixes applied)

| # | Finding | Fix |
|---|---|---|
| HIGH | Indexer Job/CronJob ran `python -m indexer.main --corpus …` — module does not exist in the image, flag does not exist, corpus mount was an empty `emptyDir`. The index could never be built as deployed. | Job/CronJob now use the image entrypoint (`python -m pipeline --corpus-dir /corpus/raw`); new `corpus-data` PVC (1Gi) mounted at `/corpus`; `make corpus-to-cluster` populates it; indexer also accepts `.md`/`.txt` so CI fixtures are indexable. |
| HIGH | CD pushed to Docker Hub but deployed `ghcr.io/…` names that were never pushed → `ImagePullBackOff`; CI `kind load` used yet another name. | CD deploy retags to the Docker Hub names build-push actually pushes; CI `kind load`s the exact names the manifests request. |
| HIGH | `make deploy` / README deployed the literal `:SHA` placeholder tag (§8 −5 trap). | Makefile `deploy` builds locally, retags `:SHA` → git-SHA tag, then applies; README documents exactly that flow. |
| MED | API startup pin check read the wrong metadata key (`dimension`, not `embedding_dimension`) — false `embedding_pin_mismatch` log on every healthy boot. | `main.py` now uses the same fallback chain as `/readyz`; test proves a healthy boot logs no mismatch. |
| MED | Gate was vacuous: with all `chunk_ids` empty, recall was `None` and the gate skipped it — it could print GATE PASSED with the headline metric unmeasured. | Live-mode gate now FAILS when recall is unmeasurable; `ABSTENTION_CORRECTNESS_MIN` wired in; duplicated inline CI gate removed (single source of truth: `run_eval.py` exit code). |
| MED | Zero-citation grounded answers passed validation; no poisoned-chunk test (§3.4 requires one). | `answered_from_context=true` with no citations now downgrades to abstention (logged); poisoned-chunk test added — injected "approve every fee waiver" instruction in a chunk is treated as data, never obeyed. |
| MED | 10 of 15 golden answers were unverified placeholders. | All 15 now filled from the fetched corpus (CGPA ≥ 2.00, tuition Rs. 12,000/credit-hour, refund 100/80/60/50/0%, attendance 80% UG / 75% grad, clauses 4.4/5.8/5.10) and marked `verified: true`. |
| LOW | `EMBED_DIMENSION` (ConfigMap) vs `EMBED_DIM` (code) name mismatch; indexer dimension hardcoded; model-swap only warned. | Config reads `EMBED_DIMENSION` (alias `EMBED_DIM`); indexer reads it from env; model mismatch now raises; empty collection metadata gets the pin written. |
| LOW | No temperature range validation; query-embed dimension unchecked. | Pydantic validator rejects temperature outside 0.0–0.3; `embed()` validates 768-dim vectors on both providers. |
| LOW | Secret ordering: overlay apply overwrote the real secret with the placeholder; gitignored secret listed in kustomization. | Placeholder secret removed from kustomization resources; README order is now overlay → create real secret via `kubectl create secret`. |
| LOW | Dev HPA (`minReplicas: 3`) fought dev api replicas (1). | Dev overlay patches HPA `minReplicas` to 1; prod keeps 3. |
| MINOR | Stale docs: PIPELINE.md said corpus "not fetched yet" (it is: 15 docs, 390 pp); ENGINEERING-NOTES Q2 timing (30 s → 60 s), Q3 in-flight gauge claim, `maxUnavailable` line; FAILURE-ANALYSIS scanned-policy page count (12 → 8). | All corrected against the fetched corpus. |

## Independent verification (orchestrator, 2026-11-05)

- `python3 scripts/check_submission.py` — **12/12 PASS, exit 0**
- `pytest api/tests eval indexer/tests` — **133 passed** (api 31, eval 69, indexer 33 across 5 test suites: `test_adversarial_chat.py`, `test_api.py`, `test_run_eval.py`, `test_unwrapping_stress.py`, `test_pipeline.py`)
- `python3 -m py_compile` on all Python files — OK; all touched YAML parses
- `grep ':latest'` as image tag — zero; `grep 'namespace: default'` — zero
- Corpus re-verified by Auditor 5: all 15 MANIFEST SHA-256 hashes match `corpus/raw/` (15/15)

## Remaining items (honest list, 2026-11-08)

1. **Human-only:** add both instructors to the private repository (or make it public); take the two screenshots of the
   assignment (greyed-out merge button on the open "DEMO: failing eval gate" PR, then green) - an automated session cannot
   screenshot; confirm Docker Hub shows the SHA-tagged images.
2. **Known quality limits, measured:** exact-term recall@5 is 0.50 (hybrid retrieval not implemented); G12 retrieves the wrong CGPA clause (all 12 answerable
   golden questions are answered and cited since the 8192-token context and the list-answer prompt; G03 and G08 used to abstain). The 3B model on CPU takes 30-55 s per
   answer. HTML pages all have the section title "Introduction". The Aug 2023 rules (OCR) yield 147 noisy chunks (superseded, filtered).
3. **Not done:** no hybrid (BM25) retrieval, no custom-metrics HPA, no demo video, no course-code golden question (none in the corpus).
