# Vault Sync Options: SyncThing and Alternatives

This document covers how to keep your Obsidian vault (`KG_DIRECTORY`) in sync across your VPS, desktop, and mobile devices. The zettelkasten bot writes notes to the VPS; sync ensures those notes appear everywhere.

---

## Why SyncThing

SyncThing is the recommended solution for this setup:

- **Open source** (MPL-2.0) — no vendor lock-in, auditable code
- **End-to-end encrypted** — data is encrypted in transit between nodes; no third-party can read your notes
- **No cloud dependency** — sync is peer-to-peer; files never pass through a vendor's server
- **Free forever** — no subscription, no storage limits beyond your own disk
- **Conflict handling** — creates `.sync-conflict-*` copies rather than silently overwriting; you decide which version to keep
- **Cross-platform** — Linux, macOS, Windows, iOS (Möbius Sync), Android (native app)

---

## SyncThing Setup Overview (3-Node Config for Obsidian Vault Sync)

The recommended configuration is a three-node network:

```
VPS (bot writes notes here)
  └─ syncs with ──► Desktop (Linux/macOS/Windows — Obsidian installed)
                        └─ syncs with ──► Mobile (iOS/Android — Obsidian Mobile)
```

All three nodes are peers — each can sync directly with any other that is online. The VPS acts as the always-online relay so that mobile and desktop stay in sync even when they are not on the same network.

### Setup Steps

1. **Install SyncThing on VPS**
   ```bash
   # Ubuntu/Debian
   curl -s https://syncthing.net/release-key.txt | sudo gpg --dearmor -o /usr/share/keyrings/syncthing-archive-keyring.gpg
   echo "deb [signed-by=/usr/share/keyrings/syncthing-archive-keyring.gpg] https://apt.syncthing.net/ syncthing stable" | sudo tee /etc/apt/sources.list.d/syncthing.list
   sudo apt update && sudo apt install syncthing
   sudo systemctl enable --now syncthing@$USER
   ```

2. **Install SyncThing on desktop** — download from [syncthing.net/downloads](https://syncthing.net/downloads/) and run; the web UI starts at `http://127.0.0.1:8384`.

3. **Install on mobile** — Android: [SyncThing on F-Droid](https://f-droid.org/en/packages/com.nutomic.syncthingandroid/) or Google Play. iOS: [Möbius Sync](https://www.mobiussync.com/) (paid, ~$2) is the most reliable client.

4. **Share the vault folder** — on the VPS web UI, add the vault directory (your `KG_DIRECTORY` path) as a shared folder and copy the VPS device ID to each peer. Accept the share on desktop and mobile. Set folder type to **Send & Receive** on all nodes.

5. **Point Obsidian** to the synced folder path on desktop and mobile.

> **Tip:** Expose the SyncThing web UI on the VPS only over an SSH tunnel, not publicly, to avoid brute-force attempts:
> `ssh -L 8384:127.0.0.1:8384 user@your-vps`

---

## Alternatives Comparison

| Tool | Cost | E2E Encryption | Platform Support | Conflict Handling | Self-Hosted |
|------|------|----------------|------------------|-------------------|-------------|
| **SyncThing** | Free | ✅ Yes (TLS between peers) | Linux, macOS, Windows, Android, iOS\* | `.sync-conflict-*` copies | ✅ Yes |
| **Obsidian Sync** | $4–$8/mo | ✅ Yes (optional end-to-end) | All Obsidian platforms | Version history (1 yr) | ❌ No |
| **iCloud Drive** | Free–$2.99/mo | ❌ No (server-side only) | macOS, iOS, Windows | Last-write wins | ❌ No |
| **Google Drive** | Free–$2.99/mo | ❌ No (server-side only) | All major platforms | Last-write wins | ❌ No |
| **Dropbox** | Free–$15/mo | ❌ No (server-side only) | All major platforms | Conflicted copy | ❌ No |
| **Resilio Sync** | Free (Home) / $60 (Pro) | ✅ Yes (AES-128) | Linux, macOS, Windows, Android, iOS | Conflicted copy | ✅ Yes (Pro) |

\* iOS support via [Möbius Sync](https://www.mobiussync.com/) (third-party, not official SyncThing).

---

## Trade-offs Summary

**SyncThing**
- ✅ Free, private, open source, no subscription, no size limits
- ✅ Works perfectly with a VPS-based workflow
- ⚠️ Requires initial setup (~15–30 min) and self-hosting on at least one always-on node
- ⚠️ iOS experience is via a third-party app (Möbius Sync), not official

**Obsidian Sync**
- ✅ Seamless first-party integration, zero setup, version history
- ✅ Best iOS/mobile experience
- ⚠️ Costs $4–$8/month; data lives on Obsidian's servers
- ⚠️ Requires an Obsidian account

**iCloud / Google Drive / Dropbox**
- ✅ No setup needed if already subscribed
- ⚠️ Not end-to-end encrypted — provider can read files
- ⚠️ Conflict handling is weak (last-write-wins or silent overwrite)
- ⚠️ Requires third-party plugin for mobile Obsidian (e.g., iSH, a-Shell, Obsidian Git)

**Resilio Sync**
- ✅ Mature, fast BitTorrent-based sync; works on all platforms
- ⚠️ Closed source; free tier has feature limits; Pro requires one-time purchase

---

## Recommendation

| Use case | Recommendation |
|----------|---------------|
| Privacy-first, VPS workflow, no subscription | **SyncThing** (this guide's primary recommendation) |
| Convenience, best mobile UX, willing to pay | **Obsidian Sync** |
| Already on Apple ecosystem, light use | **iCloud Drive** (acceptable for personal use; not private) |
| Team or shared vault | **Obsidian Sync** or **Dropbox** with manual conflict review |

For this bot's intended workflow — notes written to a VPS and synced to all personal devices — **SyncThing is the clear choice**: it is free, private, and pairs naturally with the always-on VPS that runs the bot.
