# docs/PIPELINE.md — Indexing pipeline (assignment sec. 3.1)

Stages: **extract → clean → chunk → embed → store**.
Code: `indexer/pipeline/{extract,clean,chunk,embed,store}.py`;
entrypoint: `python -m pipeline` (Job image `indexer/Dockerfile`).
The indexer is the **only** writer to ChromaDB; the API only reads
(assignment sec. 4.2 — indexing never runs at API startup).

Shared constants (must match the `rahbar` ConfigMap and the API):
`EMBED_MODEL=nomic-embed-text`, dimension **768**, Chroma collection
`rahbar_corpus` on `chroma:8000`, Redis `redis:6379` (cache invalidation
only), LLM `llama3.2:3b`, shipped chunk config **(512, 64)**.

---

## 1. Extract — PDF to text (`indexer/pipeline/extract.py`)

* Text layer first via PyMuPDF (`fitz`), falling back to `pypdf`.
* **Automatic image-only detection:** a page is scanned when it yields
  **< 20 extractable characters OR no fonts** (empty font list = scan).
  Scanned pages go to the OCR fallback (`pytesseract` + `pdf2image` /
  poppler, both installed in the indexer image).
* A page that cannot be OCR-recovered is **never dropped silently and
  never crashes the Job**: it is kept with empty text, a warning naming
  the page is logged, and the loss is listed under "What could not be
  recovered" below.
* Repeating headers/footers (a line on **> 80% of pages**) are stripped;
  numbered clauses (`1.21`, `4.2`) and headings are never treated as
  headers/footers.

### Which documents needed OCR

| Document | OCR? | Evidence / status |
|---|---|---|
| Faculty Entrepreneurship and Technical Start-ups Policy | **Yes — confirmed scanned** | Verified 2026-11-05 (docs/CORPUS.md): 8 pp, `pdffonts` returns an empty font list and `pdftotext` extracts only **8 characters from 8 pages**. OCR is mandatory for this document. |
| Undergraduate Academic Rules, Aug 2023 | **Yes — near-textless, needs OCR too** | Verified 2026-11-05: 26 pp, `pdftotext` returns only **~243 characters** for the whole document (cover + final contact page). Effectively a second scanned document. |
| Academic Rules Handbook, Jun 2026 (**58 pp**, not ~53) | No (text layer) | Numbered clauses extract directly. |
| Student Handbook, Jun 2026 (**64 pp**, not ~60) | No (text layer) | Long Generative AI policy (§XII, p. 40) extracts directly. |
| Prospectus 2026 rules (5 pp), Annual Reports 2019-20…2023-24, Fee Structure & Grading pages | No (text / HTML tables) | Tables are the risk here, not OCR — see below. |

> Status (measured 2026-11-07/08, final index run `efcfe397`): the corpus
> is **15 documents, 390 pages** (12 PDFs + 3 HTML pages; `corpus/raw/`,
> 38 MB, SHA-256 in `corpus/MANIFEST.md`). The OCR log lines of that run
> (`docs/evidence/live/indexer-final-run.log`, event `ocr_applied`) give the
> **actual** OCR list: 41 pages in 4 documents, **0 unrecovered pages**:
>
> | Document | Pages OCR'd | Why |
> |---|---|---|
> | Faculty Entrepreneurship policy | **all 8 of 8** | fully scanned (no text layer) |
> | Undergraduate Academic Rules Aug 2023 | **24 of 26** (pp 2-25) | scanned body; only cover/last page have text |
> | Academic Rules Handbook Jun 2026 | 5 of 58 (pp 1, 2, 56-58) | image-only cover/closing pages |
> | Student Handbook Jun 2026 | 4 of 64 (pp 1, 2, 63, 64) | image-only cover/closing pages |

### Before / after: a mangled table (failure mode A)

Real example from the fetched **Fee Structure page** (`Fee_Structure_page.html`),
the refund-timeline table. Two failures were measured, in order:

1. **Before HTML support the page was not indexed at all.** The first full
   index run ingested `*.pdf` only: **12 documents / 473 chunks**
   (`docs/evidence/live/kubectl-top-during-index-run1.txt`); the Fee, Grading and
   Calendar pages (tuition per credit hour, refund percentages, grade points)
   simply did not exist for retrieval. Every golden question about them
   would have been unanswerable.
2. **Naive tag stripping jumbles the columns.** Removing HTML tags and
   collapsing whitespace gives one run-on line in which the row/column
   structure is gone:

