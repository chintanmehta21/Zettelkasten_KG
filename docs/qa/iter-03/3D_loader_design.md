# 3D Kasten-card-shuffle loader — design doc

Skill consultation: `ui-ux-pro-max` + `frontend-design` (both invoked once at the start of Phase 3 — see assistant transcript). This doc captures the verified design decisions before implementation.

## 1. Palette (TEAL ONLY — never amber, never purple)

Sourced from the established `--accent` family in `website/static/css/style.css` so the loader visually belongs to the Kasten surface (not the `/knowledge-graph` 3D viz, which owns amber, and never to anything purple/violet/lavender).

| Token            | Value                  | Use                                          |
|------------------|------------------------|----------------------------------------------|
| `--kasten-teal`         | `hsl(172, 66%, 50%)` (= `--accent`)   | Card fill, primary halo                      |
| `--kasten-teal-soft`    | `hsl(172, 50%, 92%)`                  | Card backdrop / faint surface (light only)   |
| `--kasten-teal-deep`    | `hsl(172, 65%, 28%)`                  | Card border, caption text                    |
| `--kasten-teal-glow`    | `var(--accent-glow)`                  | Container backdrop in dark mode              |

`--accent-muted: hsl(172, 40%, 40%)` from style.css is reused for low-contrast borders.

## 2. Anatomy

Three index-card silhouettes in an inline-flex row, each card 28×38 with a 4px border-radius. Cards stack at rest (translateX -8/0/+8, rotateZ -3/0/+3). On animation each card briefly fans out further then restacks — evoking the physical "shuffle" of Zettel index cards. Caption sits to the right of the cards (or below on narrow surfaces).

Transform-origin: `bottom center` — the fan visually pivots from where a hand would hold them.

## 3. Three states

| State            | Loop | Cards | Motion intent                        | Where it triggers                         |
|------------------|------|-------|--------------------------------------|-------------------------------------------|
| `long-pipeline`  | 2.5s | 3     | Lively fan + cycling captions        | After 5s with no `token` SSE frame        |
| `heartbeat`      | 4s   | 3     | Slower, opacity 0.7, "Reconnecting…" | On heartbeat-timeout retry (3C.1)         |
| `queued`         | 1.5s | 1     | Single card breathes + countdown     | On 503 + Retry-After (3B.2)               |

Caption strings for `long-pipeline` cycle every 3s:
1. `Searching your Zettels…`
2. `Reading the right cards…`
3. `Connecting the dots…`
4. `Drafting your answer…`

## 4. Accessibility

- `role="status"` + `aria-live="polite"` on the container so screen readers announce caption changes (rate-limited by the 3s caption interval).
- Captions are real text, not pseudo-content, so they translate.
- `@media (prefers-reduced-motion: reduce)` disables all keyframes; cards become static stacked silhouettes; captions still update.
- Cards use `border` + `background` rather than relying on color alone for the card silhouette.

## 5. Anti-patterns guarded against

- Never amber/gold (reserved for `/knowledge-graph` 3D viz).
- Never purple/violet/lavender (`hsl(250–290, *)`, `#A78BFA`, etc.) — explicitly grepped against in the diff.
- No bouncing scale-transforms that shift surrounding layout — the loader reserves a fixed 48px height block.
- No emoji icons (rule from `ui-ux-pro-max`).

## 6. API surface

Three exports from `loader.js`. Each returns a teardown function so callers reliably clear timers when state advances:

```js
const stop = ZkLoader.showLongPipelineLoader(container);
// later → stop();

const stop = ZkLoader.showHeartbeatLoader(container, onRetryClick);

const stop = ZkLoader.showQueuedLoader(container, seconds);
```

Implemented as a global `window.ZkLoader` rather than ESM to match the rest of `user_rag.js` (no module bundler in this repo).

## 7. Wiring decisions

- 3B.2 (queued-503) keeps its current inline pill UI for now — replacing it with `showQueuedLoader` is left as a follow-up so this commit stays scoped to introducing the primitive without rewriting the 503 path.
- 3C.1 (heartbeat retry) replaces the plain `Reconnecting your Kasten…` status text with `showHeartbeatLoader` rendered in the assistant bubble.
- Long-pipeline (no token within 5s of POST accept) renders `showLongPipelineLoader` inside the assistant bubble; first `token` frame tears it down before appending text.
