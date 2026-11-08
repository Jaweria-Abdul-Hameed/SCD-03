"""Prometheus metrics (assignment §4.8). Single registry, shared by routes/services."""

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
cache_hits_total = Counter("cache_hits_total", "Semantic cache hits")
cache_misses_total = Counter("cache_misses_total", "Semantic cache misses")
abstentions_total = Counter(
    "abstentions_total", "Honest abstentions (answered_from_context=false)"
)
fallbacks_total = Counter(
    "fallbacks_total", "Canned fallbacks after validation failure"
)
tokens_in_total = Counter(
    "tokens_in_total", "Approximate input tokens (whitespace estimate)"
)
tokens_out_total = Counter(
    "tokens_out_total", "Approximate output tokens (whitespace estimate)"
)
