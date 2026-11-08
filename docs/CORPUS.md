# docs/CORPUS.md — RAHBAR corpus

> Status: **COMPLETE, verified live 2026-11-05 and against the final index 2026-11-08** (section at the end).
> Corpus: **FAST-NUCES public site (nu.edu.pk)** — the assignment's own
> ready-made source (sec. 2), checked by the assignment on 2026-11-01 and
> re-checked by us on 2026-11-05. Commit `corpus/MANIFEST.md` + the fetch
> script — **never the PDFs themselves** (the repo may be public).
>
> First-PR rule (assignment sec. 2): name this corpus in your **first pull
> request** so a weak choice gets corrected early. Name: **FAST-NUCES
> public-site corpus**.
>
> Shared constants: namespace `rahbar`; EMBED_MODEL `nomic-embed-text`
> (768 dims); LLM `llama3.2:3b` via ollama-host.

## Why this corpus

It is the only option documented to cover all seven properties — and
property 2 (a *genuine* version pair) is called out as the most common weak
choice. We verified every document below by actually downloading it on
2026-11-05; the verification log is at the bottom of this file. Nothing in
the tables below is taken on trust from the assignment text alone — where
the live site disagreed with the assignment's shorthand, the live site wins
and the difference is flagged (see the ⚠️ notes).

## The seven properties

| # | Required property | Document(s) chosen | Pages | Failure mode it makes reachable (assignment sec. 2) | Verification status |
|---|---|---|---|---|---|
| 1 | ≥6 documents, ≥40 pages total, all public or your own | 15 documents (12 PDFs + 3 HTML pages) — see `corpus/MANIFEST.md` | **390** | None; this sets the scale | ✅ Verified 2026-11-05: every file downloaded, SHA-256 recorded, pages counted with `pdfinfo` |
| 2 | ≥2 documents = different versions of the same policy | **Undergraduate Academic Rules, Aug 2023** (26 pp, superseded) vs **Academic Rules Handbook, Jun 2026** (58 pp, current); second pair: **Prospectus 2026 rules** (5 pp) vs the same Handbook; third pair: **Annual Reports 2019-20…2023-24** (5 editions); fourth pair: **EE PLOs 12 (pre-2024) vs 11 (2024 onwards)** | 26 + 58 + 5 + 223 + 3 | **E, outdated source:** the retriever faithfully returns the wrong year | ✅ Verified: all versions downloaded; hashes in MANIFEST.md. ⚠️ The Aug 2023 body is near-textless (see below) — it needs OCR too |
| 3 | ≥1 scanned, image-only PDF (no text layer) | **Faculty Entrepreneurship and Technical Start-ups Policy** (ORIC, `27.pdf`, 8 pp) | 8 | **A, bad extraction:** OCR it, or document the loss honestly | ✅ **Confirmed scanned:** `pdffonts` returns an empty font list and `pdftotext` extracts **8 characters from 8 pages**. OCR is mandatory for this document |
| 4 | ≥1 document with a table carrying real information | **Fee Structure page** (tuition/credit-hour, misc fees, refund timeline) + **Grading page** (grade-points tables) + **Annual Reports** (faculty-by-campus, graduates, publications tables) | 1 + 1 + 223 | **A, bad extraction:** table columns come out jumbled | ✅ Verified: fee table (Rs. 12,000/credit-hour, refund 100/80/60/50/0%) and grading tables (A+ 4.00 … D 1.00) read live from the HTML pages on 2026-11-05 |
| 5 | ≥1 document with long definitions a fixed-size chunker would cut in half | **Student Handbook, Jun 2026** — section XII, *Policy on Generative AI Based Tools* (p. 40), long numbered sub-sections | 64 | **B, poor chunks** | ✅ Verified: 64 pages; Generative AI policy confirmed in the table of contents (p. 40) and body text |
| 6 | ≥1 realistic topic deliberately absent | **Transport/hostel rules** — the prospectus's *Transport and Hostel Facilities* PDF is **excluded on purpose** (see below) | — (absent) | **Abstention (sec. 3.4)** | ✅ Verified excluded: the file is listed in `EXCLUDED` in `scripts/fetch_corpus.py`, is not in MANIFEST.md, and the fetch script never downloads it |
| 7 | Exact-term content: a course code, a clause number, a CGPA threshold, a fee | Clause **1 / 1.21** (attendance), clause **4.2** (registration procedure — see ⚠️), clauses **5.8 / 5.10** (failed-course rules), **CGPA ≥ 2.00**, **tuition Rs. 12,000 per credit hour**, **12 vs 11 PLOs** | — | **Embeddings blur exact terms** → motivates hybrid retrieval | ✅ Verified for clause numbers, CGPA and fees (inventory below). ⚠️ Course codes: **not yet verified** in the fetched core documents — see inventory |

