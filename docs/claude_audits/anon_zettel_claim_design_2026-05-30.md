# Item 6 — Anon→User Zettel Claim (Dual-Ownership) — Design Spec

**Status:** SPEC-FIRST — awaiting operator approval before any code is written.
**Date:** 2026-05-30
**Scope:** When an anonymous visitor (whose zettels are stored under the canonical
"Zoro" user) signs in during the same browser session, the zettel(s) they created
that session are *also* assigned to the new user's workspace. Zoro keeps its rows.

This doc is grounded in verified code anchors (file:line confirmed 2026-05-30). The
**Phase-0 Verification Checklist** (§12) lists what must be re-confirmed at build start.

---

## 1. Approved decisions (locked in chat)

| Knob | Decision |
|---|---|
| Transfer model | **Dual-row insert** — keep Zoro's `workspace_zettels` row + INSERT a sibling row in the new user's workspace pointing at the same `canonical_zettel_id`. |
| Anon-session id | **Option C** — server-issued HttpOnly HMAC-signed cookie `zk_anon_sid` (canonical) + localStorage mirror (cross-tab sync / OAuth echo / recovery). |
| Claim caps | **Conservative** — 24h claim window from session creation; ≤20 zettels per claim call; rate-limit `/claim` 3/min/IP; **first-claim-wins** (a session's zettels can be claimed by exactly one account, immutable). |
| Quota | **Enforce at claim, never surface 402.** Each claimed zettel consumes 1 unit of the new user's `ZETTEL` entitlement; if the balance runs out, **cap at remaining** and silently claim fewer. New user's free tier is 2 zettels/day — claiming deducts from that. |

Two items are **NOT yet approved** and are flagged inline for your decision (§5.4, §7.4):
audit/lineage table, and whether anon Graph visibility changes.

---

## 2. Current state (verified)

| Concern | Reality (file:line) |
|---|---|
| Anon→Zoro mapping | `_effective_user_id(user)` falls back to Zoro when anon — [zettels_routes.py:204](website/api/zettels_routes.py:204). Zoro id `a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e` from `ops/deploy/expected_users.json`. |
| Persist target | `repo.upsert_canonical_zettel` writes the workspace row under Zoro's default workspace — [persist.py:839](website/core/persist.py:839). |
| `workspace_zettels` schema | `id, workspace_id, canonical_zettel_id, ai_summary, …, deleted_at`; **UNIQUE(workspace_id, canonical_zettel_id)**; **no `anon_sid` / provenance column** — [02_content_schema.sql:74](supabase/website/_v2/02_content_schema.sql:74). |
| Claim RPC | **Does not exist** (grep: zero `claim`/`transfer`/`link_anon` in `_v2/*.sql` + `supabase_v2/*.py`). |
| Client anon-session id | **Does not exist** (grep: zero `anon_sid`/`zk-anon` in `website/mobile/js/`, `website/features/user_auth/js/`). Only `sessionStorage['zk_just_captured']` (one-shot, per-tab). |
| Quota gate | `require_entitlement(Meter.ZETTEL, user, action_id=…)` atomically reserves+consumes via `get_functional_gates().reserve_and_consume(...)`, **raises HTTP 402** `quota_exhausted` on denial — [entitlements.py:92](website/features/user_pricing/entitlements.py:92). `consume_entitlement` is a **no-op** (entitlements.py:151) — do **not** rely on it to deduct. |
| Cookie infra | `set_cookie` precedent at [app.py:349](website/app.py:349); `SessionMarkerCookieMiddleware` registered [app.py:554](website/app.py:554) — extend this pattern for `zk_anon_sid`. |
| Latest migration | `83_*` — new migration is **`84_anon_zettel_claim.sql`** (+ `.down.sql`). |

**Riskiest gap (scout synthesis):** no provenance column, no claim RPC, no client session id — this is the only L-effort piece; everything in items 1–5 was XS.

---

## 3. End-to-end flow (target)

```
Anon /m/ capture ──► POST /api/zettels/add (no token)
   server: effective_user = Zoro; tag the new workspace_zettels row with anon_sid=<cookie>
   client: zk_anon_sid cookie already set by middleware on first /m/* hit

Anon signs in (Google/Apple/email) — same browser session
   1. before redirect: server stashes anon_sid into OAuth `state` (HMAC), or email-login reads cookie directly
   2. callback: new auth session minted; session cookie ROTATED (OWASP A07:2025)
   3. client (or callback) → POST /api/zettels/claim-anon-session { anon_session_id }
   4. claim RPC (single tx): for each Zoro row tagged anon_sid (≤20, <24h, first-claim-wins):
        - require_entitlement(ZETTEL, new_user)  → consumed? dual-row INSERT into new user's ws : STOP (cap)
        - mark anon_sessions.claimed_by = new_user (immutable)
   5. BroadcastChannel('zk-auth') tells other tabs to refetch
```

---

## 4. Schema migration — `84_anon_zettel_claim.sql`

### 4.1 Provenance column on `workspace_zettels`
```sql
ALTER TABLE content.workspace_zettels
  ADD COLUMN IF NOT EXISTS anon_sid uuid;     -- NULL for normal authed writes
CREATE INDEX IF NOT EXISTS ix_workspace_zettels_anon_sid
  ON content.workspace_zettels (anon_sid) WHERE anon_sid IS NOT NULL;  -- partial: only Zoro-anon rows
```
Only rows written while `effective_user == Zoro` carry `anon_sid`. The partial index keeps the claim lookup O(rows-for-this-session).

### 4.2 `content.anon_sessions` (first-claim-wins + 24h window)
```sql
CREATE TABLE IF NOT EXISTS content.anon_sessions (
  id                uuid PRIMARY KEY,            -- == zk_anon_sid cookie value (UUIDv7)
  created_at        timestamptz NOT NULL DEFAULT now(),
  last_seen_at      timestamptz NOT NULL DEFAULT now(),
  claimed_by_user   uuid REFERENCES core.profiles(id),  -- NULL until claimed; set once (immutable)
  claimed_at        timestamptz,
  ip_hash           text,    -- sha256(ip+salt) — abuse forensics, not PII
  ua_hash           text
);
```
First-claim-wins is enforced by `SELECT … FOR UPDATE` on this row inside the claim tx + the
`claimed_by_user IS NULL` guard. 24h window = `created_at > now() - interval '24 hours'`.

### 4.3 GRANTs (mandatory — V2-grants rule)
The 09–51 grant gap caused the 2026-05-21 outage. This migration **must** include:
```sql
GRANT SELECT, INSERT, UPDATE ON content.anon_sessions TO service_role;
GRANT EXECUTE ON FUNCTION content.claim_anon_zettels(uuid, uuid) TO service_role;
-- column add inherits workspace_zettels grants (no new grant needed for the column)
```

### 4.4 Down migration `84_*.down.sql`
Drop the RPC, the table, the index, the column (reverse order). Reversible.

### 4.5 RLS
`anon_sessions` is service-role-only (no anon/authenticated policy) — the claim RPC is
`SECURITY DEFINER` and the only reader/writer. `workspace_zettels` RLS is unchanged;
the new user's sibling row lands in *their* workspace, so existing per-workspace RLS
already isolates it. **Zoro's row is never exposed to the new user** — only the
`canonical_zettel_id` is shared (public, dedup key), never Zoro's `workspace_id`.

---

## 5. Anon-session id (Option C)

### 5.1 Cookie
`zk_anon_sid` — value = UUIDv7; `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000` (30d);
**HMAC-signed** (server secret) so a forged/guessed value is rejected. Set by middleware on the
first `/m/*` response if absent (extend `SessionMarkerCookieMiddleware`, [app.py:554](website/app.py:554)).
ITP-safe: Safari's 7-day eviction hits script-writable storage, **not** server `Set-Cookie` HttpOnly
first-party cookies (WebKit, verified in research).

### 5.2 localStorage mirror
`zk.anon.sid` = same UUID, written by JS for: (a) BroadcastChannel cross-tab sync, (b) recovery if
the cookie is wiped, (c) sending in the claim body when the callback can't read the cookie. **Non-authoritative** — the server trusts the signed cookie (or HMAC-verified `state`), never the raw localStorage value.

### 5.3 OAuth round-trip + rotation
1. On "Sign in", server reads `zk_anon_sid` (cookie) → embeds it in OAuth `state` as `HMAC(csrf‖anon_sid)` (never raw sid in the URL).
2. Callback verifies HMAC, recovers `anon_sid`, runs the claim, then **rotates** the session cookie (new random id post-login) and clears `zk_anon_sid`.
3. Email/password login: no redirect — read the cookie directly, then claim.

### 5.4 ⚠ NOT approved — anon Graph
Item 5 already serves anon the **global** file-store graph. This spec does **not** change that.
Flagging only because §3 touches the anon→auth boundary: no Graph behavior changes here unless you say so.

---

## 6. Capture-time tagging
In the add-zettel persist path, when `effective_user_id == Zoro` AND a valid `zk_anon_sid` is present:
- upsert/insert `content.anon_sessions(id=anon_sid, ip_hash, ua_hash)` (ON CONFLICT touch `last_seen_at`).
- pass `anon_sid` into `upsert_canonical_zettel` so the Zoro `workspace_zettels` row carries it.
Authed writes pass `anon_sid = NULL`. **No behavior change for authed users.**

---

## 7. Claim RPC — `content.claim_anon_zettels(p_new_user uuid, p_anon_sid uuid)`

`SECURITY DEFINER`, `SET search_path = content, core`. Single transaction:

```
1. SELECT … FROM content.anon_sessions WHERE id = p_anon_sid FOR UPDATE;
   - not found OR created_at < now()-24h      → return {claimed:0, reason:'expired'}
   - claimed_by_user IS NOT NULL              → return {claimed:0, reason:'already_claimed'}  (first-claim-wins)
2. SELECT id, canonical_zettel_id, ai_summary, user_tags
     FROM content.workspace_zettels
    WHERE anon_sid = p_anon_sid AND workspace_id = <Zoro ws> AND deleted_at IS NULL
    ORDER BY created_at LIMIT 20 FOR UPDATE SKIP LOCKED;     -- cap 20
3. For each candidate: INSERT into the NEW user's default workspace
     (workspace_id=<new ws>, canonical_zettel_id, copy ai_summary/user_tags, added_via='claim')
     ON CONFLICT (workspace_id, canonical_zettel_id) DO NOTHING;   -- user already had it → skip
4. UPDATE anon_sessions SET claimed_by_user=p_new_user, claimed_at=now() WHERE id=p_anon_sid;
5. RETURN the list of canonical_zettel_ids actually inserted (for the quota loop + client refresh).
```

**Quota is NOT inside the RPC** — it's enforced in the Python endpoint (§8) because `require_entitlement`
lives in the app layer and must catch-to-cap. The RPC returns *candidates inserted*; the endpoint
pre-checks quota per zettel and only asks the RPC to insert the affordable ones (or the RPC inserts and
the endpoint reconciles — see §8 for the exact ordering decision).

### 7.4 ⚠ NOT approved — audit/lineage table
Research recommended a `content.zettel_claim_events` audit row per claim (forensics, anti-abuse, undo).
You chose **plain dual-row** over the hybrid-with-lineage option, so this spec **omits** it. Say the word
to add it (one INSERT in step 4, one table + GRANT) — recommended for abuse review but not required.

---

## 8. Claim endpoint — `POST /api/zettels/claim-anon-session`

Body: `{ anon_session_id: uuid }` (or read from cookie). Idempotent. Rate-limit **3/min/IP**.

```
1. Verify signed cookie zk_anon_sid == body (or HMAC state). Mismatch → 200 {claimed:0} (no info leak).
2. Resolve new_user from the authenticated session (must be authed; else 401).
3. Determine claimable candidates (Zoro rows for this anon_sid, ≤20, <24h, not already claimed).
4. QUOTA LOOP (catch-to-cap, never 402):
     affordable = []
     for z in candidates:
        try:
            await require_entitlement(Meter.ZETTEL, new_user, action_id=f"claim-{z.canonical_id}")
            affordable.append(z)
        except HTTPException as e:           # 402 quota_exhausted
            if e.status_code == 402: break    # cap at remaining — STOP, do not propagate
            raise
5. Call claim RPC for `affordable` only → dual-row inserts + marks session claimed.
6. Return 200 { claimed: len(inserted), capped: len(candidates) > len(affordable) }.
```

The user **never sees a 402** — the loop converts "quota exhausted" into "claimed fewer". With the common
case (1 anon zettel, fresh 2/day balance), exactly 1 unit is deducted and 1 row inserted, matching the
operator's stated intent.

> **Ordering nuance to settle at build:** consume-then-insert (above) vs insert-then-reconcile. Consume-then-insert
> avoids inserting rows we can't pay for; the cost is `require_entitlement` is per-zettel. With cap=20 that's ≤20
> gate calls — acceptable. Lock this in Phase 0.

---

## 9. Client wiring
- `auth-core.js` / a small `anon-session.js`: mirror the cookie UUID into `zk.anon.sid`; include it in `/api/zettels/add` and `/claim-anon-session` bodies.
- On successful sign-in (the existing `onAuthStateChange` SIGNED_IN path): POST `/claim-anon-session`, then `BroadcastChannel('zk-auth').postMessage({type:'claimed'})`.
- Other tabs listen and refetch `/api/zettels`.
- Mobile zettels page: after claim, the just-captured local card is reconciled with the now-owned server row.

---

## 10. Abuse mitigations (conservative set)
| Vector | Mitigation |
|---|---|
| Steal/guess `zk_anon_sid` → claim victim's zettels | HttpOnly (XSS can't read) + HMAC signature (forgery rejected) + UUIDv7 (unguessable). |
| Multi-account laundering (same session → 2 accounts) | first-claim-wins: `anon_sessions.claimed_by_user` set once, `FOR UPDATE` serializes; 2nd account gets `{claimed:0,'already_claimed'}`. |
| Claim flood / brute force session ids | rate-limit 3/min/IP on `/claim`; 24h window rejects stale sessions; cap 20/call. |
| CSRF on `/claim` | SameSite=Lax cookie + authenticated session required. |
| Quota bypass via bulk claim | per-zettel `require_entitlement` deducts real units; cap-at-remaining. |

