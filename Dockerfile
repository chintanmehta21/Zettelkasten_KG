FROM python:3.12-slim AS builder

WORKDIR /app

# Install deps into a virtual env for clean copy
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY ops/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Pre-compile all .pyc files (saves ~1-2s on cold start)
COPY telegram_bot/ telegram_bot/
COPY website/ website/
COPY ops/ ops/
RUN python -m compileall -q telegram_bot/ website/

# ── Final stage (smaller image, faster pull) ─────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copy only the venv and app code from builder
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/telegram_bot /app/telegram_bot
COPY --from=builder /app/website /app/website
COPY --from=builder /app/ops /app/ops
COPY run.py .

ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV WEBHOOK_PORT=10000

EXPOSE ${WEBHOOK_PORT}

CMD ["python", "run.py"]
