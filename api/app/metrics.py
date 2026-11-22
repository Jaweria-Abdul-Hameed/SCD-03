"""Prometheus metrics (assignment §4.8 & Part D3). Single registry, shared by routes/services."""

from prometheus_client import Counter, Histogram

http_requests_total = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
request_latency_seconds = Histogram(
    "request_latency_seconds", "Total request latency (s)", ["path"]
)
retrieval_latency_seconds = Histogram(
    "retrieval_latency_seconds", "Retrieval latency (s)"
)
generation_latency_seconds = Histogram(
    "generation_latency_seconds", "Generation latency (s)"
)
stage_latency_seconds = Histogram(
    "stage_latency_seconds",
    "Per-stage pipeline latency (s)",
    ["stage"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0, 30.0, 60.0, 120.0),
)
top1_retrieval_similarity = Histogram(
    "top1_retrieval_similarity",
    "Top-1 retrieved chunk cosine similarity distribution",
    buckets=(0.2, 0.3, 0.4, 0.5, 0.6, 0.64, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0),
)
queries_total = Counter("queries_total", "Total /chat queries processed")
cache_hits_total = Counter("cache_hits_total", "Semantic cache hits")
cache_misses_total = Counter("cache_misses_total", "Semantic cache misses")
abstentions_total = Counter(
    "abstentions_total", "Honest abstentions (answered_from_context=false)"
)
fallbacks_total = Counter(
    "fallbacks_total", "Canned fallbacks after validation failure"
)
injection_attempts_flagged_total = Counter(
    "injection_attempts_flagged_total",
    "Prompt injection attempts flagged by input or retrieval guardrails",
    ["rail"],
)
tokens_in_total = Counter(
    "tokens_in_total", "Approximate input tokens (whitespace estimate)"
)
tokens_out_total = Counter(
    "tokens_out_total", "Approximate output tokens (whitespace estimate)"
)
