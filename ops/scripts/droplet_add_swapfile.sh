#!/usr/bin/env bash
# ops/scripts/droplet_add_swapfile.sh
# Idempotent. Adds 1 GB swap to the production droplet.
# Per architecture audit (docs/claude_audits/user_stats_architecture_research_2026-05-26.md §4):
# single most cost-effective OOM prevention for the 2 GB droplet, required
# BEFORE enabling the User Stats endpoint.
#
# Safety-net: ops/host/bootstrap.sh provisions swap during initial droplet
# setup using the same pattern. This script is a standalone idempotent
# re-runner used when (a) bootstrap was missed, (b) the swapfile was deleted,
# (c) we need to recover from a prior partial-apply (fallocate succeeded but
# mkswap/swapon failed).
#
# Run via:
#   ssh root@<droplet-ip> 'bash -s' < ops/scripts/droplet_add_swapfile.sh
#
# Verification post-run:
#   free -h           # Swap row should show ~1.0 GiB total
#   swapon --show     # /swapfile listed
#   sysctl vm.swappiness   # 10
#   cat /etc/sysctl.d/99-zettelkasten-swap.conf
#   grep swapfile /etc/fstab

set -euo pipefail

SWAPFILE=/swapfile
SIZE_MB=1024

# Already active? No-op.
if swapon --show=NAME --noheadings 2>/dev/null | grep -q "^${SWAPFILE}$"; then
  echo "Swap already active at $SWAPFILE — no-op."
  swapon --show
  exit 0
fi

# Partial-state: file exists but swap not active. Wipe + recreate cleanly.
if [[ -f "$SWAPFILE" ]]; then
  echo "Found stale $SWAPFILE not currently in swap; removing to recreate cleanly."
  rm -f "$SWAPFILE"
fi

echo "Creating ${SIZE_MB}MB swapfile at $SWAPFILE..."
fallocate -l "${SIZE_MB}M" "$SWAPFILE"
chmod 600 "$SWAPFILE"
mkswap "$SWAPFILE"
swapon "$SWAPFILE"

# Persist across reboots (idempotent — only append if not present)
if ! grep -q "^${SWAPFILE} " /etc/fstab; then
  echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
fi

# Tune swap aggressiveness (lower = prefer RAM, only swap under pressure).
# Persist via /etc/sysctl.d/* so we never collide with the catch-all sysctl.conf.
sysctl -w vm.swappiness=10
cat > /etc/sysctl.d/99-zettelkasten-swap.conf <<'EOF'
vm.swappiness=10
EOF

echo
echo "Done. Verification:"
free -h
echo
swapon --show
echo
echo "Settings:"
echo "  /etc/fstab: $(grep "^${SWAPFILE} " /etc/fstab || echo MISSING)"
echo "  /etc/sysctl.d/99-zettelkasten-swap.conf: $(cat /etc/sysctl.d/99-zettelkasten-swap.conf)"
echo "  vm.swappiness (live): $(sysctl -n vm.swappiness)"