```
BEFORE (naive tag strip of the refund table):
Timeline Percentage of Fee Upto 10th day of commencement of classes 100% Fee Refund
Upto 15th day of commencement of classes 80% Fee Refund Upto 20th day of commencement
of classes 60% Fee Refund Upto 30th day of commencement of classes 50% Fee Refund ...
```

```
AFTER (indexer/pipeline/extract.py: _HtmlText -> one [TABLE] block, kept atomic by chunk.py):
[TABLE]
Timeline | Percentage of Fee
Upto 10th day of commencement of classes | 100% Fee Refund
Upto 15th day of commencement of classes | 80% Fee Refund
Upto 20th day of commencement of classes | 60% Fee Refund
Upto 30th day of commencement of classes | 50% Fee Refund
31st day onwards of commencement of classes | No Refund
[/TABLE]
```

A second bug in the same extractor was found only because the chunk counts
looked wrong: the first HTML version joined blocks with single newlines, so
`chunk.py` saw the whole page as **one paragraph containing a table** and kept
it atomic - every web page became one 900-1200-token chunk. Blocks are now
blank-line separated (`extract_html`, regression test
`test_html_page_is_split_into_paragraphs_not_one_table_blob`); Fee page: 1 -> 3
chunks, Grading: 1 -> 3, with each `[TABLE]` still whole.

### What could not be recovered

* **No page was unrecoverable**: all 41 scanned pages produced OCR text
  (`unrecovered_pages: []` for every document in the final run).
* **OCR quality is not text quality.** The OCR text of the Faculty policy contains
  recognisable noise (`lel. ese Late. 12.3. 1.2.4. Ban 4.2.` where the numbered
  list of the Purpose section was), signatures and form fields come out as
  fragments (`Uo A`, `Beal`), and the Aug 2023 rules produce **147 tiny chunks**
  (about 58 tokens each) because every OCR'd numbered line is detected as a
  section heading. These chunks are `superseded=true`, so they are filtered out of
  normal retrieval, but they would be poor evidence if someone asked about the 2023
  rules.
