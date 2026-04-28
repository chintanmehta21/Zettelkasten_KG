# 3D.2 Kasten-card-shuffle loader (manual verification)

**Files:** `website/features/user_rag/css/loader.css`, `website/features/user_rag/js/loader.js`
**Wired into:** `user_rag.js` `onAsk` (long-pipeline) + SSE retry path (heartbeat)
**Design doc:** `docs/qa/iter-03/3D_loader_design.md`

## Visual checklist (all states)

- [ ] Cards are TEAL (`hsl(172, 66%, 50%)` fill, deep `hsl(172, 65%, 28%)` border). Never amber, never purple, never violet.
- [ ] Container background is `--accent-glow`, border is `--accent-muted`, caption text is `--accent`.
- [ ] Three cards in long-pipeline + heartbeat states; one card in queued state.
- [ ] Each card has a faint horizontal "ruled line" 8px from the top — reads as an index card silhouette.
- [ ] Container has 48px min-height so layout doesn't shift on mount/unmount.

## Long-pipeline state

- [ ] Trigger: send a question whose first token takes >5s to arrive (slow-network throttling, or stub a slow upstream).
- [ ] Cards fan left (-9°) → restack → fan right (+9°) → restack on a 2.5s loop, with 0.18s stagger between cards.
- [ ] Caption cycles every 3s through: "Searching your Zettels…", "Reading the right cards…", "Connecting the dots…", "Drafting your answer…".
- [ ] Loader disappears the instant the first token frame lands; assistant text streams normally below.
- [ ] If the answer arrives in <5s, the loader never mounts.

## Heartbeat-retry state

- [ ] Trigger: the server stops sending frames for 15s (test by stalling the SSE response in DevTools).
- [ ] Cards fan more slowly (4s loop) at opacity 0.72.
- [ ] Caption reads `Reconnecting your Kasten…` with a `↻ Retry now` button to its right.
- [ ] Button: teal outline, fills teal on hover/focus with dark text. Keyboard-accessible (focus ring visible).
- [ ] On successful auto-retry: loader disappears, answer streams.
- [ ] On failed auto-retry: loader disappears and the friendly inline-error + Retry button appear.

## Queued-503 state (primitive ready; not yet wired in this commit — see design doc §7)

- [ ] In the browser console: `ZkLoader.showQueuedLoader(document.querySelector('.rag-composer').parentNode.appendChild(document.createElement('div')), 5)`.
- [ ] Single card breathes (scale 1 → 1.05) on a 1.5s loop with a teal halo pulsing outward.
- [ ] Countdown `5 → 4 → … → 1` ticks once per second; container removes itself at 0.

## Accessibility

- [ ] Container has `role="status"` and `aria-live="polite"`.
- [ ] Browser DevTools → emulate `prefers-reduced-motion: reduce` → all card animations stop. Cards remain visible in a static fanned arrangement; captions still update.
- [ ] No emoji icons used (check `↻` is the U+21BB arrow character — acceptable per design rules; not an emoji).

## Color audit

```
git diff iter-03/all..HEAD -- website/features/user_rag/css/ website/features/user_rag/js/ \
  | grep -iE "purple|violet|lavender|#A78BFA|amber|gold|#D4A024"
```

Expected: only the design-doc / loader.css comment lines that mention those colors as banned. Zero hits in actual style declarations.
