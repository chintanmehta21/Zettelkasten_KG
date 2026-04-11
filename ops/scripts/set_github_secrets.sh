#!/usr/bin/env bash
# One-shot script to populate GitHub production environment secrets from
# new_envs.txt. Does NOT echo any secret values.
#
# Usage:  bash ops/scripts/set_github_secrets.sh
#
# Requirements:
#   - gh CLI authenticated with `repo` scope
#   - new_envs.txt in the repo root
#   - $HOME/.ssh/zettelkasten_deploy (for DROPLET_SSH_KEY)

set -euo pipefail

REPO="chintanmehta21/Zettelkasten_KG"
ENV_NAME="production"
SRC_FILE="new_envs.txt"
SSH_KEY_FILE="$HOME/.ssh/zettelkasten_deploy"
REDDIT_PLACEHOLDER="skip-not-configured"

if [ ! -f "$SRC_FILE" ]; then
  echo "ERROR: $SRC_FILE not found" >&2
  exit 1
fi

if [ ! -f "$SSH_KEY_FILE" ]; then
  echo "ERROR: $SSH_KEY_FILE not found" >&2
  exit 1
fi

# Read a "KEY:value" single-line entry from new_envs.txt.
# Strips only the first colon to preserve colon-containing values.
read_field() {
  local key="$1"
  grep -m1 "^${key}:" "$SRC_FILE" | sed -E "s|^${key}:||"
}

# Set a single-line secret. Empty values get replaced with placeholder.
set_secret() {
  local name="$1"
  local value="$2"
  if [ -z "$value" ]; then
    value="$REDDIT_PLACEHOLDER"
  fi
  printf '%s' "$value" | gh secret set "$name" \
    --env "$ENV_NAME" --repo "$REPO" --body -
  echo "  set $name"
}

# Set a multi-line secret from a file path.
set_secret_file() {
  local name="$1"
  local path="$2"
  gh secret set "$name" --env "$ENV_NAME" --repo "$REPO" < "$path"
  echo "  set $name (from file)"
}

echo "Populating $ENV_NAME environment secrets for $REPO..."
echo ""

# ── Core app secrets ─────────────────────────────────────────────────
set_secret TELEGRAM_BOT_TOKEN       "$(read_field TELEGRAM_BOT_TOKEN)"
set_secret ALLOWED_CHAT_ID          "$(read_field ALLOWED_CHAT_ID)"
set_secret WEBHOOK_SECRET           "$(read_field WEBHOOK_SECRET)"
set_secret SUPABASE_URL             "$(read_field SUPABASE_URL)"
set_secret SUPABASE_ANON_KEY        "$(read_field SUPABASE_ANON_KEY)"
set_secret GEMINI_API_KEYS          "$(read_field GEMINI_API_KEYS)"

# ── GitHub notes pusher (renamed from GITHUB_*_FOR_NOTES to GH_*_FOR_NOTES) ─
set_secret GH_TOKEN_FOR_NOTES       "$(read_field GITHUB_TOKEN_FOR_NOTES)"
set_secret GH_REPO_FOR_NOTES        "$(read_field GITHUB_REPO_FOR_NOTES)"

# ── GHCR pull token ──────────────────────────────────────────────────
set_secret GHCR_READ_PAT            "$(read_field GHCR_READ_PAT)"

# ── Nexus OAuth providers ────────────────────────────────────────────
set_secret NEXUS_GOOGLE_CLIENT_ID       "$(read_field NEXUS_GOOGLE_CLIENT_ID)"
set_secret NEXUS_GOOGLE_CLIENT_SECRET   "$(read_field NEXUS_GOOGLE_CLIENT_SECRET)"
set_secret NEXUS_GITHUB_CLIENT_ID       "$(read_field NEXUS_GITHUB_CLIENT_ID)"
set_secret NEXUS_GITHUB_CLIENT_SECRET   "$(read_field NEXUS_GITHUB_CLIENT_SECRET)"
set_secret NEXUS_REDDIT_CLIENT_ID       "$(read_field NEXUS_REDDIT_CLIENT_ID)"
set_secret NEXUS_REDDIT_CLIENT_SECRET   "$(read_field NEXUS_REDDIT_CLIENT_SECRET)"
set_secret NEXUS_TWITTER_CLIENT_ID      "$(read_field NEXUS_TWITTER_CLIENT_ID)"
set_secret NEXUS_TWITTER_CLIENT_SECRET  "$(read_field NEXUS_TWITTER_CLIENT_SECRET)"
set_secret NEXUS_TOKEN_ENCRYPTION_KEY   "$(read_field NEXUS_TOKEN_ENCRYPTION_KEY)"

# ── Droplet SSH deploy key (multi-line, from ~/.ssh file) ────────────
set_secret_file DROPLET_SSH_KEY "$SSH_KEY_FILE"

echo ""
echo "Done. Verifying..."
gh secret list --env "$ENV_NAME" --repo "$REPO"
