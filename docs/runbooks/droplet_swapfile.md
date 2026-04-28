# Droplet Swapfile Provisioning + Verification

**When:** During the iter-03-mem-bounded rollout, after the Docker compose
ceiling change lands but before promoting traffic. Re-run any time the
droplet image is rebuilt or the swap config drifts.

**Why:** The 2 GB DigitalOcean droplet pairs with a 2 GB host swapfile so
the cgroup-confined containers (mem_limit 1300m, memswap_limit 2300m, see
`ops/docker-compose.{blue,green}.yml`) have a 1 GB swap budget per color.
Without this the kernel cgroup-OOM kills gunicorn workers under inference
pressure → Caddy reports 502s.

## Steps (run on droplet via SSH as the deploy user)

```bash
# ── 1. Verify current state first ─────────────────────────────────────
swapon --show
free -h
sysctl vm.swappiness

# Expected: /swapfile  file  2G ...   Swap: 2.0Gi ...   vm.swappiness = 10
# If already correct, SKIP the recreate block below.
```

```bash
# ── 2. Recreate to 2 GB if smaller (idempotent) ───────────────────────
sudo swapoff /swapfile
sudo rm /swapfile
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Persist across reboots (only if not already present)
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Tune for low swappiness — only swap under real OOM pressure
sysctl vm.swappiness  # if not already 10:
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

```bash
# ── 3. Verify cgroup v2 honors the new swap budget ────────────────────
docker exec zettelkasten-blue cat /sys/fs/cgroup/memory.max
# Expect: 1363148800 (~1.3 GB)

docker exec zettelkasten-blue cat /sys/fs/cgroup/memory.swap.max
# Expect: 1048576000 (~1.0 GB swap budget for the cgroup)
```

```bash
# ── 4. Confirm zero extra DigitalOcean cost ───────────────────────────
df -h /                   # confirm /swapfile fits on the 70 GB SSD
# Optional: from a workstation with doctl set up:
#   doctl compute droplet get <DROPLET_ID> --format Name,Size,Memory,VCPUs,PriceMonthly
# Expect: same plan and same price as before. Swap is local SSD storage,
# already billed inside the droplet plan.
```

## Verification

`free -h` shows `Swap: 2.0Gi …`. The blue and green containers report
`memory.swap.max = 1048576000`. No change in droplet plan or monthly bill.

## Rollback

```bash
sudo swapoff /swapfile
sudo sed -i '/swapfile/d' /etc/fstab
sudo rm /swapfile
```

The compose `mem_limit/memswap_limit` settings are still in repo; revert
those separately if needed.
