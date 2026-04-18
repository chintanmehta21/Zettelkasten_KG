# mem-vault — obsidian_vault-db980c8de9f4

> Auto-generated on 2026-04-18T13:07:21.122Z.  Refreshed every session start.

This folder is a **read-only mirror** of this project's entry in the mem-vault
memory store.  Nothing in this folder is authoritative — the real database is
the SQLite file below.

## Project

| Field | Value |
|---|---|
| Project root | `C:\Users\LENOVO\Documents\Claude_Code\Projects\Obsidian_Vault` |
| Project slug | `obsidian_vault-db980c8de9f4` |
| Vault DB | `C:\Users\LENOVO\.mem-vault\projects\obsidian_vault-db980c8de9f4\vault.db` |
| Observations | 2 |
| Chapters | 0 |
| Sessions | 6 |
| Cached symbols | 0 |

## Shared across

- Claude Code (app) — via `.mcp.json` in the mem-vault plugin
- Claude Code CLI — same `.mcp.json`
- Codex — via `~/.codex/config.toml` → `[mcp_servers.mem-vault]`

All three clients open the **same** `vault.db` for this project because they
resolve the same project slug from the same CWD.

## Quick queries

From this project's root:

```bash
# Inside any Claude/Codex session, just ask:
/mem-vault:mem-vault search <term>
/mem-vault:mem-vault recent
/mem-vault:mem-vault status

# Or directly via CLI (from this project root):
node "$CLAUDE_PLUGIN_ROOT/server/index.js" search --q "<term>"
node "$CLAUDE_PLUGIN_ROOT/server/index.js" timeline --limit 25
node "$CLAUDE_PLUGIN_ROOT/server/index.js" mirror   # rebuilds this folder
```

## What's in this folder

| File | Purpose |
|---|---|
| `README.md` | This file (auto-regenerated). |
| `recent.md` | Last 25 observations in human-readable form. |
| `.gitignore` | Suggested rules (defaults to ignoring `recent.md` which changes often). |

To stop generating this folder, set `mirror: false` in
`.claude/mem-vault.local.md` or delete the folder (mem-vault will only
re-create it if this feature is enabled).

## Memory types

| Type | Meaning | Auto-pruned? |
|---|---|---|
| `feature` | New capability added | never |
| `bugfix` | Bug fixed | never |
| `refactor` | Structural change | never |
| `change` | Edit/write observation | no |
| `decision` | Explicit decision recorded | never |
| `discovery` | Insight or learning | never |
| `capture` | Auto-captured tool call | yes (after 30d via `consolidate-memory`) |
| `note` | Free-form user note | no |
