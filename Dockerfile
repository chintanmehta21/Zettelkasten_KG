FROM python:3.12-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Install the package
RUN pip install --no-cache-dir -e .

# Render uses PORT env var; PTB webhook reads WEBHOOK_PORT
# Default to 8443 for local testing
ENV WEBHOOK_PORT=8443

EXPOSE ${WEBHOOK_PORT}

CMD ["python", "-m", "zettelkasten_bot"]
