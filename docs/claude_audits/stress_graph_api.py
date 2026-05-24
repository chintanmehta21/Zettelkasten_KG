"""E2E stress harness for /api/graph + the meta/metrics endpoints.

Runs inside TestClient (in-process ASGI) so we exercise the FULL middleware
stack (auth, brotli/gzip, CORS, cache) without a network hop. Numbers here are
*architecturally* representative — absolute latencies are lower than droplet
production, but the cold/warm RATIO and concurrency behaviour are real.

Reports p50 / p95 / p99, error rate, cache hit profile.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Make sure the repo root is on PYTHONPATH regardless of CWD when invoked.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("GEMINI_API_KEY", "stub-stress")
os.environ.setdefault("PROMETHEUS_MULTIPROC_DIR", "/tmp/prom_multiproc_stress")
os.makedirs(os.environ["PROMETHEUS_MULTIPROC_DIR"], exist_ok=True)


def _client():
    from fastapi.testclient import TestClient
    from website.app import create_app
    return TestClient(create_app())


def pcts(times):
    if not times:
        return (0, 0, 0, 0, 0)
    s = sorted(times)
    n = len(s)
    p = lambda q: s[min(n - 1, int(q * n))]
    return (s[0], p(0.5), p(0.95), p(0.99), s[-1])


def run_serial(c, path, n):
    lat = []
    errs = 0
    for _ in range(n):
        t0 = time.perf_counter()
        r = c.get(path)
        if r.status_code != 200:
            errs += 1
        lat.append((time.perf_counter() - t0) * 1000)
    return lat, errs


def run_concurrent(c, path, n, workers):
    lat = []
    errs = 0

    def _one(_i):
        t0 = time.perf_counter()
        r = c.get(path)
        return (time.perf_counter() - t0) * 1000, r.status_code

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for f in as_completed([pool.submit(_one, i) for i in range(n)]):
            dt, sc = f.result()
            lat.append(dt)
            if sc != 200:
                errs += 1
    return lat, errs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default="/api/graph")
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    c = _client()

    print(f"=== ENDPOINT STRESS: {args.path} ===")

    # Warm-up — exercise the cold cache once so the cache layer is loaded
    # before measurements (we want to characterise the warm steady-state
    # alongside the cold first-call latency).
    t0 = time.perf_counter()
    r = c.get(args.path)
    cold_ms = (time.perf_counter() - t0) * 1000
    print(f"COLD (first call):       {cold_ms:8.1f}ms  status={r.status_code}  body_kb={len(r.content) / 1024:.1f}")

    print(f"\n--- {args.n} SERIAL warm calls ---")
    lat, errs = run_serial(c, args.path, args.n)
    mn, p50, p95, p99, mx = pcts(lat)
    print(f"min={mn:6.1f}  p50={p50:6.1f}  p95={p95:6.1f}  p99={p99:6.1f}  max={mx:6.1f}  mean={statistics.mean(lat):6.1f}  err={errs}")

    print(f"\n--- {args.n} CONCURRENT (workers={args.workers}) ---")
    lat, errs = run_concurrent(c, args.path, args.n, args.workers)
    mn, p50, p95, p99, mx = pcts(lat)
    print(f"min={mn:6.1f}  p50={p50:6.1f}  p95={p95:6.1f}  p99={p99:6.1f}  max={mx:6.1f}  mean={statistics.mean(lat):6.1f}  err={errs}")

    print(f"\n--- {args.n * 2} CONCURRENT BURST (workers={args.workers * 2}) ---")
    lat, errs = run_concurrent(c, args.path, args.n * 2, args.workers * 2)
    mn, p50, p95, p99, mx = pcts(lat)
    print(f"min={mn:6.1f}  p50={p50:6.1f}  p95={p95:6.1f}  p99={p99:6.1f}  max={mx:6.1f}  mean={statistics.mean(lat):6.1f}  err={errs}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
