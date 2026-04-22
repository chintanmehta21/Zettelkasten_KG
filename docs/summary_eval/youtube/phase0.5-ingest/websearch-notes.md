# YouTube transcript landscape - 2026-04-22

## Key findings

- `youtube-transcript-api` remains sensitive to cloud-IP blocking. Current GitHub issue traffic still reports transcript fetches failing from datacenter ranges even when proxy rotation is attempted, which supports keeping it as a fast path but not the only path.
- `yt-dlp` still exposes YouTube player-client controls, including `android_embedded`, and current ecosystem notes show continued churn in which clients work best at a given moment. That matches our benchmark result where `android_embedded` succeeded on all 3 benchmark URLs.
- Public Piped and Invidious pools remain unstable. Current upstream issue reports still show stale instance lists, broken hosts, and age-restriction or instance-health problems. That lines up with our benchmark where both public-pool tiers went 0 for 3.
- Gemini audio remains the escape hatch conceptually, but in this worktree it is not runnable yet because `google.generativeai` is not installed. The tier stays valuable as a later fallback once dependency/runtime wiring is complete.

## Sources checked

- `youtube-transcript-api` GitHub issue `#511` on cloud-provider IP blocking: <https://github.com/jdepoix/youtube-transcript-api/issues/511>
- `youtube-transcript-api` releases page showing ongoing proxy-related work: <https://github.com/jdepoix/youtube-transcript-api/releases>
- `yt-dlp` packaging/docs showing YouTube `player_client` support: <https://pypi.org/project/yt-dlp/2025.5.16.232928.dev0/>
- TeamPiped issue `#3760` on broken or stale public instances: <https://github.com/TeamPiped/Piped/issues/3760>