## The version-pair traps (use in the golden set)

These are the real-world outdated-source cases failure mode E describes.
All four were confirmed live on 2026-11-05:

1. **Attendance clause renumbering — clause 1 vs 1.21.** The Prospectus
   2026 *Academic Rules and Regulations* (5 pp) states the attendance rule
   as **clause 1**; the Academic Rules Handbook Jun 2026 states the same
   rule as **clause 1.21**. The rule itself agrees (100% attendance
   required, max 20% condoned for genuine reasons; minimum 80% for
   undergraduate, 75% for graduate/postgraduate programmes; failure renders
   a student ineligible for the final exam). A retriever that cites the
   clause number without the document version cites the wrong clause.
   Golden questions: G02 (ordinary), G09 (version-sensitive).
2. **EE learning outcomes — 12 PLOs vs 11 PLOs.** IQAE Downloads lists
   both: *"For Batches before 2024 — 12 PLOs with statements"* (Drive id
   `1yZo--h0fZN9lqRapQbUxkYBqm-7AeL3V`, 2 pp) and *"For Batches 2024 &
   onwards — 11 PLOs with statements"* (Drive id
   `1VBkr5aHcgOHmlzAtjpn_GjQZNCXjcSLF`, 1 p). Both downloaded and hashed.
   The correct answer to "how many PLOs?" is **11** (current). Golden
   question: G10.
3. **Academic Calendar — 2026-27 schedule beside a 2023-24 holidays table.**
   The Academic Calendar page (`/Student/Calender` — the site's spelling)
   shows the *Tentative Academic Schedule for year 2026-2027* (Fall 2026
   registration Aug 10–14, classes from Aug 17; Spring 2027 registration
   Jan 12–16) directly beside a holidays table headed *"Expected Holidays
   during the year 2023-24"* (Kashmir Day Feb 5, Pakistan Day Mar 23,
   Eid-ul-Fitr Apr 10–12, …). A retriever that ignores the heading date
   answers holiday questions from a three-year-old table. Golden
   question: G08.
4. **Prospectus 2025 vs 2026.** The Downloads page lists item 6 as
   *"Prospectus 2025 (Aug-2025)"* while the prospectus page itself is
   headed *Prospectus 2026*. The 2026 prospectus PDFs (e.g. *Front
   Pages_2026.pdf*) are the current ones. ⚠️ **Unverified:** the Prospectus
   2025 PDF itself was not downloaded — only its listing was confirmed.
   Do not cite a 2025 prospectus figure without fetching it first.
5. **The Aug 2023 trap — and what actually happened.** The assignment
   says the old-rules link "would not open when checked" on 2026-11-01.
   On 2026-11-05 it **did** download — from the Bachelor rules page
   (`https://nu.edu.pk/Student/RulesUndergrad`, link text "open new tab")
   as plain `http://nu.edu.pk/public/downloads/Academic-Rules-Undergrad-Aug-2023.pdf`
   (14.9 MB, 26 pp, SHA-256 in MANIFEST.md). The fetch script tries the
   `https://` variant as a fallback and, if both fail, logs a clear warning
   and continues with the Prospectus 2026 rules as version-pair evidence
   instead of crashing. **But:** the Aug 2023 body is near-textless —
   `pdftotext` returns only ~243 characters for 26 pages (cover + a final
   contact page). It is effectively a **second scanned document**: the
   indexer must OCR it, and its clause numbers cannot be verified from
   text extraction until OCR runs. Do not quote an Aug 2023 clause number
   from memory.

## The absent topic (property 6) — what is excluded and why

