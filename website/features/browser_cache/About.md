# Browser Cache (Minimal)

This folder contains a tiny browser-side cache for the public (`/`) auth flow.
The goal is stable UX with very low disk usage and no secret persistence.

## What Is Stored

- `localStorage` key: `zk.bc.v1`
  - Compact JSON object with only non-sensitive state.
  - `a`: `1|0` (`allowCredentialStorage`)
  - `h`: `1|0` (`hasLoggedIn`)
  - `l`: landing path (default `/home`)
  - `t`: theme placeholder (blank for now)
  - `u`: update timestamp (ms)
- `sessionStorage` key: `zk.bc.return.v1`
  - Short-lived return path payload:
  - `p`: path
  - `e`: expiry timestamp (ms), TTL = 15 minutes

## Data Safety Rules

- Never store tokens, passwords, API keys, cookies, or full profile payloads.
- Use this cache as a UX hint only, not as security truth.
- Validate redirect paths (`/path` only, reject protocol-relative or absolute URL injection).
- Expire stale data automatically and one-time consume return paths.

## Disk Usage Controls

- `localStorage` payload cap: 256 bytes.
- `sessionStorage` payload cap: 96 bytes.
- If state is default/empty, remove storage keys entirely.
- Keep a single compact blob per storage surface to avoid key sprawl.

## Why These Choices

This aligns with Web Storage and security guidance:

- MDN Web Storage API:
  - https://developer.mozilla.org/en-US/docs/Web/API/Web_Storage_API/Using_the_Web_Storage_API
- MDN storage quotas:
  - https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria
- OWASP HTML5 Security Cheat Sheet:
  - https://cheatsheetseries.owasp.org/cheatsheets/HTML5_Security_Cheat_Sheet.html
