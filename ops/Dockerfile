# syntax=docker/dockerfile:1.7

# --- Stage 1: builder -------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY ops/requirements.txt /tmp/requirements.txt
# Weekly image rebuild is the freshness strategy for yt-dlp (and other
# pinned floors). The yt-dlp-freshness.yml workflow runs every Monday at
# 05:00 UTC and fails the job if PyPI is more than 21 days ahead of the
# installed version, prompting a `pip install -U yt-dlp[default]`-style
# bump + image rebuild.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r /tmp/requirements.txt

# pip already byte-compiles every wheel it installs, so this pass adds 0 files
# today (measured: 10269 .py / 10269 .pyc). Kept as a guard for any .py pip
# skips; `|| true` because compileall exits 1 on a single un-compilable file
# and would hard-fail the build for no functional reason.
RUN python -m compileall -q -j 0 /opt/venv || true

# Fetch the int8 BGE reranker from HF Hub at build time.
# Migrated out of Git LFS (LFS bandwidth quota became a deploy blocker).
# HF_TOKEN is mounted as a build secret — never lands in any image layer.
# 2026-08-01: the repo is PUBLIC (api: private:false, gated:false), so the
# token is NOT access control — it is rate-limit identity. Anonymous resolver
# quota is 3000 req/5min shared *per source IP* and GH runners share Azure
# egress; authenticating moves us to our own 5000 req/5min bucket. HF names a
# missing token the #1 cause of CI rate-limiting. required=false so tokenless
# local builds still work.
# Pin the immutable commit, not mutable `main`: a rewrite of the HF repo must
# not silently change production bytes on the next build. sha256 replaces the
# old `test -s`, which passed on a 1-byte file. Digest confirmed equal to the
# artifact already shipping in the live image.
# Output dir is consumed by the runtime stage via COPY --from=builder below.
ARG HF_RERANKER_REPO=Zettelkasten/bge-reranker
ARG HF_RERANKER_FILENAME=bge-reranker-base-int8.onnx
ARG HF_RERANKER_REVISION=8cb5ae0374a0987b8e9562957852a2995272c08f
ARG HF_RERANKER_SHA256=906fce99cf9fcae4ba3669ed799a391e01271fe3bc981054896f11ee45920c39
ENV HF_HUB_DISABLE_TELEMETRY=1
RUN --mount=type=secret,id=hf_token,required=false \
    REPO="${HF_RERANKER_REPO}" FNAME="${HF_RERANKER_FILENAME}" \
    REV="${HF_RERANKER_REVISION}" \
    HF_TOKEN="$(cat /run/secrets/hf_token 2>/dev/null || true)" \
    python -c "import os; from huggingface_hub import hf_hub_download; \
hf_hub_download(repo_id=os.environ['REPO'], filename=os.environ['FNAME'], \
revision=os.environ['REV'], local_dir='/tmp/hf-models', \
token=os.environ.get('HF_TOKEN') or None)" \
    && echo "${HF_RERANKER_SHA256}  /tmp/hf-models/${HF_RERANKER_FILENAME}" \
       | sha256sum -c -

# --- Stage 2: runtime -------------------------------------------------------
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="zettelkasten-kg-website" \
      org.opencontainers.image.description="Zettelkasten Knowledge Graph Web UI" \
      org.opencontainers.image.source="https://github.com/chintanmehta21/Zettelkasten_KG" \
      org.opencontainers.image.licenses="MIT"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini curl libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# iter-03: bake reranker model artifacts (int8 BGE + FlashRank stage-1) into
