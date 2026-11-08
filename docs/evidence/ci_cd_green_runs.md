# CI/CD green runs (GitHub Actions)

The repository was re-created on 2026-11-08 with a clean history (`first commit`, then one project commit through
PR #1). Everything below is on the new repository; both workflows are green.

| Workflow | Run | Jobs |
|---|---|---|
| **CD** (push to `main`, merge of PR #1, commit `a3c4391097a8`) | https://github.com/mohsinkhandevs/SCD-02/actions/runs/42458660890 | `test`, `build-push` (three images pushed with the commit SHA), `deploy` (ephemeral kind cluster, `kubectl rollout status`, **smoke test through the Ingress**: cited ordinary answer + must-abstain) - all green |
| CI (pull request #1, `dev` -> `main`) | https://github.com/mohsinkhandevs/SCD-02/actions/runs/42458075896 | lint, test, manifests, build, scan, **e2e-eval (`GATE PASSED`)** - all green |
| CI (push to `dev`) | https://github.com/mohsinkhandevs/SCD-02/actions/runs/42458061900 | the same six jobs, green |
| PR gate demo (PR #2, **failing**) | https://github.com/mohsinkhandevs/SCD-02/actions/runs/42459120435 | `e2e-eval` fails with `GATE FAILED` when `RELEVANCE_FLOOR` is 0.95; merge blocked (`pr-gate-failing.txt`) |
| PR gate demo (PR #2, **green after the revert**) | https://github.com/mohsinkhandevs/SCD-02/actions/runs/42461436020 | all six jobs green (`pr-gate-green.txt`) |

**Docker Hub images (pushed by `build-push`)**, tag = the full commit SHA `a3c4391097a8387c986173bbd4386ba96ab82718`:
`mohsinkhandevs/rahbar-api`, `mohsinkhandevs/rahbar-ui`, `mohsinkhandevs/rahbar-indexer`
(the CD log prints `***/rahbar-api:a3c4391097a8...@sha256:c466a63a...`, `rahbar-ui ...@sha256:cd5e7f4a...`,
`rahbar-indexer ...@sha256:48f8dfd1...`; the username is a masked secret, so the log shows `***`).
Screenshots of the failing and the green PR are in `docs/evidence/screenshots/`.

Branch protection on `main`: pull request required, 1 approving review, the six checks required (strict), no force-push,
no deletion.

## Root causes found while getting the pipelines green

| Symptom (job / step) | Root cause | Fix |
|---|---|---|
| `chroma-0` Pending, `Insufficient cpu` (e2e-eval, deploy) | Prod footprint (3 api + chroma + redis + indexer + kube-system) does not fit one kind node on a 2-vCPU runner | CI/CD only: render 1 api replica, HPA min 1, smaller CPU requests (`sed` in `ci.yml` / `cd.yml`); the manifests were later right-sized from `kubectl top` |
| api `CrashLoopBackOff`: `API_PORT` = `tcp://10.96.x.x:8000` | Kubernetes service-link env vars; Service `api` injects `API_PORT`, which collides with the app's integer setting | `enableServiceLinks: false` on every pod spec (`k8s/base/*.yaml`) |
| indexer Job failing in CI, log showed `host.minikube.internal:11434` | CI never selected the stub provider; the `sed` that does so expected quoted YAML but `kustomize build` emits it unquoted | quote-agnostic `sed` in `ci.yml` / `cd.yml` |
| Smoke test: ordinary question returned no citations | Chroma defaulted to squared-L2; the API assumes cosine (`similarity = 1 - distance`), so every score fell under `RELEVANCE_FLOOR` and the API abstained | collection created with `hnsw:space: cosine` (`indexer/pipeline/store.py`) |
| e2e-eval gate: citation validity 0.0, recall unmeasurable | Gate used the real-corpus `golden.yaml` against the 3 fixture documents | `eval/golden.fixture.yaml` + `eval/baseline.fixture.json` for CI |
| **CD deploy smoke test failed after the live-evaluation merge**: `ordinary smoke question returned no citations` | the base ConfigMap now carries the relevance floor measured for the real embedding model (0.64); the CD cluster uses the stub provider, whose hash embeddings sit on a different similarity scale, so the ordinary question fell under the floor and abstained | `cd.yml` patches `RELEVANCE_FLOOR=0.35` together with `LLM_PROVIDER=stub` (as `ci.yml` does) and restarts the api |

| PR-gate demo passed when it should not have (first attempt on the new main: `RELEVANCE_FLOOR` 0.95, e2e-eval green) | recall is now computed from the *retrieved ids* the API echoes, so abstaining on everything leaves recall unchanged; citation validity had no citations to check and was only *skipped* | live-mode gate now fails when no citation was returned at all (`citation_unmeasurable`, `eval/run_eval.py`, 2 tests) - a strengthening, not a relaxation |

`eval/results.json` is the **live run on the full corpus** (in-cluster Ollama), not a CI artefact; CI gates against
`eval/baseline.fixture.json` on the 3-document fixture corpus with the stub provider (README, "Evaluation").