---

## 11. Test matrix (TDD — write first)
- **BOLA:** anon_sid A's zettels never claimable by a session presenting anon_sid B; UUID-leak assertions (OWASP API1:2023).
- **First-claim-wins:** two accounts race to claim one session → exactly one succeeds, other gets `already_claimed`.
- **Quota cap:** new user with 1 remaining unit claims 3 anon zettels → 1 inserted, 2 left under Zoro, **no 402** surfaced.
- **24h window:** session created 25h ago → `{claimed:0,'expired'}`.
- **Cap 20:** 25 anon zettels → ≤20 claimed.
- **Idempotency:** double POST `/claim` → same result, no duplicate rows (UNIQUE + `claimed_by` guard).
- **RLS isolation:** new user cannot read Zoro's `workspace_id`; only the shared `canonical_zettel_id`.
- **Multi-tab:** sign-in in tab 2 → tabs 1/3 refetch via BroadcastChannel.
- **Authed no-op:** normal authed capture writes `anon_sid=NULL`, claim path untouched.

---

## 12. Phase-0 verification checklist (confirm before writing code)
1. Re-read `content.upsert_canonical_zettel` RPC — confirm where to thread `anon_sid` (param vs post-insert UPDATE).
2. Confirm Zoro's **default workspace_id** resolution (`get_default_workspace_id`) and the new user's default workspace creation timing (does it exist at claim time, or must we create it?).
3. Confirm `Meter.ZETTEL` is the correct meter + `get_functional_gates().reserve_and_consume` semantics for a *non-request* (claim) context (it's currently called inside request handlers).
4. Confirm `SessionMarkerCookieMiddleware` is the right extension point for `zk_anon_sid`; confirm the HMAC secret source.
5. Confirm OAuth `state` is under our control in the Supabase OAuth flow (auth-core.js) — if Supabase owns `state`, fall back to cookie-only recovery on callback.
6. Confirm migration manifest regen step + `core.profiles` is the correct FK target for `claimed_by_user`.
7. Confirm rate-limit primitive available (the existing 10/min/IP on `/add` — reuse its limiter).

---

## 13. Files to touch (build phase)
- `supabase/website/_v2/84_anon_zettel_claim.sql` + `.down.sql` (+ manifest regen)
- `website/api/zettels_routes.py` — `POST /api/zettels/claim-anon-session`; thread `anon_sid` into add
- `website/core/persist.py` — pass `anon_sid` to `upsert_canonical_zettel` when effective==Zoro
- `website/core/supabase_v2/…` — `claim_anon_zettels` repo wrapper
- `website/app.py` — `zk_anon_sid` cookie middleware
- `website/features/user_auth/js/auth-core.js` (+ `anon-session.js`) — mirror id, sign-in claim hook, BroadcastChannel
- `tests/integration/v2/…` + `tests/unit/…` — the §11 matrix
- **Prod migration is operator-applied** — never auto-run.

---

## 14. Risk & rollout
- **Blast radius:** new column (nullable, no backfill), new table, new RPC, one new endpoint, one middleware. Authed flows unchanged (anon_sid NULL).
- **Reversible:** `84_*.down.sql` drops everything; the endpoint + middleware are additive.
- **Quota:** uses the existing `require_entitlement` gate (the protected `billing.pricing_consume_entitlement` is **called, never altered** — golden-md5 safe).
- **Open operator decisions:** (a) audit/lineage table yes/no (§7.4); (b) consume-then-insert vs insert-then-reconcile ordering (§8).

---

---

## 15. Phase-0 reconciliation (verified 2026-05-30 — supersedes earlier assumptions)

These were confirmed against live code and **change the design**; the migration (`84_*`) and later phases follow THIS, not the earlier text:

1. **Cookie = opaque server-validated UUID, NOT HMAC** (operator decision). No signing-secret infra exists; the claim validates the cookie's UUID against `anon_sid` persisted on Zoro rows — a forged value matches nothing. HttpOnly+Secure+SameSite=Lax. Supersedes §5.1's "HMAC-signed".
2. **`anon_sid` is tagged via a dedicated `content.tag_anon_zettel(...)` call, NOT by modifying `content.upsert_workspace_zettel`.** That universal RPC (every ingestion path) is left untouched → zero blast radius on the authed write path. Supersedes §6's "pass into upsert".
3. **No OAuth `state` echo** — Supabase owns `state` (PKCE); `/auth/callback` is static HTML. The `zk_anon_sid` cookie (SameSite=Lax, same-origin `redirectTo`) survives the round-trip and is the carrier. Supersedes §5.3 step 1.
4. **New-user default workspace already exists at first sign-in** via a `core.profiles` AFTER-INSERT trigger (`core.create_personal_workspace`) — no bootstrap code. `get_default_workspace_id` = earliest `core.workspace_members` by `added_at`.
5. **Quota gate = `require_entitlement(Meter.ZETTEL.value, …)`** → `get_functional_gates().reserve_and_consume(profile_id, feature, action_id)` (request-free, raises 402). `consume_entitlement` is a no-op. Catch-the-402 to cap. Confirms §8.
6. **Rate-limit is a hand-rolled in-process sliding window** (`zettels_routes.py:_check_rate_limit`, 10/60s, not parameterised). Add a sibling `_check_claim_rate_limit` (3/60s) — no slowapi.
7. **Migrations apply by lexical filename sort** (no manifest); next file = `84_*`. After applying, **regenerate `expected_schema.json`** (drift snapshot) or the schema-drift gate fails deploy — operator step.
8. **`added_via` CHECK** only allowed `telegram|website|share|migration`; `84_*` extends it with `claim`. The claim RPCs (`peek_claimable_anon_zettels`, `commit_anon_claim`) are SECURITY DEFINER, service_role-granted, and use the real partial unique index `uq_workspace_zettel_active` for `ON CONFLICT … WHERE deleted_at IS NULL`.

### Build progress (PR #125)
- [x] Phase 0 verification + reconciliation
- [x] **Migration `84_anon_zettel_claim.sql` (+ down)** — column, partial index, CHECK extend, `anon_sessions`, `tag_anon_zettel`, `peek_claimable_anon_zettels`, `commit_anon_claim`, GRANTs
- [ ] Persist tagging: call `tag_anon_zettel` after a Zoro-anon write (persist.py) + repo wrapper
- [ ] `zk_anon_sid` opaque-UUID cookie middleware (_middleware.py)
- [ ] `POST /api/zettels/claim-anon-session`: peek → quota loop (consume-then-insert) → `commit_anon_claim`; `_check_claim_rate_limit`
- [ ] Client: mirror sid → localStorage, send on `/add`, sign-in claim hook, BroadcastChannel
- [ ] Tests (§11 matrix) — unit runnable locally; integration operator/CI (needs test DB)

**Next step:** continue the build phases above on PR #125; the migration is operator-applied to prod (never auto-run) and the operator regenerates `expected_schema.json` after applying.
