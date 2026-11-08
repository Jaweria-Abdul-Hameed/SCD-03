# docs/FAILURE-ANALYSIS.md - Break one stage at a time (assignment sec. 5.5)

> **Method.** Each break was introduced on purpose, **one at a time**, on the live
> minikube stack (shipped configuration: chunks 512/64, `TOP_K=5`, temperature 0.0,
> `RELEVANCE_FLOOR=0.64`, 480 chunks, `superseded` filter on), and the effect was
> **measured**; the shipped configuration was restored and re-checked after every
> experiment (final state: recall@5 0.833 again, see the last section). All six
> stages of the lecture were broken, not only the required four. Raw output:
> `docs/evidence/live/failure-analysis-measurements.txt`,
> `docs/evidence/live/failure-A-no-ocr.json`, `docs/evidence/live/chunking-experiment/`.
>
> **What was measured and what was reasoned** is stated per break. "Retrieval-only recall"
> means `scripts/recall_probe.py`, which runs the API's own embedding + `retrieve()`
> against the 13 answerable golden questions without calling the LLM (recall@3 / @5,
> relevance defined by text, `scripts/map_golden_to_chunks.py`); it is the same
> retrieval code as the API, not the full `eval/run_eval.py` (generation takes 30-60 s
> per question on CPU Ollama, so a full eval per break was not affordable).
>
> From the RAG lecture: **only F (generation) is the model's fault - check A-E first.**
> The order below is the order to check in.

| Stage | How it was broken | Measured result (shipped -> broken) |
|---|---|---|
| A - Extraction | indexer run on the scanned PDFs with OCR forced off | Faculty policy 11 910 chars / 7 chunks -> **0 chars / 0 chunks** |
| B - Chunking | fixed 100 token chunks, no overlap (100/0) | recall@5 0.833 -> **0.654**; ordinary 0.938 -> **0.562**; chunks 480 -> 1807 |
| C - Retrieval | `TOP_K` 5 -> 1 | recall@5 0.833 -> **0.346** (TOP_K=3: 0.679) |
| D - Prompt | the "use the supplied context ... say so" instruction removed | bus-route question: abstention -> an **invented answer** |
| E - Source | superseded filter removed (`include_old_versions`) | the **superseded** 12-PLO chunk becomes rank 1 (0.888 > 0.875) |
| F - Generation | temperature 1.2 | the same question gives 11 / "PLO-1..PLO-7" / "PLO-10" in three runs |

---

## Break A - Extraction: index the scanned PDF without OCR

- **How.** `scripts/stageA_noocr_probe.py` ran in the indexer image against the corpus PVC
  (a throw-away pod with the same security context) and extracted + chunked the two
  scanned documents twice, once normally and once with `_ocr_page` forced to raise.
  Output: `docs/evidence/live/failure-A-no-ocr.json`.
- **Symptom (measured).**

  | Document | with OCR (shipped) | OCR off |
  |---|---|---|
  | Faculty Entrepreneurship policy (8 pp scanned) | 11 910 chars, 7 chunks | **0 chars, 0 chunks** |
  | Undergraduate Academic Rules Aug 2023 (26 pp) | 34 199 chars, 166 chunks | **214 chars**, 2 chunks (cover text only) |

  The Job still exits 0; the document is simply not in the index.
  (This probe skips the `clean` stage, hence 166 rather than the 147 chunks in the real index.)