**Excluded document:** *Transport and Hostel Facilities* (Prospectus 2026),
`https://nu.edu.pk/Admissions/ProspectusUpload/Transport and Hostel Facilities.pdf`
— linked from the Prospectus index page, **deliberately never downloaded**.

The Student Handbook only says hostels exist (an "In-Campus Hostel"
facilities line) — it gives no allotment rules, no bus routes, no timings.
So these questions have **no answer in the corpus** and must abstain:

- "What are the hostel allotment rules for first-year students?" (G13)
- "Which bus routes serve the campus, and what are their timings?" (G14)

Expected behaviour: `answered_from_context: false`. Abstention correctness
must be 100% (assignment sec. 5.3). The exclusion lives in code
(`EXCLUDED` in `scripts/fetch_corpus.py`) and in `corpus/MANIFEST.md`, so
a future re-fetch cannot silently re-add the topic. **If anyone removes
this exclusion, G13/G14 become answerable and the abstention evaluation
becomes meaningless — do not do it.**

## Exact-term inventory (property 7)

Verified live from the fetched copies on 2026-11-05. Record the value from
*your* fetched copy — never from memory — before writing golden answers.

| Exact term | Value (verified) | Where |
|---|---|---|
| Attendance clause | **1** (Prospectus 2026) vs **1.21** (Handbook Jun 2026) | Prospectus rules p. 1; Handbook §1.21 |
| Attendance minimum | **80%** undergraduate, **75%** graduate/postgraduate; 100% required, max **20%** condoned | Both documents |
| Registration procedure | Clause **4.2** (Handbook Jun 2026) | Handbook §4.2 |
| Failed-course rule | Clause **5.8**: a failed/missed course "should become mandatory in the subsequent semester (if Offered)"; clause **5.10**: repeating a course whose post-requisite was passed needs a written undertaking (fail → post-requisite grades become F); clause **4.4**: students under academic warning must re-register failed (F) courses | Handbook §§4.4, 5.8, 5.10 |
| Minimum CGPA | **CGPA 2.00** — "Minimum Cumulative Grade Point Average (CGPA) of 2.00"; warning count resets to zero if CGPA ≥ 2.00 after 1st/2nd warning | Handbook §§5.7 and academic-standing section |
| Tuition fee | **Rs. 12,000 per credit hour** for BBA/BS, MBA/MS and PhD (academic year 2026-27, w.e.f. Fall 2026) | Fee Structure page |
| Other fees | Admission **Rs. 30,000** (once); refundable security deposit **Rs. 20,000**; Student Activities Fund **Rs. 2,500/semester**; misc. fees Rs. 300–5,000 (transcript 300, campus transfer 5,000, recheck 500, …) | Fee Structure page |
| Fee refund timeline | **100%** to 10th day of classes; **80%** to 15th; **60%** to 20th; **50%** to 30th; **no refund** from 31st day onwards | Fee Structure page |
| Grade points | **A+ 4.00, A 4.00, A− 3.67, B+ 3.33, B 3.00, B− 2.67, C+ 2.33, C 2.00, C− 1.67, D+ 1.33, D 1.00** (BBA/BS scale); grade "I" converts to "F" before the end of the next semester; "S"/"U" for PhD thesis only, excluded from CGPA | Grading page |
| EE PLOs | **12** (batches before 2024) vs **11** (batches 2024 onwards) | IQAE Downloads (Drive) |
| Course codes | **Decision (final, 2026-11-08): the corpus contains no verified course code and the golden set contains no course-code question.** Programme/course codes live in the prospectus programme PDFs (*Computing Programs*, *Engineering Programs*), which were not added. The exact-term property is covered by clause numbers (G11: clause 4.4), the CGPA threshold (G12: 2.00, clause 5.4) and the fee amounts (G04: Rs. 12,000) - three of the four example kinds in the assignment. No code was invented. | — |

> ⚠️ **Correction to the assignment's shorthand — read this before writing
> golden questions.** The assignment's case study says the answer to "can a
> student register after failing a prerequisite?" is "in clause 4.2". In the
> **fetched Jun 2026 Handbook, clause 4.2 is the recommended course
> registration procedure** (clear dues → register online → pay by due date).
> The failed-course substance is in **§§4.4, 5.8 and 5.10** (see the table
> above). AGENT_EVAL should reword golden questions G01/G11 to cite the
> clauses as actually numbered in the fetched copy, or to ask about
> registration after a failed course generally — do not keep citing "clause
> 4.2" for the failed-prerequisite rule, or the golden set will assert a
> clause number the document does not support.

