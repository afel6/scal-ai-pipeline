# ─────────────────────────────────────────────
# SCAL AI Pipeline (Hviel) — Production Dockerfile
# Multi-stage build, non-root, python:3.11-slim
# ─────────────────────────────────────────────

# Stage 1: Builder — install deps into a venv
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build tools for any C extensions
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc g++ && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip && \
    /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime — minimal image
FROM python:3.11-slim AS runtime

# Security: non-root user
RUN groupadd --gid 1001 prc && \
    useradd --uid 1001 --gid 1001 --create-home --shell /bin/bash prc

WORKDIR /app

# Copy virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Copy application source
COPY --chown=prc:prc . .

# Remove dev/test files from production image
RUN rm -rf tests/ frontend/node_modules/ frontend/e2e/ \
    *.bak *.bundle dummy_test.csv \
    __pycache__/ .pytest_cache/ .git/

# Create required directories
RUN mkdir -p /app/uploads /app/exports /app/chroma_db /app/kb && \
    chown -R prc:prc /app

USER prc

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "30"]
