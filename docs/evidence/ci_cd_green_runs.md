# CI/CD green runs (GitHub Actions)

Both workflows are green on the final commit. History was rewritten on 2026-11-08 to a single clean commit
(`7667e2e`, "RAHBAR: grounded RAG on Kubernetes (assignment 02)"); the runs below are on that commit.

| Workflow | Run | Jobs |
|---|---|---|
| **CD** (push to `main`, commit `7667e2e`) | https://github.com/mohsinkhandevs/SCD-02/actions/runs/42430754446 | `test`, `build-push` (images pushed with the commit SHA), `deploy` (ephemeral kind cluster, `kubectl rollout status`, **smoke test through the Ingress**: cited ordinary answer + must-abstain) - all green |
| CI (push to `dev`, commit `7667e2e`) | https://github.com/mohsinkhandevs/SCD-02/actions/runs/42430756872 | lint, test, manifests, build, scan, **e2e-eval (`GATE PASSED`)** |
| CI (pull request before the rewrite) | https://github.com/mohsinkhandevs/SCD-02/actions/runs/42429479092 | the same six jobs, green |
| CD (the merge before the rewrite) | https://github.com/mohsinkhandevs/SCD-02/actions/runs/42430114502 | green (the run before it, 42427126471, failed - see the table below) |
| PR gate demo v2 (blocked, then green) | `docs/evidence/pr-gate-failing.txt`, `docs/evidence/pr-gate-green.txt` | `e2e-eval` fails with `GATE FAILED` when `RELEVANCE_FLOOR` is 0.95, passes after the revert |

**Docker Hub images (pushed by `build-push`)**, tag = the full commit SHA `7667e2e8dbc48c270b7172422d7e5f5fa022347e`:
`<DOCKERHUB_USERNAME>/rahbar-api`, `<DOCKERHUB_USERNAME>/rahbar-ui`, `<DOCKERHUB_USERNAME>/rahbar-indexer`
(the log prints `***/rahbar-api:7667e2e8...`, the username being a masked secret; the push is confirmed by the
`pushing manifest for docker.io/***/rahbar-api:7667e2e8...@sha256:e745ee09...` line of the run). The Docker Hub page itself
could not be opened from the automated session: confirm it shows the tags.

## Root causes found while getting the pipelines green

| Symptom (job / step) | Root cause | Fix |
|---|---|---|
| `chroma-0` Pending, `Insufficient cpu` (e2e-eval, deploy) | Prod footprint (3 api + chroma + redis + indexer + kube-system) does not fit one kind node on a 2-vCPU runner | CI/CD only: render 1 api replica, HPA min 1, smaller CPU requests (`sed` in `ci.yml` / `cd.yml`); the manifests were later right-sized from `kubectl top` |
| api `CrashLoopBackOff`: `API_PORT` = `tcp://10.96.x.x:8000` | Kubernetes service-link env vars; Service `api` injects `API_PORT`, which collides with the app's integer setting | `enableServiceLinks: false` on every pod spec (`k8s/base/*.yaml`) |
| indexer Job failing in CI, log showed `host.minikube.internal:11434` | CI never selected the stub provider; the `sed` that does so expected quoted YAML but `kustomize build` emits it unquoted | quote-agnostic `sed` in `ci.yml` / `cd.yml` |
| Smoke test: ordinary question returned no citations | Chroma defaulted to squared-L2; the API assumes cosine (`similarity = 1 - distance`), so every score fell under `RELEVANCE_FLOOR` and the API abstained | collection created with `hnsw:space: cosine` (`indexer/pipeline/store.py`) |
| e2e-eval gate: citation validity 0.0, recall unmeasurable | Gate used the real-corpus `golden.yaml` against the 3 fixture documents | `eval/golden.fixture.yaml` + `eval/baseline.fixture.json` for CI |
| **CD deploy smoke test failed after the live-evaluation merge** (run 42427126471): `ordinary smoke question returned no citations` | the base ConfigMap now carries the relevance floor measured for the real embedding model (0.64); the CD cluster uses the stub provider, whose hash embeddings sit on a different similarity scale, so the ordinary question fell under the floor and abstained | `cd.yml` patches `RELEVANCE_FLOOR=0.35` together with `LLM_PROVIDER=stub` (as `ci.yml` does) and restarts the api |

| PR-gate demo passed when it should not have (first attempt on the new main: `RELEVANCE_FLOOR` 0.95, e2e-eval green) | recall is now computed from the *retrieved ids* the API echoes, so abstaining on everything leaves recall unchanged; citation validity had no citations to check and was only *skipped* | live-mode gate now fails when no citation was returned at all (`citation_unmeasurable`, `eval/run_eval.py`, 2 tests) - a strengthening, not a relaxation |

`eval/results.json` is the **live run on the full corpus** (in-cluster Ollama), not a CI artefact; CI gates against
`eval/baseline.fixture.json` on the 3-document fixture corpus with the stub provider (README, "Evaluation").