## Fetch instructions

```bash
# Full fetch (downloads to corpus/raw/, writes corpus/MANIFEST.md):
python3 scripts/fetch_corpus.py

# Inspect first — lists every URL + expected SHA-256, downloads nothing:
python3 scripts/fetch_corpus.py --dry-run

# Re-verify hashes after a re-fetch, or be extra polite:
python3 scripts/fetch_corpus.py --delay 2
```

How the script works (assignment sec. 2):

- **No API/sitemap:** it reads the four index pages — Downloads
  (`/Downloads`), Prospectus (`/Admissions/Prospectus`), ORIC Policies
  (`/Oric/Policies`), IQAE Downloads (`/IQAE/Downloads`) — plus the
  Fee Structure, Grading, Academic Calendar and Undergraduate Rules pages.
  ⚠️ The short paths do **not** work: `/prospectus`, `/fee-structure` and
  `/academic-calendar` all return **404** (checked 2026-11-05); use the
  real routes above.
- **URL-encoding:** several file names contain spaces (e.g. `Annual Report
  2023-24.pdf`, `Academic Rules and Regulations.pdf`); the script encodes
  path segments before requesting.
- **Google Drive:** `/file/d/<ID>/view` links (most IQAE documents) are
  converted to `https://drive.google.com/uc?export=download&id=<ID>`
  (works for small files — both EE PLO documents downloaded this way).
- **Polite:** 1 second between requests (configurable with `--delay`),
  3 retries with exponential back-off, 60 s timeout, a descriptive
  User-Agent.
- **Public pages only** — never SLATE, Flex, NU Mail, `admissions.nu.edu.pk`
  or anything behind a login. The script refuses URLs matching those
  patterns.
- **Not acceptable** (and not used): course lecture slides, LLM-generated
  corpora, paywalled or private material.

## Verification log (2026-11-05, AGENT_CORPUS)

Every line below was established by a live request/download from this VM,
not from the assignment text:

| Check | Result |
|---|---|
| Index pages return 200 | Downloads, Prospectus, ORIC Policies, IQAE Downloads, Fee Structure, Grading, Academic Calendar (`/Student/Calender`), Undergraduate Rules page (`/Student/RulesUndergrad`) — all HTTP 200 |
| Short paths return 404 | `/prospectus`, `/fee-structure`, `/academic-calendar`, `/fee` — all 404; `/Admissions` returns 403 |
| Academic Rules Handbook Jun 2026 | Downloaded, 58 pp (assignment said ~53 — actual is 58), SHA-256 in MANIFEST.md |
| Undergraduate Academic Rules Aug 2023 | Downloaded via `http://` from the Bachelor rules page, 26 pp, 14.9 MB; body near-textless (~243 chars extracted) — needs OCR |
| Prospectus 2026 rules | Downloaded, 5 pp; attendance = clause 1, 80%/75% minima confirmed in text |
| Student Handbook Jun 2026 | Downloaded, 64 pp (assignment said ~60 — actual is 64); Generative AI policy §XII p. 40 confirmed |
| Faculty Entrepreneurship policy | Downloaded, 8 pp; `pdffonts` empty, `pdftotext` 8 chars — **confirmed scanned** |
| Annual Reports 2019-20…2023-24 | All 5 downloaded: 33, 33, 36, 36, 85 pp |
| EE PLOs (Drive) | Both downloaded via `uc?export=download`: 11 PLOs (1 p) and 12 PLOs (2 pp); PLO-1…PLO-4 text confirmed |
| Fee Structure page | Read live: tuition Rs. 12,000/credit-hour, refund timeline, all misc fees (see inventory) |
| Grading page | Read live: full grade-points tables, SGPA/CGPA definitions, I→F rule |
| Academic Calendar page | Read live: 2026-2027 schedule + holidays table headed "Expected Holidays during the year 2023-24" |
| Downloads page lists "Prospectus 2025 (Aug-2025)" | Confirmed in the page text; the 2025 PDF itself was **not** downloaded — unverified, do not cite |
| Transport and Hostel Facilities PDF | Listed on the Prospectus page; **not downloaded, not in MANIFEST.md** (property 6) |
| Course codes | Not in the corpus; golden set has none (decision above) |