# the image so /app/models is read-only at runtime. Eliminates the host-state-
# drift class of bug that defeated iter-03-stale (model file silently missing
# on the droplet -> lazy fp32 fallback ate 1 GB RSS per worker).
# 2026-05-03: bge-reranker-base-int8.onnx now comes from HF Hub, fetched in
# the builder stage. Everything else (tokenizer, calibration, FlashRank
# stage-1) still ships from the repo's models/ dir.
# Copied ahead of website/ because both layers are static: models/ from the
# build context is ~52 MB (the three big .onnx/bge_export entries are excluded
# by .dockerignore) and the builder-stage reranker below is 279 MB / 266 MiB.
# Keeping the pair here means commit-only rebuilds reuse ~332 MB of layers
# instead of re-materialising them behind a changed website/.
COPY --chown=appuser:appuser models/ /app/models/
COPY --from=builder --chown=appuser:appuser \
     /tmp/hf-models/bge-reranker-base-int8.onnx /app/models/bge-reranker-base-int8.onnx

# D-1: ship the migration runner + SQL files so deploy.sh can run
# `python ops/scripts/apply_migrations.py` from inside the new image
# before the blue/green flip. Also includes ops/scripts/backfill_metadata.py
# and the existing post-cutover backfill scripts referenced by deploy.sh.
#
# Phase 8.5 v2-purge (2026-05-11): deploy runs `apply_migrations.py --v2`
# against supabase/website/_v2/*.sql + expected_schema.json. The legacy
# kg_public/migrations/ tree was archived to migrations_archived_2026-05-11/
# and is no longer copied into the image — it's unrunnable (every file
# references dropped public.kg_* tables) and not referenced by any runtime
# script with --v2.
COPY --chown=appuser:appuser ops/scripts/ ops/scripts/
COPY --chown=appuser:appuser supabase/website/_v2/ \
     supabase/website/_v2/
# expected_users.json: zettels_routes._zoro_user_id() reads this at runtime
# to map anonymous captures to the canonical Zoro user. Without it the app
# falls back to a sentinel UUID that is not a real profile row, which then
# breaks anonymous pricing metering with an FK violation.
COPY --chown=appuser:appuser ops/deploy/expected_users.json \
     ops/deploy/expected_users.json

# Application code -- changes on nearly every commit, copied last so the
# heavier / more static layers above stay cached.
COPY --chown=appuser:appuser website/ website/
COPY --chown=appuser:appuser run.py ./
COPY --chown=appuser:appuser pyproject.toml ./

# Precompile APP bytecode. The runtime rootfs is read-only and
# PYTHONDONTWRITEBYTECODE=1 is set, so without this CPython silently re-parses
# all ~450 website/ modules from source on EVERY start (measured 1.92s) --
# SourceFileLoader.set_data swallows the read-only write failure with no error.
# checked-hash, not default timestamp mode: immune to mtime rewriting if
# BuildKit reproducible-builds is ever enabled. No `|| true` unlike the venv
# pass: a syntax error in our own code must fail the BUILD, not the cutover.
RUN python -m compileall -q -j 0 --invalidation-mode checked-hash \
        /app/website /app/run.py /app/ops/scripts

RUN mkdir -p /app/kg_output /app/bot_data \
    && chown -R appuser:appuser /app/kg_output /app/bot_data

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=10000 \
    PROMETHEUS_MULTIPROC_DIR=/app/var/prom

# Multiprocess Prometheus exposition needs a shared directory each worker
# writes its metrics shards to. Phase 4 / Task 4.6 originally placed this
# at /tmp/prom_multiproc; on 2026-05-25 the Naruto live-test repro caught
# the host-side systemd-tmpfiles / compose-tmpfs class of bug wiping /tmp
# mid-process, raising FileNotFoundError out of Counter.labels(...).inc().
# Moved to /app/var/prom (in-image, app-namespaced) so no /tmp cleaner can
# reach it. Django-Prometheus docs name `/run` or `/var/run` as the
# canonical alternatives; we go one step further and namespace under the
# app's own /app/var/ tree.
RUN mkdir -p /app/var/prom && chown -R appuser:appuser /app/var/prom

EXPOSE 10000

USER appuser

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl --silent --show-error --fail --max-time 2 http://127.0.0.1:10000/api/health || exit 1

ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown
LABEL org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILD_DATE}"

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "run.py"]
