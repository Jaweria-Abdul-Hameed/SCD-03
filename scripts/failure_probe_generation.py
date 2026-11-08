#!/usr/bin/env python3
"""Failure-analysis stages D and F: break the prompt / the temperature (measured).

    kubectl exec -i deploy/api -n rahbar -- python - <variant> "<question>" < scripts/failure_probe_generation.py

variant: ``shipped`` | ``noctx`` (stage D: the 'use the supplied context / say so if
absent' instruction removed) | ``temp12`` (stage F: temperature 1.2, which the
Settings validator forbids in the ConfigMap, so it is set on the provider here).
Prints the answer, answered_from_context, citations and the wall time of the LLM call.
"""

import json
import sys
import time

from app.providers import get_provider
from app.retrieval.retriever import retrieve
from app.services.chat import query_text
from app.services.grounding import build_augmented_prompt

variant, question = sys.argv[1], sys.argv[2]
prov = get_provider()
if variant == "temp12":
    prov.temperature = 1.2
emb = prov.embed([query_text(question)])[0]
chunks = retrieve(question, emb, include_old_versions=False)
prompt = build_augmented_prompt(question, chunks)
if variant == "noctx":
    first = prompt.split("\n", 1)[0]
    assert first.startswith("You answer ONLY from the evidence below.")
    prompt = prompt.split("\n", 1)[1]
t0 = time.time()
raw = prov.generate(prompt)
dt = time.time() - t0
try:
    out = json.loads(raw)
    print(
        json.dumps(
            {
                "variant": variant,
                "temperature": prov.temperature,
                "answer": out.get("answer"),
                "answered_from_context": out.get("answered_from_context"),
                "n_citations": len(out.get("citations", [])),
                "llm_seconds": round(dt, 1),
            },
            ensure_ascii=False,
        )
    )
except json.JSONDecodeError:
    print(
        json.dumps(
            {"variant": variant, "invalid_json": raw[:200], "llm_seconds": round(dt, 1)}
        )
    )
