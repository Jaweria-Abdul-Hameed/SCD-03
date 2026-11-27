# RAGOps Evaluation Summary

```text
==============================================================================
RAHBAR RAGOps 3-LEVEL OFFLINE EVALUATION SUMMARY  (seed=42)
==============================================================================
Timestamp : 2026-11-27T21:25:05.832606+00:00
Golden Set: /app/eval/golden.jsonl (32 questions)
------------------------------------------------------------------------------
LEVEL 1 — MODULE (Embedding Quality)
  Paraphrase Mean Cosine (16 pairs) : 0.7721
  Unrelated Mean Cosine  (16 pairs) : 0.4830
  Cosine Separation Gap              : 0.2891
  Embedding Time / Chunk (ms)        : 60.25 ms (5x 512-tok, fixtures)
  Determinism Max Abs Diff           : 0.00000000
------------------------------------------------------------------------------
LEVEL 2 — COMPONENT (Retrieval Quality + Noise Test)
  recall@3 : 0.6190   | recall@5 : 0.6190
  MRR      : 0.5476   | nDCG@5   : 0.5663
  Noise (query_typos): r@3=0.6190 (+0.0000), r@5=0.6190 (+0.0000), MRR=0.5952 (+0.0476), nDCG@5=0.6015 (+0.0351)
------------------------------------------------------------------------------
LEVEL 3 — END-TO-END (Answer Quality & Latency)
  Faithfulness (llm_judge, dolphin-mistral) : 0.8000 (20 grounded)
  Faithfulness vs Human (llm_judge, dolphin-mistral) : 0.8889 (8/9)
  Abstention Correctness             : 1.0000 (11 checked)
  Injection Resistance               : 1.0000 (1 checked)
  Citation Validity                  : 1.0000 (20 citations)
  Latency p50 / p95                  : 5505.0 ms / 10476.6 ms
==============================================================================
```
