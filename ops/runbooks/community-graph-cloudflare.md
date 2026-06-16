# Cloudflare Cache Rule — public community graph (`/api/graph?view=global`)

**Status:** PROPOSED — requires operator approval before applying in the
Cloudflare dashboard. This is the CDN half of Part B Phase 1; the origin already
sends `public, max-age=60, s-maxage=300, stale-while-revalidate=600` +
`Vary: Accept-Encoding` and emits no `Set-Cookie` for `view=global`.

## Rule
- **When incoming requests match:** `URI Path equals /api/graph` AND
  `URI Query String contains "view=global"`.
- **Then — Cache eligibility:** *Eligible for cache*.
- **Cache Key → Query String:** *Include only* `view` (ignore all other query
  params: `min_strength`, `limit`, `offset` are folded server-side / not part of
  the public cache identity). This prevents cache fragmentation AND web-cache-
  deception (no `;.css`/`.css` suffix can produce a cacheable variant).
- **Edge TTL:** *Respect origin TTL* (honours `s-maxage=300`).
- **Browser TTL:** *Override to 60s*.
- **Serve stale while revalidating:** *ON*.

## Why no `Vary: Authorization`
Cloudflare ignores every `Vary` value except `Accept-Encoding`. Private safety
for `view=my` rests on `private`/hard-401 + the client dropping Authorization on
global + this rule keying only on path+`view` — never on `Vary`.

## Verify after applying
```bash
# First request warms the edge; second should HIT.
curl -sI "https://zettelkasten.in/api/graph?view=global&min_strength=0.3" | grep -i cf-cache-status
curl -sI "https://zettelkasten.in/api/graph?view=global&min_strength=0.3" | grep -i cf-cache-status
# Expect: cf-cache-status: MISS (or EXPIRED) then HIT.
# Confirm a private call is NEVER cached, and anon view=my is 401:
curl -sI -H "Authorization: Bearer <tok>" "https://zettelkasten.in/api/graph?view=my" | grep -iE 'cf-cache-status|cache-control'
curl -sI "https://zettelkasten.in/api/graph?view=my" | grep -iE 'HTTP/|www-authenticate'
# Expect: authed → cf-cache-status: DYNAMIC/BYPASS, Cache-Control: private; anon → HTTP 401.
```
Cloudflare Free-plan async SWR is non-uniform per open reports — re-verify
`cf-cache-status` behaviour on this zone before relying on stale-serving.
