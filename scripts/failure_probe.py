#!/usr/bin/env python3
"""Show what retrieval returns for a question (failure-analysis helper).

Runs inside an api pod; honours the same env as the API (TOP_K, RELEVANCE_FLOOR...):

    kubectl exec -i deploy/api -n rahbar -- env TOP_K=1 python - "<question>" [old] < scripts/failure_probe.py

Prints rank, similarity, source, doc_version, superseded for the retrieved chunks and
the generated answer when ``gen`` is passed (a real LLM call, 15-60 s).
"""

import json
import sys

from app.config import settings
from app.providers import get_provider
from app.retrieval.retriever import retrieve
from app.services.chat import query_text
from app.services.grounding import build_augmented_prompt

q = sys.argv[1]
flags = sys.argv[2:]
prov = get_provider()
emb = prov.embed([query_text(q)])[0]
chunks = retrieve(q, emb, include_old_versions="old" in flags)
print(
    f"TOP_K={settings.TOP_K} include_old_versions={'old' in flags} temperature={settings.TEMPERATURE}"
)
for i, c in enumerate(chunks, 1):
    m = c["metadata"]
    sim = c.get("score", c.get("similarity", 0))
    print(
        f"{i}. sim={sim:.3f} {m['source']} v={m['doc_version']} superseded={m['superseded']} p{m['page']}"
    )
if "gen" in flags:
    out = json.loads(prov.generate(build_augmented_prompt(q, chunks)))
    print(
        "ANSWER:",
        out.get("answer"),
        "| answered_from_context:",
        out.get("answered_from_context"),
    )
