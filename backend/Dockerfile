# ── Stage 1: Dependencies ────────────────────────────
FROM python:3.12-slim AS deps
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ─────────────────────────────────
FROM python:3.12-slim

# Single layer for runtime deps — curl for healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pre-built Python packages from deps stage
COPY --from=deps /install /usr/local

# Copy application code (ordered by change frequency for better caching)
COPY server.py .
COPY lib/ lib/
COPY templates/ templates/
COPY scripts/ scripts/

RUN mkdir -p /app/db

EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
