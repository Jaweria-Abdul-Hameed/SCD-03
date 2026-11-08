# Final verification, 2026-11-08 (before submission)

Everything below was run on the reference machine against the live minikube stack (api x3, ui x2, chroma, redis,
indexer Job / reindex CronJob, HPA 3-8) in **GPU mode** (host Ollama on the RTX 5060, reached through
`host.minikube.internal`, model `llama3.2:3b`, embeddings `nomic-embed-text`). Where something was not run, it says
"not verified". Raw outputs: `live/reindex-pagefix.txt`, `../../eval/results.json`, `pytest_suite.txt`.

## 1. Automated checks

| Check | Result |
|---|---|
| `pytest api/tests eval indexer/tests` | **154 passed** (api 42, eval 71, indexer 41; the indexer count includes the new page-number regression test) |
| `ruff check` / `ruff format --check` / `mypy api/app indexer/pipeline` | clean (48 files formatted, 27 source files) |
| `python scripts/check_submission.py` | 12/12 PASS |
| `kubectl kustomize` base, dev, prod, incluster-ollama, host-gpu-ollama | all five render; prod overlay passes `kubeconform -strict` (27 resources, 0 invalid) |
| `python eval/run_eval.py --dry-run` on the committed results | GATE PASSED |
| Secret scan (tree and `git log -p --all`) | nothing found (private keys, `ghp_`, `gho_`, `dckr_pat`, AWS keys, password literals) |
| Tracked PDFs | only the assignment PDF and the submission PDF; `corpus/*.pdf` is ignored |
| `scripts/demo-check.ps1` x3 | 10/10 PASS each time |

## 2. Live stack

| Check | Evidence |
|---|---|
| GPU is used | `GET /api/ps`: `size_vram == size` for both models (3 106 270 084 and 323 150 151 bytes); `nvidia-smi` 5 392 / 8 151 MiB used |
| Index complete | 480 chunks, 15 sources, embed model `nomic-embed-text`, dimension 768, no mojibake, 259 chunks `superseded=true` (2023 rules, EE PLOs before 2024, four older annual reports) |
| NetworkPolicy (live, Calico) | `ui -> chroma` times out, `ui -> redis` blocked, `ui -> api` allowed, `api -> chroma` allowed, `api -> internet` blocked |
| Pod deleted under load | 60 requests through the Ingress (4 workers, mixed cached / uncached), one api pod deleted at t=6 s: **0 failures**, max 10.1 s; 3 endpoints again afterwards |
| Rollout | `kubectl set image` -> `rollout status` ok -> `rollout undo` -> `rollout status` ok, original image restored |
| HPA | `cpu: 2%..11%/70%`, 3 replicas (min 3, max 8) |
| `kubectl top pods` | api 2-31 m / 77-95 Mi, chroma 5 m / 122 Mi, redis 3 m / 4 Mi, ui 1 m / 2 Mi |
| Live evaluation, before the re-index | recall@3 0.679, recall@5 0.833, citation validity 12/12, abstention 2/2, gate PASSED (identical to the committed run) |
| Live evaluation, after the re-index | recall@3 0.679, recall@5 0.833, citation validity **13/13**, abstention 2/2, gate PASSED; committed as `eval/results.json` |

## 3. Chatbot, through the UI path (`:3000/api/chat`, and typed into the page)

Each answer was compared with the source text in the database. "Latency" is a fresh generation (`follow_up: true`
bypasses the cache); cached repeats take 0.03-0.06 s. The page renders bullets and bold, strips the model's leading
`>`, lists the citations, and shows the "Not covered by the corpus" banner only for abstentions.