* **Scanned table grids** cannot be recovered from an image: they come back as
  lines, not as a grid (the Faculty policy's annex forms are the example).
* HTML pages: the section title of every chunk is `Introduction` because heading
  tags are not (yet) turned into section headings; page citations for these are
  always page 1.

---

## 2. Clean — artefacts out, structure kept (`indexer/pipeline/clean.py`)

Rules applied (also returned by `clean.cleaning_rules()`):

1. Page numbers — drop lines that are only a page number (`12`,
   `Page 12`, `12 of 53`).
2. Headers/footers — drop lines repeated on > 80% of pages (extract
   stage) plus a same-position repeat pass in `clean_document`.
3. Hyphenation — rejoin words split by a hyphen at a line break
   (`regis-\ntration` → `registration`).
4. Whitespace — collapse 3+ blank lines to one, runs of spaces/tabs
   to one, strip trailing spaces; join single newlines inside a
   paragraph, keep blank-line paragraph breaks.
5. Control characters — remove C0 controls except tab/newline.
6. Tables — mark runs of `|` / multi-column lines as
   `[TABLE]` … `[/TABLE]` and keep their line breaks verbatim.

**Deliberately NOT stripped:** clause numbers and section headings
(e.g. `4.2`, `1.21`, `Clause 4.2`) and table delimiters (`|`, column
spacing) inside `[TABLE]` blocks. Reason: they are the retrieval and
citation anchors — the golden set asks for exact clause numbers
(G11), the `section` citation field depends on them, and the
`doc_version` / `superseded` filter depends on knowing which clause
came from which version. Stripping them would destroy groundedness,
not noise.

---

## 3. Chunk — structure-aware (`indexer/pipeline/chunk.py`)

Order: **sections → paragraphs → sentences**. A numbered clause /
long definition that fits in the target size whole is **never split**
across chunks (property 5, failure mode B). Overlap is **whole
sentences only**. Token estimate: **~1 token per 4 characters**
(documented approximation — the same ruler for every config, so the
comparison below is apples-to-apples).

### Chunking experiment - recall on the golden set (measured on the live stack)

Four configurations were indexed one after another on the **real corpus** with the
**real `nomic-embed-text`** (live minikube, in-cluster Ollama), everything else
identical (same extractor, same 13 answerable golden questions). Because chunk ids
are `sha256(source|section|chunk_index)` they change with every configuration, so
relevance is defined by **text**: `scripts/map_golden_to_chunks.py` holds one
verbatim answer-bearing quote per question and resolves it to the chunk ids that
contain it in the *current* collection. `scripts/recall_probe.py` then runs the
API's own embedding + `retrieve()` for every question (no LLM generation) and
computes recall@3/@5. Raw output: `docs/evidence/live/chunking-experiment/`.

| (size, overlap) | chunks | storage amplification | recall@3 | **recall@5** | ordinary r@5 (8) | version-sens. r@5 (2) | exact-term r@5 (2) | injection r@5 (1) |
|---|---|---|---|---|---|---|---|---|
| (100, 0) - fixed-size-like | 1807 | 0.991 | 0.500 | 0.654 | 0.562 | 1.000 | 1.000 | 0.000 |
| (256, 32) | 821 | 1.042 | 0.500 | 0.577 | 0.625 | 0.750 | 0.500 | 0.000 |
| **(512, 64) - SHIPPED** | **480** | **1.071** | **0.679** | **0.833** | **0.938** | **1.000** | 0.500 | 0.333 |
| (1024, 128) | 319 | 1.088 | 0.538 | 0.654 | 0.812 | 0.500 | 0.500 | 0.000 |

Read it with care: 13 questions, so one question moves recall@5 by 4-8 points, and
the exact-term and injection rows are 2 and 1 questions. The ordering of the
overall column is the finding, not the third decimal.

**Why (512, 64) ships** (measured, not assumed):

* It has the best recall@5 (0.833 vs 0.577-0.654), the best recall@3, and the best
  ordinary-question recall (0.938) - those are the long-definition and table
  questions that property 5 exists for (Generative AI policy, Handbook clauses).
* **100 / 0 is the "fixed 100-token chunks, no overlap" break of the assignment**
  (stage B): 3.8x the chunks, no overlap (amplification 0.991) and clauses split over
  several chunks; ordinary recall falls from 0.938 to 0.562. Its exact-term score
  (1.000) is the one place it wins: a 100-token chunk is almost all clause number,
  which is the lexical-signal argument for hybrid retrieval, not for small chunks.
* **256 / 32** doubles the chunk count for a *lower* recall: the long Generative AI
  definition no longer fits in one chunk.
* **1024 / 128** has the fewest chunks, but each vector averages more topics
  (version-sensitive recall falls to 0.500 because the 12-PLO and 11-PLO lists are
  retrieved with neighbouring text) **and it stresses the embedder**: the
  `len(text)//4` token estimate under-counts number-dense annual-report tables, and
  Ollama rejected a chunk with HTTP 500 `input length exceeds the context length`
  (2118 real tokens vs the 2048-token limit). `indexer/pipeline/embed.py` now
  retries on a shorter prefix and logs `embed_input_truncated` - it fired once in
  this run and 0 times at the other sizes.
* Indexing time was the same for all (236-272 s) once Ollama's thread count was
  pinned (`OLLAMA_NUM_THREAD`; ENGINEERING-NOTES Q7), so cost did not decide it.

The end-to-end evaluation (with generation, `eval/results.json`) was run on the
shipped (512, 64) index only - generation takes 30-60 s per question on CPU Ollama,
so the three alternative indexes were compared on retrieval alone.

### Storage amplification

`stored_tokens / original_tokens`. Lecture example: **150 / 120 = 1.25**.
Shipped configuration on the full corpus: **164 969 / 153 996 = 1.071** (480 chunks,
15 documents; per-document values 0.99-1.10 in `docs/evidence/live/index_done.txt`).
Overlap is the cost: every overlapped sentence is stored twice. The ruler is the
same `len//4` estimate on both sides, so the ratio is comparable even though the
absolute token numbers are approximate.

---

## 4. Embed — one vector per chunk, pinned model (`indexer/pipeline/embed.py`)

* **Model: `nomic-embed-text`, dimension: 768.**
* The model is read from env `EMBED_MODEL` (default
  `nomic-embed-text`) and called at
  `POST http://{OLLAMA_HOST}/api/embeddings` (`OLLAMA_HOST` default
  `host.minikube.internal:11434`, ollama-host mode).
* **Pin enforcement in code:** every returned vector is checked —
  `len(embedding) != 768` raises `ValueError` and the Job fails
  loudly (`embed.py: _embed_one`). There is **no silent fallback to
  another model**: retries cover transient network/5xx errors only;
  a dimension/model mismatch is never retried.
* **Task prefixes + document header (measured fix):** `nomic-embed-text` is trained
  with `search_document: ` / `search_query: ` prefixes. Indexed text is embedded as
  `search_document: Document: <title>. Section: <section>.` + newline + chunk (the
  *stored* chunk text is unchanged: `embed.py: document_text`) and the API embeds
  `search_query: <question>` (`services/chat.py: query_text`). Before this change
  "How many PLOs does the Electrical Engineering program have?" retrieved an
  Annual Report chunk (the bare PLO list never says "Electrical Engineering")
  and the system answered "10".
* Inputs above the embedder's 2048-token context are embedded on a shorter prefix
  instead of failing the Job (`embed_input_truncated` log line).
* **Where the pin lives (three places, one truth):**
  1. the `rahbar` **ConfigMap** (`EMBED_MODEL`, read by indexer and API);
  2. `embed.py: PINNED_MODEL / PINNED_DIMENSION` (defaults matching it);
  3. the **Chroma collection metadata** written by `store.py`
     (`model_name`, `embed_model`, `embedding_dimension`) — the API
     compares this at readiness and refuses to become ready on
     mismatch (assignment sec. 4.4).

---

## 5. Store — ChromaDB (`indexer/pipeline/store.py`)

* Client: `chromadb.HttpClient` to `CHROMA_HOST:CHROMA_PORT`
  (default `chroma:8000`); collection **`rahbar_corpus`**.
* On creation the collection is written **with** the pin metadata
  `{"model_name": "nomic-embed-text", "embed_model": "nomic-embed-text",
  "embedding_dimension": 768}` (`store.py: get_or_create_collection`).
  A pre-existing collection whose pin disagrees raises a hard error —
  vectors from different models are never mixed.
* Chunk ids are stable: `sha256(source + section + chunk_index)`, so
  re-running the Job **upserts** (idempotent re-index, no duplicates).
* **Cache invalidation:** on successful index completion the Redis
  semantic cache is flushed (`rahbar:cache:*`). If Redis is
  unreachable the Job logs a warning and still succeeds — it never
  crashes on cache failure (a stale cache is bad; no index is worse).

### Metadata schema (graded — every chunk carries all five)

| Field | Type | Example |
|---|---|---|
| `source` | str | `Academic_Rules_Handbook_2026.pdf` |
| `section` | str (<= 80 chars) | `1.9 A theory course is normally assigned 2 to 4 credit hours, depending on its...` |
| `page` | int | `8` |
| `doc_version` | str | `2026-06` (current), `2023-08`, `pre-2024`, `2024+`, `2019-20`... |
| `superseded` | bool | `false` (current) / `true` (Aug 2023 rules, EE PLOs before 2024, Annual Reports before 2023-24) |

Enforcement: `store.validate_metadata()` rejects any chunk missing a
field, with a non-`int` page, or with a non-`bool` `superseded`
(string `"false"` included), **before any write**. Superseded rule:
the Aug 2023 Undergraduate Academic Rules (`doc_version="2023-08"`)
get `superseded=true`; the Jun 2026 Handbook (`"2026-06"`) gets
`superseded=false` (`store.superseded_for()`; the orchestrator also
derives it from the filename). Retrieval filters out
`superseded: true` by default — metadata filtering, not a prompt,
fixes failure mode E.

### Chunk count (full corpus, shipped configuration)

**480 chunks from 15 documents** (index run `efcfe397`, 236 s, storage amplification
1.071). Per document: Annual Report 2023-24 111, Student Handbook 43, Academic Rules
Handbook 39, Annual Reports 2019-20..2022-23 26/26/27/31, Prospectus rules 12,
Faculty policy 7, Fee page 3, Grading page 3, EE PLOs 2+2, Calendar page 1, and
**147** for the Aug 2023 rules (OCR noise, see "What could not be recovered").
Collection metadata: `{'model_name': 'nomic-embed-text', 'embed_model': 'nomic-embed-text',
'dimension': 768, 'embedding_dimension': 768, 'hnsw:space': 'cosine'}`. All 480 chunks
carry `source`, `section`, `page`, `doc_version`, `superseded` (checked: 0 missing).
Version flags: Aug 2023 rules, EE PLOs before 2024 and the four Annual Reports before
2023-24 are `superseded=true`; everything else `false`.

---

## 6. Running it

```bash
# Local (Ollama on the laptop, Chroma/Redis reachable):
python -m pipeline --corpus-dir corpus/raw --chunk-size 512 --chunk-overlap 64

# In-cluster (the Job / weekly CronJob does exactly this):
kubectl create job --from=cronjob/reindex manual-reindex-1 -n rahbar
kubectl logs -n rahbar job/manual-reindex-1   # JSON lines, run_id per run
```

Exit codes: `0` = indexed, `2` = no input documents found,
`1` = a stage failed. Tests: `python -m pytest
indexer/tests/test_pipeline.py -v` (41 tests, mocked Ollama/Chroma/
Redis - no network or model needed).
