#!/usr/bin/env bash
# ops/scripts/droplet_add_swapfile.sh
# Idempotent. Adds 1 GB swap to the production droplet.
# Per architecture audit (docs/claude_audits/user_stats_architecture_research_2026-05-26.md §4):
# single most cost-effective OOM prevention for the 2 GB droplet, required
# BEFORE enabling the User Stats endpoint.
#
# Run via:
#   ssh root@<droplet-ip> 'bash -s' < ops/scripts/droplet_add_swapfile.sh
#
# Verification post-run:
#   free -h           # Swap row should show 1.0 GiB total
#   swapon --show     # /swapfile listed
#   sysctl vm.swappiness   # 10
#   grep swapfile /etc/fstab

set -euo pipefail

SWAPFILE=/swapfile
SIZE_MB=1024

if [ -f "$SWAPFILE" ]; then
  echo "Swapfile already exists at $SWAPFILE — no-op."
  swapon --show
  exit 0
fi

echo "Creating ${SIZE_MB}MB swapfile at $SWAPFILE..."
fallocate -l ${SIZE_MB}M "$SWAPFILE"
chmod 600 "$SWAPFILE"
mkswap "$SWAPFILE"
swapon "$SWAPFILE"

# Persist across reboots
if ! grep -q "^${SWAPFILE} " /etc/fstab; then
  echo "${SWAPFILE} none swap sw 0 0" >> /etc/fstab
fi

# Tune swap aggressiveness (lower = prefer RAM, only swap under pressure)
sysctl vm.swappiness=10
if ! grep -q "^vm.swappiness" /etc/sysctl.conf; then
  echo "vm.swappiness=10" >> /etc/sysctl.conf
fi

echo
echo "Done. Verification:"
free -h
echo
swapon --show
echo
echo "Settings:"
echo "  /etc/fstab: $(grep "^${SWAPFILE} " /etc/fstab || echo MISSING)"
echo "  vm.swappiness: $(sysctl -n vm.swappiness)"
