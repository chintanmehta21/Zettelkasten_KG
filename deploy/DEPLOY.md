# Zettelkasten Bot — Deployment Guide

This guide covers a production deployment of the Zettelkasten Telegram Bot
using systemd (process management) and nginx (TLS termination / reverse proxy).

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| Python 3.11+ | `python3 --version` |
| nginx | `sudo apt install nginx` (Debian/Ubuntu) |
| certbot | `sudo apt install certbot python3-certbot-nginx` |
| A domain name | Pointed at your server's public IP |
| A Telegram bot token | Obtained from @BotFather |

---

## 1  Clone and Set Up the Virtual Environment

```bash
sudo useradd --system --shell /sbin/nologin zettelbot
sudo mkdir -p /opt/zettelkasten-bot
sudo chown zettelbot:zettelbot /opt/zettelkasten-bot

sudo -u zettelbot git clone https://github.com/your-org/zettelkasten-bot.git \
    /opt/zettelkasten-bot

cd /opt/zettelkasten-bot
sudo -u zettelbot python3 -m venv .venv
sudo -u zettelbot .venv/bin/pip install -e .
```

---

## 2  Configure Environment Variables

Copy the template and populate every required variable:

```bash
sudo cp .env.example /opt/zettelkasten-bot/.env
sudo chown zettelbot:zettelbot /opt/zettelkasten-bot/.env
sudo chmod 600 /opt/zettelkasten-bot/.env
sudo nano /opt/zettelkasten-bot/.env
```

Required variables (no default — must be set):

```
TELEGRAM_BOT_TOKEN=
ALLOWED_CHAT_ID=
GEMINI_API_KEY=
REDDIT_CLIENT_ID=
REDDIT_CLIENT_SECRET=
```

Webhook-specific variables (required when `WEBHOOK_MODE=true`):

```
WEBHOOK_MODE=true
WEBHOOK_URL=https://YOUR_DOMAIN/YOUR_BOT_TOKEN
WEBHOOK_PORT=8443
WEBHOOK_SECRET=
```

Optional variables with defaults:

```
REDDIT_USER_AGENT=ZettelkastenBot/1.0
REDDIT_COMMENT_DEPTH=10
MODEL_NAME=gemini-2.5-flash
LOG_LEVEL=INFO
KG_DIRECTORY=./kg_output
DATA_DIR=./data
```

---

## 3  Install and Start the systemd Service

```bash
sudo cp /opt/zettelkasten-bot/deploy/zettelkasten-bot.service \
    /etc/systemd/system/zettelkasten-bot.service

sudo systemctl daemon-reload
sudo systemctl enable zettelkasten-bot
sudo systemctl start zettelkasten-bot
```

---

## 4  Configure nginx with TLS

### 4.1  Install the nginx config

```bash
sudo cp /opt/zettelkasten-bot/deploy/nginx.conf \
    /etc/nginx/sites-available/zettelkasten-bot

# Edit the two placeholders: YOUR_DOMAIN and YOUR_BOT_TOKEN
sudo nano /etc/nginx/sites-available/zettelkasten-bot

sudo ln -s /etc/nginx/sites-available/zettelkasten-bot \
    /etc/nginx/sites-enabled/zettelkasten-bot

sudo nginx -t && sudo systemctl reload nginx
```

### 4.2  Obtain a TLS certificate

```bash
sudo certbot --nginx -d YOUR_DOMAIN
```

certbot edits the nginx config in place to point at the generated certificate.
After this step, reload nginx once more:

```bash
sudo systemctl reload nginx
```

---

## 5  Register the Webhook with Telegram

With `WEBHOOK_MODE=true` and `WEBHOOK_URL` set in `.env`, the bot registers
its webhook automatically on startup via PTB's `run_webhook()`.

To verify the registration:

```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

---

## 6  Verification

```bash
# Service is running
sudo systemctl status zettelkasten-bot

# Live log stream
sudo journalctl -u zettelkasten-bot -f

# nginx is forwarding correctly (should return a Telegram error, not a 502)
curl -sk https://YOUR_DOMAIN/YOUR_BOT_TOKEN | python3 -m json.tool

# TLS certificate validity
echo | openssl s_client -connect YOUR_DOMAIN:443 -servername YOUR_DOMAIN 2>/dev/null \
    | openssl x509 -noout -dates
```

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `systemctl status` shows `failed` | `journalctl -u zettelkasten-bot -n 50` — look for missing env vars or import errors |
| nginx returns 502 Bad Gateway | Bot not listening on port 8443 — confirm service is running |
| Telegram delivers no updates | `getWebhookInfo` — confirm `url` and `has_custom_certificate` fields |
| SSL handshake errors | Certbot certificate may have expired — `certbot renew --dry-run` |
