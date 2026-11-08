# E2E Test Suite Ready — RAHBAR

## Test Runner
- **Command**: `pytest api/tests eval indexer/tests -v`
- **Expected Outcome**: All 150 tests pass with exit code 0.
- **Additional Quality Gates**:
  - `python scripts/check_submission.py` (12/12 mechanical submission checks pass)
  - `mypy api/app indexer/pipeline --ignore-missing-imports` (27 source files clean, 0 typing errors)
  - `ruff check api indexer eval scripts` (0 lint errors)
  - `ruff format --check api indexer eval scripts` (0 formatting deviations)
  - `kubectl kustomize k8s/base`, `k8s/overlays/dev`, `k8s/overlays/prod` (render cleanly; plus `k8s/overlays/incluster-ollama`)

## Test Suites & Tier Coverage Summary
| Test Suite / Tier | Test File | Test Count | Description |
|-------------------|-----------|:----------:|-------------|
| **Tier 1: Feature Coverage** | `api/tests/test_api.py` | 26 | FastAPI endpoints (`/healthz`, `/readyz`, `/metrics`, `/chat`), query embedding, vector retrieval, and prompt augmentation |
| **Tier 1: Pipeline Feature Coverage** | `indexer/tests/test_pipeline.py` | 40 | 5-stage indexing pipeline (Extract, Clean, Chunk, Embed, Store), Chroma vector persistence, model pinning metadata, cache invalidation |
| **Tier 2: Boundary & Corner Cases** | `api/tests/test_adversarial_chat.py` | 13 | Relevance floor abstention (scores below `RELEVANCE_FLOOR`), prompt injection resistance, citation validation, fallback on malformed LLM outputs |
| **Tier 3: Cross-Feature Combinations** | `eval/test_unwrapping_stress.py` | 43 | Schema unwrapping across nested vs flat responses, missing citations, empty context, HTTP error codes, CD client parity |
| **Tier 4: Real-World Workload Testing** | `eval/test_run_eval.py` | 28 | Golden dataset validation (15 questions across 5 types: ordinary, version-sensitive, exact-term, must-abstain, prompt-injection), recall@k, baseline comparison |
| **Total Automated Tests** | **5 Suites** | **150** | **100% Pass Rate Across Entire Repository** |

## Invariant Checks
| Check # | Description | Tool / Script | Status |
|:-------:|-------------|---------------|:------:|
| 1 | Required paths from sec. 10 repository layout exist | `scripts/check_submission.py` | PASS |
| 2 | No secrets or sensitive keys in tracked Git files | `scripts/check_submission.py` | PASS |
| 3 | Namespace is `rahbar` everywhere (no default) | `scripts/check_submission.py` | PASS |
| 4 | Chroma is a StatefulSet (1 replica) with PVC | `scripts/check_submission.py` | PASS |
| 5 | Chroma & Redis services use ClusterIP only (no NodePort/LoadBalancer) | `scripts/check_submission.py` | PASS |
| 6 | Every container specifies CPU/memory requests and limits | `scripts/check_submission.py` | PASS |
| 7 | No floating `:latest` tags in workflows or manifests | `scripts/check_submission.py` | PASS |
| 8 | All publishing and deploying jobs gated by `needs:` | `scripts/check_submission.py` | PASS |
| 9 | Golden dataset has >= 15 questions across all 5 mandatory types | `scripts/check_submission.py` | PASS |
| 10 | ADR 0001 covers all four failure modes and manual reindex command | `scripts/check_submission.py` | PASS |
| 11 | ENGINEERING-NOTES answers all 7 questions (headings Q1–Q7) | `scripts/check_submission.py` | PASS |
| 12 | `.gitignore` covers `*-secret.yaml` and does not ignore `eval/results.json` | `scripts/check_submission.py` | PASS |
