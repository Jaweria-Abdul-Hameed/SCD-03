# ADR 0002 — Semantic cache in Redis, not a second Chroma collection

- **Status:** Accepted
- **Date:** 2026-11-05
- **Context:** Assignment sec. 3.3 requires a semantic cache: a hit is cosine
  similarity at or above a threshold read from the ConfigMap
  (`cache_threshold`), the threshold is chosen with data (the lowest
  threshold with zero false hits on the test questions), follow-ups,
  abstentions, out-of-scope answers and validation failures are never
  cached, and the cache is invalidated on re-index.

## Decision

Use **Redis** (Deployment + PVC + ClusterIP Service, `k8s/base/redis.yaml`)
as the semantic cache. Store each cache entry as a Redis key using the format:
`rahbar:cache:<sha256(normalised_query)>`
where normalisation trims whitespace, converts to lowercase, and collapses multiple spaces.
The value is stored as a JSON object containing:
- `embedding`: 768-dimensional float vector produced by the pinned `nomic-embed-text` model.
- `answer`: The complete serialized Pydantic `Answer` schema (`reasoning`, `answer`, `citations`, `answered_from_context`, `confidence`).

Lookups first evaluate the exact key match, and then scan `rahbar:cache:*` computing cosine similarity against stored embeddings. A cache hit requires cosine similarity >= `CACHE_THRESHOLD` (pinned at **0.96** in `k8s/base/configmap.yaml` (`CACHE_THRESHOLD`) and `api/app/config.py:30`).

## Why Redis over a second Chroma collection

| Concern | Redis | Second Chroma collection |
|---|---|---|
| **Separation of duties** | The cache is ephemeral by design: it may be dropped and rebuilt at any time with no data loss. Redis is built for exactly that. | A second collection in the same store as the source of truth invites confusion between "the index" and "answers we once gave" — and a bug that writes cache entries into the retrieval collection (or vice versa) corrupts grounding. |
| **Invalidation on re-index** | One command: flush the cache keys on Job completion (`indexer/pipeline/store.py` invalidates Redis when indexing finishes). Atomic, total, and obviously correct. | Deleting a collection and recreating it is a heavier, slower operation, and a half-deleted collection leaves stale answers served from the old index — the exact bug sec. 3.3 warns is "real and easy to ship". |
| **TTL and eviction** | Native TTL per key and `maxmemory` eviction policies; a cache that grows without bound is a one-line config fix. | Chroma has no TTL or eviction; cache growth would need application-level garbage collection. |
| **Latency** | Redis is an in-memory key-value store; a cache lookup must be far cheaper than the retrieval + generation it replaces, or the cache is pointless. | A Chroma similarity search is a vector search over a second store — the same cost class as the retrieval it is meant to shortcut. |
| **Failure isolation** | If Redis is down, `/readyz` reports it and the API can still answer (cache miss path) — or be held out of traffic honestly. If the cache lived inside Chroma, a cache problem and an index problem would be the same outage. | Couples cache availability to index availability. |

## Consequences

- Redis needs its own persistence (PVC) so a pod restart does not cold-start
  the cache on every deploy — but losing the cache is always safe: it is
  rebuilt from live questions, never from a backup. The invalidation call
  itself is `indexer/pipeline/store.py:283` (`invalidate_semantic_cache()`),
  run on Job completion.
- The API must treat a Redis failure as a cache miss, never as a request
  failure, except at readiness time where `/readyz` reports Redis
  reachability honestly.
- **Threshold data tuning (assignment sec. 3.3) - measured on the live stack, 2026-11-08.**
  `scripts/cache_threshold_probe.py` embeds 6 paraphrase pairs (should hit) and 7
  near-miss pairs (different question, different answer - must NOT hit) with the API's own
  embedding path (`search_query:` prefix included) and counts hits per threshold. Raw
  output: `docs/evidence/live/cache-threshold-probe.json`.

  | Cosine | Pair | Kind |
  |---|---|---|
  | 0.963 | "tuition fee per credit hour?" / "How much is tuition per credit hour?" | paraphrase |
  | 0.949 | "minimum CGPA to avoid academic warning?" / "What CGPA do I need to avoid an academic warning?" | paraphrase |
  | 0.923 | "fee refund timeline if I withdraw" / "When can I get a fee refund after withdrawing" | paraphrase |
  | 0.902 | "register after failing the prerequisite?" / "allowed to take a course if I failed its prerequisite?" | paraphrase |
  | 0.877 | "attendance requirement for a course" / "How much attendance do I need" | paraphrase |
  | 0.763 | "how many PLOs does EE have" / "number of PLOs for the EE program" | paraphrase |
  | **0.952** | "how many PLOs does EE have?" / "how many PLOs did EE have **before 2024**?" | **near-miss** |
  | 0.917 | attendance requirement undergraduate / graduate programmes (80 % vs 75 %) | near-miss |
  | 0.902 | refund if I withdraw by the 10th day / by the 20th day (100 % vs 60 %) | near-miss |
  | 0.859 | "clause 4.4 ..." / "clause 5.8 ..." | near-miss |
  | 0.821 | minimum CGPA to avoid warning / required for graduation | near-miss |
  | 0.665 | tuition fee / admission fee | near-miss |
  | 0.489 | hostel allotment rules / bus routes | near-miss |

  | Threshold | paraphrases served (of 6) | **false hits (of 7)** |
  |---|---|---|
  | 0.85 | 5 | **4** |
  | 0.90 | 4 | **3** |
  | 0.92 (the previous value) | 3 | **1** - the PLO pair: a cached "11" would be served for "before 2024" (should be 12) |
  | 0.95 | 1 | **1** (0.952 > 0.95) |
  | **0.96 (SHIPPED)** | 1 | **0** |

  Rule of the lecture: the lowest threshold with zero false hits on the test questions.
  That is **0.96** - and the data say what that costs: only near-identical rewordings hit
  (hit rate on paraphrases 1 of 6; an exact repeat has cosine 1.0 and always hits). The
  precise cost of the cache being *safe* is therefore low reuse, and the ruled-out value
  is 0.92 because of the version pair. Version-sensitive questions are exactly where a
  wrong cached answer is most expensive, and a bigger embedding model or a cache key that
  includes the extracted year would be the next improvement; both were out of scope.
  (Earlier drafts of this ADR quoted trial outcomes for 0.85 / 0.88 that were not
  measurements; they have been replaced by the table above.)
- **TTL & Eviction Policy:** Primary cache coherence is maintained via event-driven
  invalidation: on completion of any re-indexing run, the indexer executes
  `invalidate_semantic_cache()` (`indexer/pipeline/store.py:283`), issuing `flushdb()` /
  deleting all `rahbar:cache:*` keys. Redis persistence via PVC (`redis-data` 2Gi) ensures
  cache survival across pod restarts, while memory pressure is bounded by Redis memory limits
  (64Mi limit in `k8s/base/redis.yaml`; measured peak 15 Mi).
- **Cache Exclusion Rules:** As enforced by `api/app/retrieval/cache.py:cacheable()`,
  follow-up questions (`follow_up: true`), explicit old-version queries (`include_old_versions: true` - found
  by the rehearsal: the key is the question only, so a cached *current* answer was served for the old-version request;
  the cache is now neither read nor written for them, `api/app/services/chat.py` `use_cache`),
  abstentions (`answered_from_context: false`), and validation failures are NEVER cached. A cached mistake is served to everyone.
