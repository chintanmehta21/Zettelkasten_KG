# YouTube Phase 0.5 ingest decision - 2026-04-22

## Benchmark summary

- URLs tested: `hhjhU5MXZOo`, `HBTYVVUBAGs`, `Brm71uCWr-I`
- Tier 1 `ytdlp_player_rotation`: `3/3` success, all `confidence=high`, mean `25101` transcript chars, mean latency `2766 ms`
- Tier 2 `transcript_api_direct`: `3/3` success, all `confidence=high`, mean `23835` transcript chars, mean latency `1598 ms`
- Tier 3 `piped_pool`: `0/3` success
- Tier 4 `invidious_pool`: `0/3` success
- Tier 5 `gemini_audio`: `0/3` success in this environment because `google.generativeai` is not installed
- Tier 6 `metadata_only`: `1/3` success, `confidence=low`

## Winner by URL

- `hhjhU5MXZOo`: Tier 2 was the fastest successful transcript path; Tier 1 also succeeded with slightly more text.
- `HBTYVVUBAGs`: Tier 2 was the fastest successful transcript path; metadata-only hit a bot-check failure.
- `Brm71uCWr-I`: Tier 2 was the fastest successful transcript path; metadata-only hit a bot-check failure.

## Final ordering decision

Keep the default chain order as:

1. `ytdlp_player_rotation`
2. `transcript_api_direct`
3. `piped_pool`
4. `invidious_pool`
5. `gemini_audio`
6. `metadata_only`

## Rationale

- Acceptance is met because at least `2/3` URLs achieved `confidence=high`; in practice both Tier 1 and Tier 2 achieved `3/3`.
- Tier 2 was faster on this benchmark set, but Tier 1 produced slightly longer transcripts and aligns better with the current ecosystem evidence that player-client rotation is often the safer bypass when public transcript endpoints get blocked.
- Public Piped and Invidious instances are too unreliable to promote upward; they remain best-effort recovery tiers only.
- Gemini audio should stay below the free transcript tiers until its dependency/runtime path is wired and benchmarked successfully.
- Metadata-only remains the terminal fallback because it is low confidence and was degraded by bot checks on two of the three URLs.
