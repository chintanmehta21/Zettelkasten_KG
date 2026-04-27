# 3C.1 SSE heartbeat-aware client + auto-retry (manual verification)

**Surface:** `/home/rag` SSE stream from `POST /api/rag/sessions/:id/messages`

## Behavioral checklist

- [ ] Normal stream: tokens flow as before; no behavior change.
- [ ] Server emits `:heartbeat\n\n` every ~10s during a long pipeline → reader does NOT cancel; `lastFrameMs` is refreshed by the heartbeat frame.
- [ ] Server stops emitting frames for >15s → `consumeSSE` cancels the reader with reason `heartbeat-timeout` and throws `Error{code:'heartbeat-timeout'}`.
- [ ] After heartbeat-timeout, `onAsk` automatically reissues the POST exactly once after a 1s backoff. Status text reads `Reconnecting your Kasten…`.
- [ ] If the retry succeeds → answer streams normally; no error chip.
- [ ] If the retry also fails → friendly `Lost connection mid-answer. Please retry.` with the existing Retry button.
- [ ] Subsequent fresh user messages get a fresh `_sseRetryUsed` budget (the flag is cleared on success and on terminal failure).
- [ ] No duplicate watchdog timers if the same chat asks rapid-fire questions.

## Test recipe (DevTools)

1. Override the fetch response body to send `data: {"type":"token","content":"hi "}\n\n` then stall for 20s.
2. Confirm cancel + retry path fires.
3. Restore network and confirm the retry completes the answer.
