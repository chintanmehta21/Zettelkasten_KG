#!/usr/bin/env bash
# Auto-discover secrets from new_envs.txt and sync to GitHub Environment.
#
# Source of truth:
#   new_envs.txt — every KEY:VALUE line under a "=== SECRETS: * ===" section
#   is synced. Lines under LOCAL/PUBLIC/DOCS sections are ignored.
#
# Rename directive:
#   Prepend a "# gh-name: NEW_NAME" comment ABOVE a KEY:VALUE line to upload
#   that key under a different name in GitHub. Used for keys that conflict
#   with GH's reserved GITHUB_ prefix (e.g., GITHUB_TOKEN_FOR_NOTES must
#   upload as GH_TOKEN_FOR_NOTES).
#
# Empty values:
#   Lines with empty values (e.g. "FOO:") are skipped, NOT uploaded as
#   empty strings. This lets you commit placeholders for keys you haven't
#   filled in yet without overwriting existing GH secrets.
#
# Special case:
#   DROPLET_SSH_KEY is uploaded from ~/.ssh/zettelkasten_deploy, NOT from
#   new_envs.txt. The multi-line value in new_envs.txt is a local backup.
#
# Usage:  bash ops/scripts/set_github_secrets.sh
#
# Requirements:
#   - gh CLI authenticated with `repo` scope
#   - new_envs.txt in repo root
#   - ~/.ssh/zettelkasten_deploy for DROPLET_SSH_KEY

set -euo pipefail

REPO="chintanmehta21/Zettelkasten_KG"
ENV_NAME="production"
SRC_FILE="new_envs.txt"
SSH_KEY_FILE="$HOME/.ssh/zettelkasten_deploy"

if [ ! -f "$SRC_FILE" ]; then
  echo "ERROR: $SRC_FILE not found" >&2
  exit 1
fi

if [ ! -f "$SSH_KEY_FILE" ]; then
  echo "ERROR: $SSH_KEY_FILE not found" >&2
  exit 1
fi

DRY_RUN="${DRY_RUN:-0}"

set_secret() {
  local name="$1"
  local value="$2"
  if [ "$DRY_RUN" = "1" ]; then
    local bytes
    bytes=$(printf '%s' "$value" | wc -c | tr -d ' ')
    echo "  [dry-run] would set $name (${bytes} bytes)"
    return
  fi
  printf '%s' "$value" | gh secret set "$name" \
    --env "$ENV_NAME" --repo "$REPO" --body -
  echo "  set $name"
}

set_secret_file() {
  local name="$1"
  local path="$2"
  if [ "$DRY_RUN" = "1" ]; then
    local bytes
    bytes=$(wc -c < "$path" | tr -d ' ')
    echo "  [dry-run] would set $name from $path (${bytes} bytes)"
    return
  fi
  gh secret set "$name" --env "$ENV_NAME" --repo "$REPO" < "$path"
  echo "  set $name (from file)"
}

echo "Populating $ENV_NAME secrets for $REPO from $SRC_FILE..."
echo ""

category=""
section=""
pending_rename=""
count_set=0
count_skipped_empty=0
count_renamed=0

while IFS= read -r line || [ -n "$line" ]; do
  # Strip trailing carriage returns (CRLF files)
  line="${line%$'\r'}"

  # Section headers: === CATEGORY: NAME ===
  if [[ "$line" =~ ^===[[:space:]]*([A-Z]+):[[:space:]]*(.+[^[:space:]])[[:space:]]*===$ ]]; then
    category="${BASH_REMATCH[1]}"
    section="${BASH_REMATCH[2]}"
    pending_rename=""
    if [ "$category" = "SECRETS" ]; then
      echo "── [$section] ──────────────────────"
    fi
    continue
  fi

  # gh-name directive: # gh-name: NEW_NAME
  if [[ "$line" =~ ^#[[:space:]]*gh-name:[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*$ ]]; then
    pending_rename="${BASH_REMATCH[1]}"
    continue
  fi

  # Comments and blank lines — blank lines break pending_rename adjacency
  if [[ -z "$line" ]]; then
    pending_rename=""
    continue
  fi
  if [[ "$line" =~ ^# ]]; then
    continue
  fi

  # Only process KEY:VALUE lines inside SECRETS sections
  if [ "$category" != "SECRETS" ]; then
    pending_rename=""
    continue
  fi

  # Parse KEY:VALUE (first colon splits; value may contain further colons)
  if [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*):(.*)$ ]]; then
    key="${BASH_REMATCH[1]}"
    value="${BASH_REMATCH[2]}"

    if [ -n "$pending_rename" ]; then
      upload_name="$pending_rename"
      count_renamed=$((count_renamed + 1))
    else
      upload_name="$key"
    fi
    pending_rename=""

    if [ -z "$value" ]; then
      echo "  skip $upload_name (empty)"
      count_skipped_empty=$((count_skipped_empty + 1))
      continue
    fi

    set_secret "$upload_name" "$value"
    count_set=$((count_set + 1))
  fi
done < "$SRC_FILE"

echo ""
echo "── [DROPLET_SSH_KEY from file] ──────"
set_secret_file DROPLET_SSH_KEY "$SSH_KEY_FILE"
count_set=$((count_set + 1))

echo ""
echo "Done."
echo "  $count_set secret(s) uploaded"
echo "  $count_skipped_empty empty value(s) skipped"
echo "  $count_renamed rename(s) applied via # gh-name directive"
echo ""
echo "Verifying..."
gh secret list --env "$ENV_NAME" --repo "$REPO"
