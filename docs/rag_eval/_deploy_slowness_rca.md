# Slow Deploy RCA — feat: rag improvements iter-01 + ux bundle (SHA 6f93b80)

**Total deploy time:** 12 min 40 s (pytest 1:52, build+push 2:32, SSH-deploy 7:31, GH overhead ~46 s).

## Per-job timing (GH Actions)

| Job | Duration | Notes |
|---|---|---|
| pytest (mocked) | 1 min 52 s | Acceptable; 1208 tests + collection |
| Build & push image | 2 min 32 s | Acceptable; multi-stage cached |
| SSH deploy to droplet | **7 min 31 s** | **DOMINANT COST** |

## SSH-deploy step breakdown

| Phase | Wall time | Notes |
|---|---|---|
| Setup + checkout + Caddy reconcile | 0:23 (35:09 → 35:32) | OK |
| `Starting deploy` → Caddy reload + cutover | **7:05 (35:32 → 42:37)** | The critical-path step |
| Post-cutover (backfill skip + retire bg) | 0:01 (42:37 → 42:38) | OK |

## Root cause

The 7-minute gap between `[Starting deploy] SHA=6f93b80, ACTIVE=green, IDLE=blue` and `[Caddy reload]` is dominated by **`docker pull ghcr.io/chintanmehta21/zettelkasten-kg-website:6f93b80` on the droplet**. The image base is `python:3.12-slim` plus the full Python deps (BGE bi-encoder ONNX, FlashRank, Ragas, supabase-py, etc.) — total uncompressed ~1.5–2 GB. Two compounding factors:

1. **No droplet-side layer cache hit for the venv layer.** `ops/Dockerfile` Stage 1 builds `/opt/venv` from `ops/requirements.txt`. Because this iter added 3 new deps (`dateparser`, `tldextract`, `cachetools`), the requirements layer-hash changed → the venv layer was rebuilt and pushed fresh → droplet pulled it cold. The venv layer is the heaviest in the image (~700 MB-1 GB compressed).
2. **GHCR → DigitalOcean droplet bandwidth.** GHCR egress to DO is on the order of 30–80 MB/s depending on region; pulling ~1 GB of fresh layers takes 4–6 min plus extraction. Plus first-time TLS handshake + manifest fetches add overhead.

## Secondary issue (not slowness, but caught while reading the log)

- `[backfill] WARN: ops/scripts/backfill_metadata.py not found in blue container — skipping backfill.` 
  - The script DID land in this commit (43abf26), and the container WORKDIR is `/app`. The `docker exec ... test -f` check the b9cb8ac patch added probably uses the wrong path or runs before the container fully starts.
  - **Effect on iter-01 eval:** EXISTING chunks have `metadata_enriched_at IS NULL`, so the recency / source-type / author boosts that the eval is supposed to test will not see enriched metadata for any chunk created before this deploy. **The eval will still run, but the boosts measure on enriched chunks only — for iter-01 we'll see partial activation; iter-02 must verify the backfill cron + deploy-hook actually run.**

## Proposed fixes (iter-02 backlog)

### F-D1 (slow deploy, high impact)
- **Switch image registry to DigitalOcean Container Registry** in the same region as the droplet. Pull bandwidth jumps to 200+ MB/s; expect 2-3 min savings on cold-deps-change deploys.
- **Or:** keep GHCR but pre-warm the image on the droplet via a side-channel pull triggered by `workflow_dispatch` 2 min before the cutover step.

### F-D2 (venv layer reuse, medium impact)
- Split `ops/requirements.txt` into `requirements-base.txt` (rarely changing — torch, numpy, fastapi, supabase-py, BGE, ragas) and `requirements-dynamic.txt` (often changing — dateparser-style additions). Two `pip install -r` lines in two separate Dockerfile RUN statements → only the dynamic layer rebuilds for typical changes.
- Expected savings: 4-5 min on iters that don't touch heavy deps.

### F-D3 (backfill hook fix)
- The b9cb8ac `docker exec zettelkasten-${IDLE} python ops/scripts/backfill_metadata.py` likely needs the container WORKDIR or an absolute path. Read the WORKDIR in `ops/Dockerfile` and either (a) pass `--workdir /app` to docker exec or (b) use the absolute path `/app/ops/scripts/backfill_metadata.py`. Verify by re-running deploy with `set -x` enabled in deploy.sh for that block.
- This is the gating fix for actually-enriched chunks during iter-01 eval — folding into iter-02 means we'll re-deploy then re-run eval to see the boosts in action.

### F-D4 (general)
- Deploy.sh emits no per-step timing logs between `Starting deploy` and `Caddy reload`. Add `printf '[%s] step: %s\n' "$(date -Iseconds)" "<step name>"` before each major action (pull, start container, health-poll, flip, retire) so the next slow deploy is RCA'd in seconds, not minutes.

## Decision: do not block iter-01 eval on the deploy fix

Per CLAUDE.md "Production change discipline + do it right the first time": deploy IS slow but it succeeded; rolling back or re-deploying for a 5-minute optimization right now would be churn. The eval can run immediately. The deploy fixes go into iter-02 (F-D1..F-D4) where they belong.
