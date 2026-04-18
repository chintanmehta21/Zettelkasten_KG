# syntax=docker/dockerfile:1.7

# --- Stage 1: builder -------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build deps for any wheels that need to compile
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Create a clean virtual env we can copy wholesale to the runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install runtime requirements only (not dev)
COPY ops/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /tmp/requirements.txt

# Pre-compile site-packages to .pyc for faster cold start
RUN python -m compileall -q /opt/venv

# --- Stage 2: runtime -------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="zettelkasten-kg-website" \
      org.opencontainers.image.description="Zettelkasten Capture Bot + Web UI" \
      org.opencontainers.image.source="https://github.com/chintanmehta21/Zettelkasten_KG" \
      org.opencontainers.image.licenses="MIT"

# Minimal runtime dependencies: ca-certs (for HTTPS), tini (proper PID 1),
# curl (for healthcheck and manual debugging).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for runtime
RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --create-home --shell /bin/bash appuser

WORKDIR /app

# Copy the venv from the builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application code (chowned to appuser)
COPY --chown=appuser:appuser telegram_bot/ telegram_bot/
COPY --chown=appuser:appuser website/ website/
COPY --chown=appuser:appuser run.py ./
COPY --chown=appuser:appuser pyproject.toml ./

# Pre-create writable directories the app may use at runtime, owned by appuser
RUN mkdir -p /app/kg_output /app/bot_data \
    && chown -R appuser:appuser /app/kg_output /app/bot_data

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WEBHOOK_PORT=10000

EXPOSE 10000

USER appuser

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl --silent --show-error --fail --max-time 2 http://127.0.0.1:10000/api/health || exit 1

ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "run.py"]