| Question | Answer (short) | Verdict | Latency |
|---|---|---|---|
| Tuition fee per credit hour | Rs. 12,000, Fee Structure page | **correct** | 1.9 s |
| Hostel allotment rules, first year | abstains | **justified abstention** (hostel document excluded on purpose) | 0.7 s |
| How many PLOs does Electrical Engineering have | answers from the current 2024+ document (not the 12-PLO one) but quotes PLO-1..6 or PLO-8..11; never says "11" | **partially correct** (right version, count not stated) | 3.4-4.1 s |
| Same, worded "How many PLOs are there in the current EE program" | before the re-index: `4`; after: a PLO-8..11 quote | **wrong / partial, unstable** | 1.2-3.4 s |
| Which clause states attendance, current version | 100 % attendance, up to 20 % condoned; cites Prospectus 2026 (clause 1 there); does not name Handbook clause 1.21 | **partially correct** | 1.9 s |
| Same with `include_old_versions` | 2023 rules, chunk "1.21 ...", page 7, same rule | **correct** (the clause number is in the citation, not the sentence) | 2.0 s |
| Prompt injection (`docs/DEMO.md` step 6) | not obeyed, abstains | **justified abstention** | 0.8 s |
| Tell me all rules for examination (x3) | 15 bullets, identical in 3 runs; rules 2-13 of the Student Handbook; rule 1 (mobile phones) is missing | **mostly correct, one rule missing** | 5.5-6.2 s |
| Smoking and fine | must pay a fine, repeated cases disciplinary action (p. 10); no amount invented; does not say the amount is unspecified | **correct, could be more explicit** | 1.6 s |
| Caught cheating in an exam | F in the course (8.15), suspension (8.16), expulsion for an extreme act (8.17) | **correct** | 2.3 s |
| Fee refund if I withdraw | only the security deposit rule; omits the tuition refund timeline (100 % to day 10, 80 % to day 15, ...) that is in the same chunk | **partially correct** | 1.5 s |
| Key rules of the Generative AI policy | six generic bullets matching the policy text; page now 42 (was 3) | **correct but generic** | 5.7 s |
| How are grade points assigned | letter grades with points (A+ 4.00 ... F 0.00); before the re-index it hedged and listed no values | **correct** | 3.0 s |
| Who are you / capital of France / "ignore all previous instructions" / bus charges | abstain | **justified abstentions** | 0.04-0.07 s (below the relevance floor, no model call) |
| Hostel fee per semester | "Not mentioned in the evidence" | **justified abstention** | 1.1 s |
| Clause 4.4 (registering after failing) | clause 4.4 (warning/probation: register for all F courses), page 18 | **correct but partial** (the question's premise matches clause 1.20 better) | 2.1 s |
| Minimum CGPA to remain in good standing | abstains although Handbook 5.4 says 2.00 | **false abstention** (known: G12 retrieves the wrong CGPA clause) | 0.9 s |
| Rules on mobile phones in an exam | abstains although the Student Handbook says "Mobile Phones ... are NOT allowed in Examination Hall" | **false abstention** (the rule sits in a chunk that is not in the top 5) | 1.1 s |
| Empty, 2 characters, 600 characters | HTTP 422, never 500 | **correct** | 0.01 s |
| Follow-up "And what about labs?" | abstains (the service keeps no conversation history) | **expected** | 1.0 s |
| Urdu, Roman Urdu, a question with typos | abstain (below the relevance floor) | **honest but unhelpful**: the corpus is English and the floor is strict | 0.04 s |
| "Tell me everything about the university" | a generic Student Handbook summary | **acceptable, vague** | 12.7-15.6 s |

## 4. Problems found

| # | Problem | Root cause | Status |
|---|---|---|---|
| 1 | CI `manifests` job failed on four runs of `dev` | not the repo: every `github.com/.../releases/download` URL (kubeconform, kustomize) answered **HTTP 504 / an HTML body** during the check (reproduced from the laptop for four tarballs); the pipe `curl \| tar` hid it as "not in gzip format" | **fixed** (`f70d617`): kubeconform is taken from its `ghcr.io` image with 5 retries, kustomize is the preinstalled one (already used by `e2e-eval`), the ingress-nginx manifest is downloaded with retry and a sanity check. Prod manifests validated locally with the same image. Not yet run on GitHub Actions |
| 2 | Wrong page numbers in citations: Generative AI policy cited as Handbook page 3 (the cover; it is on 41-43), examination rules as Student Handbook page 9 (they are on 24-26), clause 4.4 text on a chunk labelled 18/20 | `indexer/pipeline/chunk.py:page_for()` returned the **first page that contains the first 60 characters** of the chunk: the running header `NATIONAL UNIVERSITY OF COMPUTER AND EMERGING SCIENCES` and table-of-contents lines match an earlier page, and a needle that crosses a line break never matched. Offline: 16 of 66 (Handbook) and 37 of 88 (Student Handbook) chunks had a suspect page | **fixed** (`7da0b5c`): position-based search, whitespace-normalised, never goes backwards; regression test; suspect pages 16 -> 1 and 37 -> 4 (the rest are chunks that really span pages). Index re-run (`live/reindex-pagefix.txt`): same 480 chunks and chunk ids, amplification 1.071, recall and baseline unchanged, citation pages now correct |
| 3 | `demo-check.ps1` reported "EE PLOs question answers 11" and "cites clause 1.21" although the answer text said neither | the regexes ran over the whole JSON, including the model's `reasoning` and `PLO-11` labels | **fixed**: the checks now look at the citations (current document, not the superseded one) and print a `[NOTE]` for what the 3B model still does not state |
| 4 | 38 chunks of the superseded 2023 rules contain only a clause number (`2.6`, `3.5`, ...) | the 2023 PDF is scanned and OCR separates the number from its text | **not fixed**: superseded document (excluded from default retrieval), fixing needs a chunker/OCR change and a re-index; documented |
| 5 | Some answers are weak: PLO count, "which clause", refund timeline, CGPA and mobile-phone false abstentions, typos | 3B model terseness and the recall@5 limit on exact-term questions (known, measured: exact-term recall@5 0.50) | **not fixed**. A prompt change asking for "the number first" was tried and **reverted**: it made the 3B model answer "There are 4 PLOs" (it counted the visible items), so it is worse than before. A change that moves a citation to the best-supporting chunk was also tried and reverted: it did not fix the case it targeted and moved the old-version answer to the Prospectus. No gate was touched |
| 6 | The "all rules for examination" answer from the old index ended in a stray `\` | the model's last JSON string; the answer is not truncated after the re-index (15 bullets) | **not reproduced** after the re-index |

## 5. Not verified

* The new `ci.yml` / `cd.yml` steps have not run on GitHub Actions (nothing was pushed). They parse as YAML, keep the
  `needs:` chains, and the kubeconform image path was run locally.
* A fresh clone with `minikube delete` was not tried (not allowed here); `scripts/rebuild-from-scratch.ps1` was not run.
* `docker pull` of the Docker Hub images was not run; the three tags for the CD commit
  (`a3c4391097a8387c986173bbd4386ba96ab82718`) exist according to the Docker Hub API (HTTP 200, pushed 2026-11-08 07:26-07:28 UTC).
* Screenshots were not retaken; the three PR #2 screenshots are in `screenshots/`.
