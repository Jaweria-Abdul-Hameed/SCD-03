# RAGOps Evaluation Summary

```text
==============================================================================
RAHBAR RAGOps 3-LEVEL OFFLINE EVALUATION SUMMARY  (seed=42)
==============================================================================
Timestamp : 2026-11-27T20:54:35.940347+00:00
Golden Set: /app/eval/golden.jsonl (32 questions)
------------------------------------------------------------------------------
LEVEL 1 — MODULE (Embedding Quality)
  Paraphrase Mean Cosine (16 pairs) : 0.7721
  Unrelated Mean Cosine  (16 pairs) : 0.4830
  Cosine Separation Gap              : 0.2891
  Embedding Time / Chunk (ms)        : 73.91 ms (5x 512-tok, fixtures)
  Determinism Max Abs Diff           : 0.00000000
------------------------------------------------------------------------------
LEVEL 2 — COMPONENT (Retrieval Quality + Noise Test)
  recall@3 : 0.3810   | recall@5 : 0.3810
  MRR      : 0.3810   | nDCG@5   : 0.3810
  Noise (query_typos): r@3=0.5238 (+0.1429), r@5=0.5238 (+0.1429), MRR=0.5238 (+0.1429), nDCG@5=0.5238 (+0.1429)
------------------------------------------------------------------------------
LEVEL 3 — END-TO-END (Answer Quality & Latency)
  Faithfulness (llm_judge, dolphin-mistral) : 0.7143 (7 grounded)
  Faithfulness vs Human (llm_judge, dolphin-mistral) : 1.0000 (3/3)
  Abstention Correctness             : 1.0000 (11 checked)
  Injection Resistance               : 1.0000 (1 checked)
  Citation Validity                  : 1.0000 (7 citations)
  Latency p50 / p95                  : 1561.3 ms / 6951.9 ms
==============================================================================
```
