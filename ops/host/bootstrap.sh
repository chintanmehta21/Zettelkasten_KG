#!/usr/bin/env bash
# ops/host/bootstrap.sh
#
# One-shot droplet bootstrap. Safe to re-run (idempotent).
# Run as root on a fresh DO Docker 1-Click Ubuntu 22.04 droplet.
#
# Required environment variables:
#   DEPLOY_PUBKEY — the SSH public key (one line) for the deploy user

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "Must run as root" >&2
    exit 1
fi

if [[ -z "${DEPLOY_PUBKEY:-}" ]]; then
    echo "DEPLOY_PUBKEY env var is required (the deploy user's SSH public key)" >&2
    exit 1
fi

echo "[bootstrap] Updating apt index and installing security packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
    ufw fail2ban unattended-upgrades apt-listchanges \
    logrotate curl ca-certificates jq

echo "[bootstrap] Configuring unattended-upgrades (security only, no reboot)..."
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
cat > /etc/apt/apt.conf.d/50unattended-upgrades <<'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Mail "";
EOF

echo "[bootstrap] Configuring UFW..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 443/udp comment 'HTTP/3 QUIC'
ufw --force enable
ufw status verbose

echo "[bootstrap] Enabling fail2ban with sshd jail..."
systemctl enable --now fail2ban

echo "[bootstrap] Creating 1 GiB swapfile..."
if [[ ! -f /swapfile ]]; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi
sysctl -w vm.swappiness=10

echo "[bootstrap] Installing kernel tuning..."
install -m 0644 /opt/zettelkasten/repo-cache/ops/host/sysctl-zettelkasten.conf \
    /etc/sysctl.d/99-zettelkasten.conf
sysctl --system

echo "[bootstrap] Configuring file descriptor limits..."
cat > /etc/security/limits.d/zettelkasten.conf <<'EOF'
*    soft nofile 65535
*    hard nofile 65535
root soft nofile 65535
root hard nofile 65535
EOF

echo "[bootstrap] Creating deploy user..."
if ! id deploy &>/dev/null; then
    useradd --create-home --shell /bin/bash --groups docker deploy
fi
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh
echo "$DEPLOY_PUBKEY" > /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

echo "[bootstrap] Installing NOPASSWD sudoers whitelist for deploy user..."
# Required by .github/workflows/deploy-droplet.yml:
#   - sudo tee / chmod / chown on /opt/zettelkasten/compose/.env
#   - sudo ops/deploy/*.sh (deploy, rollback, retire_color, reload_caddy, healthcheck)
# Required by .github/workflows/droplet-maintenance.yml:
#   - sudo fallocate / mkswap / swapon / sysctl / journalctl / apt-get / find / rm
# Any other sudo command falls through to password prompt → CI fails cleanly.
cat > /etc/sudoers.d/99-zettelkasten-deploy <<'EOF'
deploy ALL=(root) NOPASSWD: /usr/bin/tee /opt/zettelkasten/compose/.env, /usr/bin/chmod 600 /opt/zettelkasten/compose/.env, /usr/bin/chown deploy\:deploy /opt/zettelkasten/compose/.env, /opt/zettelkasten/deploy/deploy.sh, /opt/zettelkasten/deploy/deploy.sh *, /opt/zettelkasten/deploy/rollback.sh, /opt/zettelkasten/deploy/rollback.sh *, /opt/zettelkasten/deploy/retire_color.sh, /opt/zettelkasten/deploy/retire_color.sh *, /opt/zettelkasten/deploy/reload_caddy.sh, /opt/zettelkasten/deploy/healthcheck.sh, /opt/zettelkasten/deploy/healthcheck.sh *, /usr/bin/fallocate, /usr/sbin/mkswap, /usr/sbin/swapon, /usr/sbin/sysctl, /usr/bin/journalctl, /usr/bin/apt-get, /usr/bin/find, /usr/bin/rm
EOF
chmod 440 /etc/sudoers.d/99-zettelkasten-deploy
visudo -c -f /etc/sudoers.d/99-zettelkasten-deploy

echo "[bootstrap] Hardening sshd (key-only, no root login)..."
cat > /etc/ssh/sshd_config.d/99-zettelkasten.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
UsePAM yes
X11Forwarding no
PermitEmptyPasswords no
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
EOF
systemctl restart ssh

echo "[bootstrap] Creating /opt/zettelkasten directory tree..."
install -d -o deploy -g deploy -m 0755 \
    /opt/zettelkasten \
    /opt/zettelkasten/compose \
    /opt/zettelkasten/caddy \
    /opt/zettelkasten/caddy/data \
    /opt/zettelkasten/caddy/config \
    /opt/zettelkasten/data \
    /opt/zettelkasten/data/kg_output \
    /opt/zettelkasten/data/bot_data \
    /opt/zettelkasten/logs \
    /opt/zettelkasten/logs/caddy \
    /opt/zettelkasten/deploy

echo blue > /opt/zettelkasten/ACTIVE_COLOR
chown deploy:deploy /opt/zettelkasten/ACTIVE_COLOR

echo "[bootstrap] Creating shared Docker network..."
docker network inspect zettelnet >/dev/null 2>&1 || docker network create zettelnet

echo "[bootstrap] Installing logrotate config for Caddy logs..."
install -m 0644 /opt/zettelkasten/repo-cache/ops/host/logrotate-zettelkasten.conf \
    /etc/logrotate.d/zettelkasten

echo "[bootstrap] Installing systemd unit..."
install -m 0644 /opt/zettelkasten/repo-cache/ops/systemd/zettelkasten.service \
    /etc/systemd/system/zettelkasten.service
systemctl daemon-reload
systemctl enable zettelkasten.service

echo "[bootstrap] DONE."
echo
echo "Next steps:"
echo "  1. Verify SSH as deploy user: ssh deploy@<droplet-ip>"
echo "  2. Trigger the GitHub Actions deploy workflow targeting stage.zettelkasten.in"
