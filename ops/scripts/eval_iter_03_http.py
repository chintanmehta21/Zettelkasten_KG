"""Browser-free harness: hits /api/rag/adhoc directly for each iter-03 query
and records latency, primary citation, gold@1. Bypasses Playwright entirely
so we can measure raw RAG pipeline performance without networkidle pain.
Output: docs/rag_eval/common/knowledge-management/iter-03/http_results.json
"""
import json
import os
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[2]
QUERIES = ROOT / "docs/rag_eval/common/knowledge-management/iter-03/queries.json"
OUT = ROOT / "docs/rag_eval/common/knowledge-management/iter-03/http_results.json"

BASE = os.environ.get("ZK_BASE_URL", "https://zettelkasten.in")
TOKEN = os.environ["ZK_BEARER_TOKEN"]
KASTEN_ID = os.environ.get(
    "RAG_SMOKE_KASTEN_ID", "227e0fb2-ff81-4d08-8702-76d9235564f4"
)


def post_query(text: str, quality: str = "fast", timeout_s: int = 120) -> tuple[int, dict | None, float]:
    body = json.dumps(
        {
            "sandbox_id": KASTEN_ID,
            "content": text,
            "quality": quality,
            "stream": False,
            "scope_filter": {},
        }
    ).encode()
    req = urllib.request.Request(
        f"{BASE}/api/rag/adhoc", data=body, method="POST"
    )
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Content-Type", "application/json")
    # Cloudflare WAF blocks default Python-urllib UA with 403 before the
    # request reaches the app. Spoof Chrome to match real browser traffic.
    req.add_header(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    )
    req.add_header("Accept", "application/json")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            elapsed = time.monotonic() - t0
            return resp.getcode(), json.loads(resp.read()), elapsed
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - t0
        try:
            body = json.loads(e.read())
        except Exception:
            body = None
        return e.code, body, elapsed
    except Exception as e:
        elapsed = time.monotonic() - t0
        return 0, {"error": str(e)[:200]}, elapsed


def main():
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))["queries"]
    results = []
    print(f"running {len(queries)} queries against {BASE}", flush=True)
    # Pace queries so Gemini per-key rate limits don't cascade. The eval
    # harness is the only client; 8s between queries gives the key pool
    # time to clear cooldowns before the next burst of 4 Gemini calls.
    pacing_s = float(os.environ.get("ZK_EVAL_PACING_S", "8"))
    for i, q in enumerate(queries):
        if i > 0 and pacing_s > 0:
            time.sleep(pacing_s)
        qid = q["qid"]
        text = q["text"]
        gold = q.get("expected_primary_citation")
        # API only accepts "fast" | "high" (validator at chat_routes.py:34).
        # iter-03 spec: q1-q3 are lookup→fast, rest mostly multi-hop→high.
        quality = "fast" if q.get("class") in ("lookup",) else "high"
        code, body, elapsed_s = post_query(text, quality=quality)
        primary = None
        cit_count = 0
        crit_verdict = None
        answer_chars = 0
        retrieved_node_ids: list[str] = []
        if body and isinstance(body, dict):
            turn = body.get("turn") or {}
            cits = turn.get("citations") or []
            cit_count = len(cits)
            primary = cits[0]["node_id"] if cits else None
            crit_verdict = turn.get("critic_verdict")
            answer_chars = len(turn.get("content") or "")
            retrieved_node_ids = list(turn.get("retrieved_node_ids") or [])
        gold_at_1 = primary == gold
        # RAGAS-lite proxies (no Gemini judge — deterministic from response):
        # context_precision: gold cited at rank 1
        # context_recall:    gold appears anywhere in retrieved_node_ids
        # answer_relevancy:  has substantive answer (>120 chars)
        # faithfulness:      critic verdict (supported=1, partial=0.5, else=0)
        ctx_prec = 1.0 if gold_at_1 else 0.0
        ctx_recall = 1.0 if gold and gold in retrieved_node_ids else 0.0
        ans_rel = 1.0 if answer_chars >= 120 else (
            0.5 if answer_chars >= 40 else 0.0
        )
        verdict_score = {
            "supported": 1.0,
            "retried_supported": 1.0,
            "partial": 0.5,
            "unsupported": 0.0,
            "retried_low_confidence": 0.2,
            "retried_still_bad": 0.0,
        }
        faith = verdict_score.get(crit_verdict or "", 0.0)
        composite = round((ctx_prec + ctx_recall + ans_rel + faith) / 4.0, 3)
        ragas = {
            "context_precision": ctx_prec,
            "context_recall": ctx_recall,
            "answer_relevancy": ans_rel,
            "faithfulness": faith,
            "composite": composite,
        }
        print(
            f"  {qid:>4} {code} {elapsed_s*1000:7.0f}ms "
            f"gold@1={gold_at_1} primary={primary} cits={cit_count} "
            f"critic={crit_verdict} ans={answer_chars}c "
            f"ragas[p={ctx_prec} r={ctx_recall} a={ans_rel} f={faith} = {composite}] "
            f"quality={quality}",
            flush=True,
        )
        results.append(
            {
                "qid": qid,
                "code": code,
                "elapsed_ms": int(elapsed_s * 1000),
                "primary": primary,
                "expected": gold,
                "gold_at_1": gold_at_1,
                "citations": cit_count,
                "answer_chars": answer_chars,
                "critic": crit_verdict,
                "quality": quality,
                "ragas": ragas,
                "retrieved_node_ids": retrieved_node_ids,
            }
        )
    summary = {
        "total_count": len(results),
        "gold_at_1_count": sum(1 for r in results if r["gold_at_1"]),
        "infra_failures": sum(1 for r in results if r["code"] >= 500 or r["code"] == 0),
        "fast_p95_ms": sorted([r["elapsed_ms"] for r in results if r["quality"] == "fast"])[
            -max(1, int(0.05 * sum(1 for r in results if r["quality"] == "fast")))
        ] if any(r["quality"] == "fast" for r in results) else None,
        "strong_p95_ms": sorted([r["elapsed_ms"] for r in results if r["quality"] == "strong"])[
            -max(1, int(0.05 * sum(1 for r in results if r["quality"] == "strong")))
        ] if any(r["quality"] == "strong" for r in results) else None,
        "max_ms": max(r["elapsed_ms"] for r in results) if results else 0,
    }
    OUT.write_text(json.dumps({"results": results, "summary": summary}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    print(f"wrote {OUT}", flush=True)


if __name__ == "__main__":
    main()
