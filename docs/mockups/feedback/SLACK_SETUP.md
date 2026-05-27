# Slack workspace setup — Feedback feature

One-time operator setup. Required before the implementation PR can deploy. Walkthrough is mobile-friendly (Slack Android app + any mobile browser); a desktop browser works the same way.

> **Why a Slack app and not a webhook?** Incoming Webhooks cannot attach files. The user-uploaded screenshots must be sent through Slack's `files_upload_v2` API, which requires a bot token with `files:write`. The bot also uses `chat:write` to post the Block Kit message. Slack's `files.upload` (the older method) retires **2025-11-12** — no rollback to that path.

---

## Step 1 — Confirm you're an admin on the workspace (Slack Android)

The Slack Android app does **not** show the technical workspace ID (`T...`) in its UI — that's intentional, it's an internal identifier. What you can do on Android is confirm admin status + grab the workspace URL slug.

1. Open the Slack Android app.
2. Tap your workspace name at the top-left.
3. Tap the gear icon → **View workspace settings**.
4. Note the workspace URL (looks like `acme.slack.com`). Keep it handy for Step 3.
5. Scroll the settings page. If you see **"Manage members"** / **"Manage apps"** entries, you're a Workspace Owner or Admin — you can proceed. If those are missing, you're a regular member — ask the admin to install the app on your behalf, or have them promote you for the duration of setup.

---

## Step 2 — Get the channel ID for `#zk-testing` (Slack Android)

The channel ID (`C09ABCDEF1G` format) is what the backend uses to target Slack posts.

1. In Slack Android, open the workspace from Step 1.
2. Open (or create) `#zk-testing`.
3. Tap the channel name at the very top of the conversation.
4. The detail sheet opens. Scroll to **"About"** at the bottom.
5. Tap the row labelled **"Channel ID"** — it copies the ID to your clipboard. Paste it somewhere — looks like `C09ABCDEF1G`.

If you can't find "Channel ID" in About on your version of the Slack app: alternate path — long-press the channel name → **Copy link** → paste; the ID is the last segment of the URL `https://acme.slack.com/archives/C09ABCDEF1G`.

This value is the **`SLACK_CHANNEL_FEEDBACK`** env var.

---

## Step 3 — Create the Slack app (mobile browser is fine)

The Slack app creation flow is web-only. Mobile Chrome / Safari on Android works fine.

1. Open https://api.slack.com/apps in a browser.
2. Sign in with the same Slack account you use on Android (browser-side SSO if you already signed in).
3. Click **Create New App** → **From scratch**.
4. **App Name**: `Zettelkasten Feedback` (this is what users see as the message author in `#zk-testing`).
5. **Pick a workspace**: select the one you confirmed in Step 1.
6. Click **Create App**.

After creation you land on the **App Settings** dashboard for the new app. The top-right shows the **App ID** (`A...`) and the **Workspace** with its ID (`T...`). Note the workspace ID for your records (optional — not used by the backend).

---

## Step 4 — Add the OAuth scopes the bot needs

1. Left nav: **OAuth & Permissions**.
2. Scroll to **Bot Token Scopes** section.
3. Click **Add an OAuth Scope**, then add **both** of these:
   - `chat:write` — to post the feedback message
   - `files:write` — to upload screenshot attachments via `files_upload_v2`
4. Scroll back to the top of **OAuth & Permissions**.
5. Click **Install to Workspace** → review the permissions → **Allow**.
6. After the redirect, the page now shows **Bot User OAuth Token** at the top. Click **Copy**.

The token starts with `xoxb-` and looks like `xoxb-12345678901-1234567890123-abcdefABCDEF...`. This is the **`SLACK_BOT_TOKEN_FEEDBACK`** secret. **Treat it like a password** — anyone with this token can post messages and upload files as your bot.

---

## Step 5 — Add the bot to `#zk-testing` (Slack Android)

A Slack bot can only post to channels it's a member of. Add it:

1. In Slack Android, open `#zk-testing`.
2. Send the message: `/invite @Zettelkasten Feedback` and tap send.

Alternative if `/invite` doesn't auto-resolve the app: tap channel name → **Integrations** → **Add apps** → search **"Zettelkasten Feedback"** → **Add**.

You should see a join notice in the channel like *"Zettelkasten Feedback has joined the channel"*.

---

## Step 6 — Paste secrets into the production droplet

SSH into the droplet (or use the existing deploy workflow). Append to the secret file mounted at `/etc/secrets/api_env`:

```
SLACK_BOT_TOKEN_FEEDBACK=xoxb-PASTE-FROM-STEP-4
SLACK_CHANNEL_FEEDBACK=C09ABCDEF1G   # From step 2
SECRET_FEEDBACK_COOKIE=PASTE-A-32-BYTE-RANDOM-HEX-STRING
```

For `SECRET_FEEDBACK_COOKIE`, generate fresh on the droplet:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

After saving the file, restart the gunicorn container (blue/green deploy on next merge picks up the new env automatically; for a manual restart see `ops/deploy/`).

---

## Step 7 — Smoke test

Once the implementation PR lands, after deploy:

1. Open the live site logged in (or logged out, whichever path you want to test).
2. Click the megaphone in the footer.
3. Fill Subject = `smoke test`, Description = `verifying Slack delivery from <your name> on <date>`.
4. Submit.
5. Switch to Slack Android → `#zk-testing` → you should see the Block Kit message within ~2 seconds.

If you don't see it:
- Check droplet logs: `gh workflow run read_recent_logs.yml` (CLAUDE.md infrastructure section).
- Common failures:
  - **`401 invalid_auth`** → `SLACK_BOT_TOKEN_FEEDBACK` is misset.
  - **`channel_not_found`** → `SLACK_CHANNEL_FEEDBACK` ID is wrong, or you skipped Step 5 (bot isn't in the channel).
  - **`missing_scope: files:write`** → re-do Step 4 with both scopes; reinstall the app.

---

## Notes

- **Token rotation**: rotate `SLACK_BOT_TOKEN_FEEDBACK` every ~90 days. If the token leaks: api.slack.com → your app → **Settings** → **Manage Distribution** → **Reset Token** → re-install → update the env var.
- **Multi-workspace**: this setup targets one Slack workspace. If you later want feedback posted to multiple workspaces (e.g., a separate community Slack), the app needs to be installed once per workspace; the backend would need a per-workspace token map. Not in scope for v1.
- **Local dev**: install the app to a personal test workspace, set the env vars in your local `.env`, and run with `ENV=dev`. The feature won't load if `SLACK_BOT_TOKEN_FEEDBACK` is empty — the route returns 503.
- **Privacy**: Slack-hosted images are visible to everyone in the workspace with access to `#zk-testing`. They are NOT publicly fetchable (`slack_file` blocks reference an internal file ID, not a signed URL). Workspace retention applies to the messages.
