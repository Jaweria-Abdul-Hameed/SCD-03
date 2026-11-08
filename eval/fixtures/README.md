# eval/fixtures/ — tiny fixture corpus for CI

## Why these files exist

The full FAST-NUCES corpus is ≥6 documents and ≥40 pages. Indexing and
evaluating against it takes minutes and needs the real documents fetched
first. CI's `e2e-eval` job (`.github/workflows/ci.yml`) needs something
much smaller: enough documents to make recall@k meaningful, fast enough
to run on every pull request on a kind/k3d cluster.

These three short Markdown documents are that corpus:

| File | What it covers | Golden questions it serves |
|---|---|---|
| `doc1.md` | Clause 4.4 (prerequisite; corrected from starter-kit 4.2), clause 1.21 (attendance), CGPA 2.00 standing | G01, G02, G11, G12 |
| `doc2.md` | Tuition-per-credit-hour table, refund timeline, fee waivers | G04, G06, G15 |
| `doc3.md` | Version pair: attendance clause 1 (2023, superseded) vs 1.21 (2026, current) | G09, G10 (filter test) |

## What they are NOT

- **Not real university documents.** Every figure in them (80% attendance,
  CGPA 2.00, PKR 10,000 per credit hour, 100%/50%/0% refunds) is a
  **fixture value invented for CI**. Each file says so at the top and
  bottom. Never copy a fixture number into `eval/golden.yaml`, a report,
  or a demo answer as a real university rule.
- **Not a substitute for the real baseline.** `eval/baseline.json` is
  labelled `measured_on: fixture corpus (eval/fixtures/)` for exactly
  this reason. After the first full-corpus index, re-run
  `python eval/run_eval.py` against the live stack and update
  `eval/baseline.json` with the real numbers.
- **Not the abstention test.** The must-abstain questions (G13 hostel,
  G14 transport) have no fixture document on purpose — the fixture
  corpus, like the real one, deliberately excludes that topic.

## How CI uses them

1. Create a kind/k3d cluster, apply the manifests.
2. Run the indexer Job with the fixture corpus as its input
   (the Job's input path / ConfigMap points at `eval/fixtures/`).
3. Wait for the API rollout, then run
   `python eval/run_eval.py --baseline eval/baseline.json`.
4. The sec. 5.4 gate fails the job if recall@5 drops >5pp below the
   fixture baseline, any must-abstain question is answered from context,
   or citation validity falls below 95%.

## How to run locally

```bash
# Index the fixtures, start the API, then:
python eval/run_eval.py --api-base http://localhost:8000
# Or validate the gate logic with no live API at all:
python eval/run_eval.py --dry-run --results-file eval/results.json
python -m pytest eval/test_run_eval.py -v
```
