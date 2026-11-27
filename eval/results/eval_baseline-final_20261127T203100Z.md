# RAGOps Evaluation Summary

```text
==============================================================================
RAHBAR RAGOps 3-LEVEL OFFLINE EVALUATION SUMMARY  (seed=42)
==============================================================================
Timestamp : 2026-11-27T20:24:41.071984+00:00
Golden Set: /app/eval/golden.jsonl (32 questions)
------------------------------------------------------------------------------
LEVEL 1 — MODULE (Embedding Quality)
  Paraphrase Mean Cosine (16 pairs) : 0.7721
  Unrelated Mean Cosine  (16 pairs) : 0.4830
  Cosine Separation Gap              : 0.2891
  Embedding Time / Chunk (ms)        : 68.15 ms (5x 512-tok, fixtures)
  Determinism Max Abs Diff           : 0.00000000
------------------------------------------------------------------------------
LEVEL 2 — COMPONENT (Retrieval Quality + Noise Test)
  recall@3 : 0.5714   | recall@5 : 0.7143
  MRR      : 0.4913   | nDCG@5   : 0.5460
  Noise (query_typos): r@3=0.6667 (+0.0952), r@5=0.7143 (+0.0000), MRR=0.5810 (+0.0897), nDCG@5=0.6137 (+0.0676)
------------------------------------------------------------------------------
LEVEL 3 — END-TO-END (Answer Quality & Latency)
  Faithfulness (llm_judge, dolphin-mistral:latest) : 0.8889 (18 grounded)
  Faithfulness vs Human (llm_judge, dolphin-mistral:latest) : 1.0000 (10/10)
  Abstention Correctness             : 1.0000 (11 checked)
  Injection Resistance               : 1.0000 (1 checked)
  Citation Validity                  : 1.0000 (18 citations)
  Latency p50 / p95                  : 4950.9 ms / 7753.7 ms
------------------------------------------------------------------------------
STOCHASTICITY DIFF (Run 2 - Run 1, Fixed Seed)
  {"level1": {"paraphrase_mean_cosine": 0.0, "unrelated_mean_cosine": 0.0, "cosine_gap": 0.0, "embedding_time_per_chunk_ms": 28.68, "determinism_max_abs_diff": 0.0}, "level2": {"recall@3": 0.0, "recall@5": 0.0, "MRR": 0.0, "nDCG@5": 0.0, "noisy_recall@3": 0.0, "noisy_recall@5": 0.0, "noisy_MRR": 0.0, "noisy_nDCG@5": 0.0}, "level3": {"grounded_answered": 0, "faithfulness": 0.0, "abstention_correctness": 0.0, "injection_resistance": 0.0, "citation_validity": 0.0, "citations_checked": 0, "latency_p50_ms": 199.79, "latency_p95_ms": 2445.45}}
==============================================================================
```
