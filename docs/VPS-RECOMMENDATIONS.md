# VPS Recommendations for the Zettelkasten Bot

This bot is a long-running Python process with modest resource needs. Any Linux VPS with a public IPv4 address and a domain name (for webhook TLS) will work. This document covers the best free and low-cost options.

---

## Minimum Requirements

| Resource | Minimum | Notes |
|----------|---------|-------|
| RAM | 256 MB | Bot idle ~50–80 MB; Python + libraries ~120–180 MB total |
| CPU | 1 vCPU | The bot is I/O-bound (Telegram + Reddit API calls); CPU is rarely the limit |
| Storage | 2 GB | OS + vault + logs; 5 GB comfortable |
| Network | Public IPv4 | Required for Telegram webhook TLS termination |
| Domain | Required | Telegram webhooks require HTTPS; a cheap domain (~$1–$12/yr) or a free subdomain (e.g., DuckDNS) works |

---

## Primary Recommendation: Oracle Cloud Always Free

**Oracle Cloud Free Tier — Ampere A1 Flex** is the standout option for this workload:

- **4 ARM vCPUs + 24 GB RAM** — permanently free (not a trial), shared across up to 4 instances
- **200 GB block storage** — far more than needed
- **Outbound transfer** — 10 TB/month free
- **ARM architecture** — Python 3.11 and all dependencies install normally via pip on `aarch64`

This is massively over-provisioned for a bot that idles at ~80 MB RAM. You could run the bot, SyncThing, nginx, and several other services on a single free instance. The catch is that Oracle's sign-up process occasionally requires a credit card and can reject accounts — have a fallback ready (Hetzner is the best paid alternative).

**Sign up:** [cloud.oracle.com/free](https://www.oracle.com/cloud/free/)

---

## Alternatives Comparison

| Provider | Tier | vCPUs | RAM | Storage | Cost | Notes |
|----------|------|-------|-----|---------|------|-------|
| **Oracle Cloud** | Always Free (A1 Flex) | 4 ARM | 24 GB | 200 GB | **Free** | Best free option; ARM; account approval can be tricky |
| **Hetzner Cloud** | CAX11 (ARM) | 2 ARM | 4 GB | 40 GB | €4.51/mo | Best paid value; EU-based; instant provisioning |
| **DigitalOcean** | Basic Droplet | 1 vCPU | 1 GB | 25 GB | $6/mo | Good DX, managed databases available; pricier than Hetzner |
| **Fly.io** | Free Machines | Shared | 256 MB | 1 GB | Free\* | Free tier: 3 shared VMs; 160 GB outbound; no persistent disk by default |
| **Google Cloud** | e2-micro | 2 vCPU (burst) | 1 GB | 30 GB | Free\* | 1 free e2-micro per region (us-east1/us-west1/us-central1); egress costs apply |
| **AWS Lightsail** | Nano | 1 vCPU | 512 MB | 20 GB | $3.50/mo | Predictable pricing; AWS ecosystem; free trial 3 months |

\* Fly.io and Google Cloud free tiers have usage limits and may incur charges if limits are exceeded. Read provider terms before relying on them for production.

---

## OS Recommendation

**Ubuntu 22.04 LTS** is the recommended OS for all providers above. It offers:

- Python 3.10 in the default repos (sufficient); Python 3.11 available via the [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa) if needed
- Long-term support through April 2027 (standard) / April 2032 (extended)
- Wide community support and extensive documentation
- Systemd for managing the bot as a service (see `ops/deploy/DEPLOY.md`)

To install Python 3.11 on Ubuntu 22.04 if needed:
```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update && sudo apt install python3.11 python3.11-venv
```

**Ubuntu 24.04 LTS** is also a valid choice (ships Python 3.12 natively), but has a shorter track record on ARM-based VPS instances as of 2024.

---

## Oracle Cloud Setup Notes

1. During sign-up, choose the **Always Free** tier — do not select a paid upgrade.
2. Create the instance in a region that offers A1 Flex (most do; avoid regions marked as constrained).
3. Select **Ubuntu 22.04 Minimal** as the image; choose **VM.Standard.A1.Flex** shape.
4. Allocate at minimum 1 OCPU and 6 GB RAM (you have 4 OCPU / 24 GB to allocate freely).
5. Upload your SSH public key during instance creation.
6. After provisioning, open ports 22 (SSH), 80 (HTTP), and 443 (HTTPS) in the OCI Security List and Ubuntu's `ufw` firewall.

---

## Server Setup

Once your VPS is running, follow **[ops/deploy/DEPLOY.md](../ops/deploy/DEPLOY.md)** for the complete server setup steps:

- Python environment and dependency installation
- nginx reverse proxy configuration for Telegram webhooks
- systemd service file (`zettelkasten-bot.service`) for process management
- SSL/TLS certificate setup via Certbot (Let's Encrypt)
- Environment variable configuration

Everything in that guide is tested on Ubuntu 22.04 with both x86_64 and ARM (Ampere A1) hardware.
