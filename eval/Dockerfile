# RAHBAR RAGOps 3-level evaluation + release gate Job image (Part B, C2, F2).
# Build from repo root: docker build -f eval/Dockerfile -t ghcr.io/rahbar/eval:TAG .
FROM python:3.12-slim

RUN useradd -m -u 10001 rahbar
WORKDIR /app

# Quoted: unquoted `pkg>=x` is parsed by /bin/sh as an output redirect, which
# silently drops every version pin and leaves junk files named "=2.9" etc.
RUN pip install --no-cache-dir "pydantic>=2.9" "pydantic-settings>=2.6" "requests>=2.32" "pyyaml>=6.0" "numpy>=1.26"

COPY eval/ ./eval/

RUN chown -R rahbar:rahbar /app
USER 10001

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "eval/run_ragops_eval.py"]