## What "done" looks like for this file

- [x] Total page count: **390 pages across 15 documents** (≥40 required)
- [x] Which docs needed OCR: Faculty Entrepreneurship policy (confirmed
      scanned) + Undergraduate Academic Rules Aug 2023 (near-textless body)
- [x] Mangled-table example pointer: fee/grading tables are HTML — the
      indexer (AGENT_INDEXER, `docs/PIPELINE.md`) must capture one
      before/after table-extraction example from these pages
- [x] Excluded (absent-topic) document named explicitly, in code and here
- [x] Exact terms recorded from the fetched copies, with the clause-4.2
      correction flagged for AGENT_EVAL

## Checklist before the first full-corpus index

1. **Re-run the fetch** (`python3 scripts/fetch_corpus.py`) from your own
   machine/network before the indexer runs, and confirm the manifest hashes
   still match — the site re-publishes files (the script warns on mismatch).
   The PDFs land in `corpus/raw/` (gitignored); only the manifest is committed.
2. **Check `corpus/raw/` is gitignored** — the repo-root `.gitignore`
   already contains a `corpus/raw/` rule (confirmed 2026-11-05), and the
   fetch script also writes `corpus/raw/.gitignore` as a backstop. Verify
   with `git status` after fetching that no PDF shows up as untracked.
3. **Course-code question - decided:** the golden set's exact-term questions use a
   clause number and a CGPA threshold; there is no course-code question and no
   course code was invented (see the inventory row "Course codes").
4. **OCR check:** after the first indexing run, confirm the Entrepreneurship
   policy and the Aug 2023 rules actually produced chunks (they are the two
   documents most likely to come back empty).

## Verification against the final index (2026-11-08)

Measured from the final full index run (`docs/evidence/live/index_done.txt`,
`docs/evidence/live/indexer-final-run.log`), not from the assignment text:

| Property | Real result |
|---|---|
| 1 - scale | 15 documents, **390 pages**, 153 996 tokens (len/4 estimate) -> **480 chunks** (512/64), amplification 1.071 |
| 2 - version pairs | `superseded=true`: Undergraduate Academic Rules **Aug 2023** (26 pp), EE PLOs **before 2024 (12)**, Annual Reports 2019-20 .. 2022-23; current: Handbook Jun 2026, EE PLOs 2024+ (11), Annual Report 2023-24. Retrieval with the filter off returns the 12-PLO list as rank 1 (`docs/FAILURE-ANALYSIS.md` E) |
| 3 - scanned PDFs | **two** documents needed OCR: Faculty Entrepreneurship policy (all 8 pages) and Aug 2023 rules (24 of 26 pages); also image-only cover/closing pages of the Handbook (5) and Student Handbook (4). 41 pages OCR'd, **0 unrecovered**. Without OCR: 0 chunks / 214 chars (`docs/evidence/live/failure-A-no-ocr.json`) |
| 4 - tables | Fee page (tuition, refund timeline), Grading page (grade points) as HTML `[TABLE]` blocks; Annual Reports (faculty by campus, graduates, publications). Before/after example: `docs/PIPELINE.md` |
| 5 - long definitions | Student Handbook section XII *Policy on Generative AI Based Tools* (numbered sub-sections, pp 40-52); a 100-token chunker splits it (recall impact: `docs/PIPELINE.md` chunking table) |
| 6 - absent topic | Transport and Hostel Facilities PDF excluded; the hostel and bus-route questions abstain (`eval/results.json`: abstention correctness 1.00) |
| 7 - exact terms | clause 4.4 / 5.4 / 1.21, CGPA 2.00, Rs. 12,000, refund percentages; **no course code** (decision above). Exact-term recall@5 is the worst of the question types: 0.50 (`docs/ENGINEERING-NOTES.md` Q5) |

Page-count note: the assignment said "about 53" and "about 60" pages for the two handbooks; the fetched
copies have **58** and **64**.
