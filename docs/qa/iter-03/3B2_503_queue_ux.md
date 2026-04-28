# 3B.2 503 Retry-After queue UX (manual verification)

**Surface:** `/home/rag` composer area, on POST `/api/rag/sessions/:id/messages`

## Test setup

Trigger a 503 with `Retry-After: 4` from the bounded queue (Phase 1B). One repro:
1. Saturate the queue from a parallel client.
2. Or stub the response in DevTools → Network → Override response with status 503 and header `Retry-After: 4`.

## Visual checklist

- [ ] A teal pill labeled `Lots of questions right now — retrying in Ns…` appears immediately above the sticky composer.
- [ ] Background is `--accent-glow` (soft teal), text is `--accent` (teal). NO purple/violet/lavender. NO amber/gold.
- [ ] Left dot pulses outward in a teal halo.
- [ ] Pill itself softly breathes (opacity 1 → 0.78 → 1) at ~1.6s.
- [ ] Countdown ticks down each second; uses tabular-nums (no jitter).
- [ ] When the countdown reaches 0, the pill removes itself and the actual retry POST fires.
- [ ] On a successful retry the assistant streams normally; no leftover pill.

## Behavioral checklist

- [ ] Server `Retry-After` header is honored exactly (try `Retry-After: 2` and `Retry-After: 8`).
- [ ] Missing/garbage `Retry-After` defaults to 5s.
- [ ] `Retry-After` > 30 is capped at 30 (sanity guard).
- [ ] Two concurrent 503s do not stack two pills (the second replaces the first).
- [ ] `prefers-reduced-motion: reduce` disables both the dot pulse and the breathe.

## Cross-checks

- [ ] Existing 502/504 retry path (1s backoff) still works unchanged.
- [ ] No regression on the friendly mid-stream "Lost connection mid-answer" error.
