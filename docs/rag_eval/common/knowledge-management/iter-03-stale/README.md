# iter-03-stale (archived)

Archived 2026-04-28. The original iter-03 attempt landed all 9 build-phase
commits but the load-bearing artifact (bge-reranker-base-int8.onnx) was never
deployed to the droplet. The lazy fp32 fallback fired in production, RSS hit
1.27 GB per worker, and 10 of 13 eval queries got 503'd by the memory guard.
Final eval: gold@1 = 0.2308, infra_failures = 10, p95 = 60.1 s.

This dir is kept for log/screenshot/post-mortem reference. The fresh iter-03
attempt lives one directory up. See `2026-04-28-iter-03-design.md` for the
new spec and `2026-04-28-iter-03.md` for the new plan.