- **Effect on the system (reasoned from the above, not run end to end).** G07 ("What does the
  Faculty Entrepreneurship ... Policy cover?") has no chunk to retrieve: its recall would be 0.0
  and the best the system can do is abstain; with OCR the live eval retrieves it at recall 1.0
  and answers from it. Nothing else changes - aggregate recall barely moves, which is why this
  break hides.
- **Diagnosis without causing it.** The indexer logs `extract_done ... "scanned_pages": [...],
  "unrecovered_pages": [...]` for every document and `ocr_applied` per page
  (`docs/evidence/live/indexer-final-run.log`); a document with `chunks: 0` in `index_done.per_document`,
  or `unrecovered_pages` non-empty, is this failure. Metric: per-document chunk count = 0.
- **Stage / remedy.** Extraction. Install `tesseract-ocr` + `poppler-utils` in the indexer
  image (done, `indexer/Dockerfile`), keep the `< 20 characters per page` scan detector, and
  fail loudly (listed under "What could not be recovered" in `docs/PIPELINE.md`).

## Break B - Chunking: fixed 100-token chunks, no overlap

- **How.** Re-index with `--chunk-size 100 --chunk-overlap 0` (Job args), retrieval-only
  recall with the same 13 questions. (The shipped chunker is structure-aware, so 100/0 is the
  nearest honest equivalent of "fixed 100 tokens": sections and clauses are still respected
  where they fit, otherwise cut by size.)
- **Symptom (measured).** `docs/evidence/live/chunking-experiment/recall_probe_c100.json`:

  | | shipped 512/64 | broken 100/0 |
  |---|---|---|
  | chunks | 480 | **1807** |
  | recall@3 / recall@5 | 0.679 / 0.833 | **0.500 / 0.654** |
  | ordinary recall@5 | 0.938 | **0.562** |

  The long Generative AI definition no longer fits in one chunk, so no single chunk contains the
  rule a question asks about (G03 would need to find several partial chunks).
- **Diagnosis without causing it.** `index_done` shows the chunk count and storage amplification
  jump (chunks 480 -> 1807; amplification 1.071 -> 0.991, i.e. nothing is duplicated across a
  boundary any more) and the retrieved chunk texts in the request log start or end mid-sentence.
  Metric: chunk count / amplification in `index_done`, recall@3 falling faster than recall@5.
- **Stage / remedy.** Chunking. Keep a clause whole when it fits (`chunk.py: CLAUSE_START_RE`),
  keep overlap in whole sentences, choose the size by measurement (`docs/PIPELINE.md` table).

## Break C - Retrieval: `top_k: 1`

- **How.** `TOP_K=1` (and `3`) in the environment of the retrieval probe executed inside an api pod
  (`kubectl exec ... env TOP_K=1 python - ...`); the ConfigMap value is read the same way.
- **Symptom (measured).**

  | TOP_K | recall@3 | recall@5 | ordinary | version-sensitive |
  |---|---|---|---|---|
  | 5 (shipped) | 0.679 | 0.833 | 0.938 | 1.00 |
  | 3 | 0.679 | 0.679 | 0.688 | 1.00 |
  | **1** | **0.346** | **0.346** | **0.312** | **0.50** |

  recall@5 can never exceed recall@1 when only one chunk comes back. Citation validity stays 100 %
  (the one citation is a real chunk), so the citation gate does not notice; only recall does.
- **The API-only `EMBED_MODEL` variant** is the guardrail demonstration: changing `EMBED_MODEL`
  in the ConfigMap and restarting only the api left the new pod at `0/1 READY`, with the log
  line `embedding_pin_mismatch` naming both models and `/readyz` 503 naming the conflict
  (`docs/evidence/live/embedding-pin-demo.txt`; ENGINEERING-NOTES Q6). Without the guardrail it
  would have silently retrieved against incomparable vectors.
- **Diagnosis without causing it.** The per-request log line records `top_k` and the retrieved
  `chunk_ids` / `scores` (`"top_k": 5, "chunk_ids": [...]`); `top_k: 1` shows as a one-element list.
  Metric: recall@5 == recall@3 == recall@1 in `eval/results.json` by type.
- **Stage / remedy.** Retrieval. `TOP_K` is a ConfigMap value (`k8s/base/configmap.yaml`); the CI
  gate (recall@5 may not drop more than 5 points below `eval/baseline.json`) turns this into a red build.

## Break D - Prompt: remove the "use the supplied context" instruction

- **How.** `scripts/failure_probe_generation.py` with the first prompt paragraph removed
  ("You answer ONLY from the evidence below. Use the supplied context and nothing else. If the
  evidence does not contain the answer, say so ..."), on the two must-abstain questions,
  temperature 0.0, same retrieved chunks.
- **Symptom (measured, `failure-analysis-measurements.txt`).**

  | Question | shipped prompt | instruction removed |
  |---|---|---|
  | hostel allotment rules | `answer: ""`, answered_from_context false (abstains) | same (still abstains) |
  | bus routes and timings | "The corpus does not cover this question." | **"The university has arranged buses to operate between the campus and designated points in various localities of Faisalabad. The transport facility is available on self-finance basis."** with a citation |

  One of the two must-abstain questions is now answered from unrelated text (a sentence from the retrieved text
  about *whether* buses run, not the routes and timings that were asked for). In production
  this is the "-10 must-abstain answered from context" deduction. The retrieved chunks were
  identical in both runs - only the prompt changed, which is how you recognise stage D.
- **Diagnosis without causing it.** Compare the request log lines of the failing question under
  both prompts: same `chunk_ids` and `scores`, different answer -> not retrieval. Metric:
  abstention correctness < 100 % in `eval/results.json` with unchanged recall.
- **Stage / remedy.** Prompt (`api/app/services/grounding.py: build_augmented_prompt`). The
  instruction is also under test in the gate (`must-abstain` questions).

## Break E - Source: remove the superseded filter, ask a version-sensitive question

- **How.** `include_old_versions=True` (the API's switch for "the user explicitly asks about an
  older version", which removes the `superseded=false` metadata filter) in
  `scripts/failure_probe.py`, on G10 and on the attendance question.
- **Symptom (measured).**

  | Rank | filter ON (shipped) | filter OFF |
  |---|---|---|
  | 1 | EE_PLOs_2024_onwards_11.pdf (0.875) | **EE_PLOs_before_2024_12.pdf (0.888, superseded)** |
  | 2 | EE_PLOs_2024_onwards_11.pdf (0.866) | EE_PLOs_2024_onwards_11.pdf (0.875) |
  | 3 | Annual Report 2023-24 | **EE_PLOs_before_2024_12.pdf (0.869, superseded)** |

  The repealed 12-PLO list is the best match for the question (the two documents are
  near-duplicates), so the retriever "faithfully returns the wrong year". For the attendance
  question 4 of the 5 chunks were the Aug 2023 rules, and the generated answer cited the
  *Undergraduate Academic Rules (2023)* as if it were current. Citation validity is still 100 %
  because the wrong chunk really was retrieved - the failure is invisible to the citation gate.
  (The 12-vs-11 question also made the 3B model abstain once it saw both lists.)
- **Diagnosis without causing it.** The retrieved `chunk_ids` map to `doc_version` /
  `superseded` metadata: a `superseded=true` chunk in the context of a request that did not ask
  about an old version. Metric: a version-sensitive golden question (G09/G10) with recall 0 and
  100 % citation validity.
- **Stage / remedy.** Source/metadata. Filtering in the retriever (`api/app/retrieval/retriever.py`),
  `doc_version` + `superseded` written at index time (`indexer/pipeline/__main__.py`
  `_version_from_filename`); a prompt cannot fix this.

## Break F - Generation: temperature 1.2

- **How.** `scripts/failure_probe_generation.py temp12` (the `Settings` validator rejects 1.2 in
  the ConfigMap - range 0.0-0.3 - so the provider temperature was set in the probe), same chunks.
- **Symptom (measured).** G10 ("How many PLOs does the EE program have?"), three runs at 1.2:
  **"The Electrical Engineering program has a total of 11 PLOs."** / **"PLO-1, PLO-2, ..., PLO-7."**
  / **"PLO-10"**; and `answered_from_context` flips between true and false for the same
  question. At temperature 0.0 the answer is identical on every run (4 runs, "11"; this is why the
  shipped value is 0.0 - `k8s/base/configmap.yaml`).
- **Diagnosis without causing it.** Same question asked twice gives different answers with
  identical retrieved `chunk_ids` in the logs; `cache_hit` ratio falls because answers differ.
  Metric: run-to-run variance of one golden question while retrieval recall is unchanged.
- **Stage / remedy.** Generation: temperature in the ConfigMap, validated to 0.0-0.3. And it does
  **not** fix hallucination: even at 0.0 the 3B model counted PLOs wrongly until the prompt asked
  it to list the items first (ENGINEERING-NOTES Q7).

---

## Summary table - break -> affected metric (measured unless marked)

| Break | Stage | recall@5 | recall@3 | Citation validity | Abstention correctness |
|---|---|---|---|---|---|
| A - scanned PDF without OCR | Extraction | that document's questions: 0 (reasoned from 0 chunks) | same | unchanged | unchanged |
| B - 100/0 chunks | Chunking | **0.833 -> 0.654** (measured) | **0.679 -> 0.500** | not measured (generation not run) | not measured |
| C - `top_k: 1` | Retrieval | **0.833 -> 0.346** (measured) | **0.679 -> 0.346** | unchanged (reasoned: the one citation is real) | not measured |
| D - instruction removed | Prompt | unchanged (same chunks, measured) | unchanged | unchanged | **bus-route question answered -> would fail the 100 % gate** (measured, 2 questions) |
| E - filter removed | Source | version-sensitive: wrong-year chunk is rank 1 (measured) | same | **unchanged (100 %)** - the invisible one | unchanged |
| F - temperature 1.2 | Generation | unchanged (retrieval untouched) | unchanged | not measured | not measured; answers unstable (3 runs, 3 answers) |

## After the experiments: shipped configuration restored and re-verified

The collection was re-indexed with the shipped configuration (512/64) after the B experiment; `TOP_K`
and the temperature were only overridden inside the probe processes (the ConfigMap was never edited
for C, F); the EMBED_MODEL pin demo was reverted (`embedding-pin-demo.txt` ends with
`EMBED_MODEL=nomic-embed-text` and `/readyz` ready). Retrieval-only recall@3/@5 on the restored
index: **0.679 / 0.833** - identical to the committed baseline (`eval/baseline.json`: 0.68 / 0.83);
the full live evaluation was re-run on the final images (`eval/results.json`).

## How to use this file during debugging

1. Reproduce on the golden set, never on one ad-hoc question - the pattern across types is the diagnosis.
2. Read the per-request log line (`request_id`, `top_k`, `chunk_ids`, `scores`, `cache_hit`, `abstention`)
   before touching code: five of the six stages are visible in the retrieved context.
3. Check A -> B -> C -> D -> E in that order. Only then consider F.
4. After the fix re-run `python eval/run_eval.py` and confirm the metric recovers *and* the gate passes.
