# RAHBAR indexer — the only writer to ChromaDB (assignment sec. 4.2).
# Runs as a one-shot Kubernetes Job / weekly CronJob; NEVER at API startup.
FROM python:3.12-slim

# tesseract-ocr: OCR fallback for scanned PDFs (failure mode A).
# poppler-utils: pdftoppm for pdf2image, and pdffonts for scan checks.
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (assignment sec. 4.7): containers must not run as root.
RUN useradd -m -u 10001 rahbar
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline/ ./pipeline/

# Config is read from env vars with these defaults (ConfigMap in-cluster):
#   EMBED_MODEL=nomic-embed-text  CHROMA_HOST=chroma  CHROMA_PORT=8000
#   CHROMA_COLLECTION=rahbar_corpus  CHUNK_SIZE=512  CHUNK_OVERLAP=64
#   OLLAMA_HOST=host.minikube.internal:11434  REDIS_HOST=redis  REDIS_PORT=6379
# CPU/memory requests+limits live in the K8s manifests, not here.
ENV EMBED_MODEL=nomic-embed-text \
    CHROMA_HOST=chroma \
    CHROMA_PORT=8000 \
    CHROMA_COLLECTION=rahbar_corpus \
    CHUNK_SIZE=512 \
    CHUNK_OVERLAP=64 \
    OLLAMA_HOST=host.minikube.internal:11434 \
    REDIS_HOST=redis \
    REDIS_PORT=6379 \
    PYTHONUNBUFFERED=1

USER 10001
ENTRYPOINT ["python", "-m", "pipeline"]
