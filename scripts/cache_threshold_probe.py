#!/usr/bin/env python3
"""Measure semantic-cache cosine similarities on paraphrase vs near-miss pairs.

Runs inside an api pod (uses the API's own embedding path):

    kubectl exec -i deploy/api -n rahbar -- python - < scripts/cache_threshold_probe.py

The cache stores the query embedding (``search_query: `` prefix included), so
the similarity of two QUESTIONS decides a hit. A paraphrase should hit
(same answer), a near-miss must not (different answer served = false hit).
"""

import json

from app.providers import get_provider
from app.services.chat import query_text

PARAPHRASE = [
    (
        "What is the tuition fee per credit hour?",
        "How much is tuition per credit hour?",
    ),
    (
        "What is the university's attendance requirement for a course?",
        "How much attendance do I need in a course?",
    ),
    (
        "What is the minimum CGPA to avoid academic warning?",
        "What CGPA do I need to avoid an academic warning?",
    ),
    (
        "How many program learning outcomes does Electrical Engineering have?",
        "What is the number of PLOs for the Electrical Engineering program?",
    ),
    (
        "What is the fee refund timeline if I withdraw from a course?",
        "When can I get a fee refund after withdrawing from a course?",
    ),
    (
        "Can a student register for a course after failing its prerequisite?",
        "Is it allowed to take a course if I failed its prerequisite?",
    ),
]
NEAR_MISS = [
    ("What is the tuition fee per credit hour?", "What is the admission fee?"),
    (
        "What is the attendance requirement for undergraduate programmes?",
        "What is the attendance requirement for graduate programmes?",
    ),
    (
        "How many PLOs does the Electrical Engineering program have?",
        "How many PLOs did the Electrical Engineering program have before 2024?",
    ),
    (
        "What fee refund applies if I withdraw by the 10th day of classes?",
        "What fee refund applies if I withdraw by the 20th day of classes?",
    ),
    (
        "What is the minimum CGPA to avoid academic warning?",
        "What is the minimum CGPA required for graduation?",
    ),
    (
        "What does clause 4.4 say about registering for failed courses?",
        "What does clause 5.8 say about failed courses?",
    ),
    ("What are the hostel allotment rules?", "What are the bus routes and timings?"),
]


def cos(a, b):
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


prov = get_provider()
rows = {"paraphrase": [], "near_miss": []}
for kind, pairs in (("paraphrase", PARAPHRASE), ("near_miss", NEAR_MISS)):
    for a, b in pairs:
        ea, eb = prov.embed([query_text(a)])[0], prov.embed([query_text(b)])[0]
        rows[kind].append({"a": a, "b": b, "cosine": round(cos(ea, eb), 4)})
table = {}
for t in (0.80, 0.85, 0.88, 0.90, 0.92, 0.95):
    table[str(t)] = {
        "paraphrase_hits": sum(r["cosine"] >= t for r in rows["paraphrase"]),
        "paraphrase_total": len(rows["paraphrase"]),
        "false_hits": sum(r["cosine"] >= t for r in rows["near_miss"]),
        "near_miss_total": len(rows["near_miss"]),
    }
print(json.dumps({"pairs": rows, "thresholds": table}, indent=1))
