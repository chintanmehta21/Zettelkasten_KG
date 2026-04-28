# Droplet Swapfile Provisioning (one-shot)

**When:** After iter-03 deploy lands on the 2 GB droplet, before promoting traffic to the new container.

**Why:** The 2 GB DigitalOcean droplet ships with zero swap. Swap is the safety net against OOM-kill if the BGE int8 ONNX model + 2 gunicorn workers spike memory unexpectedly. Expect ~5% perf cost when swap is touched; in steady state it should never be touched.

## Steps (run on droplet via SSH)

```bash
# Verify no swap currently
swapon --show

# Allocate 2 GB swapfile
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Persist across reboots
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Tune for low swappiness — only swap under real OOM pressure
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.conf
sudo sysctl -p

# Verify
swapon --show
free -h
```

## Verification

`free -h` should show `Swap: 2.0Gi 0B 2.0Gi` (used = 0 in steady state).

## Rollback

```bash
sudo swapoff /swapfile
sudo sed -i '/swapfile/d' /etc/fstab
sudo rm /swapfile
```
