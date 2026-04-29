"""Post-mortem analyzer for iter-03 http_results.json.
Groups failed queries by failure mode, dumps answer + critic_notes so we can
see WHY each query was low-confidence or wrong-zettel.
"""
import json
import sys
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/rag_eval/common/knowledge-management/iter-03/http_results.json")
QPATH = Path("docs/rag_eval/common/knowledge-management/iter-03/queries.json")

data = json.loads(PATH.read_text(encoding="utf-8"))
results = data["results"]
queries = {q["qid"]: q for q in json.loads(QPATH.read_text(encoding="utf-8"))["queries"]}

print(f"=== {PATH.name}: {len(results)} queries ===\n")
print(f"{'qid':>5} {'code':>4} {'lat_s':>6} {'qclass':<14} {'gold@1':<6} {'critic':<25} {'cits':>4} {'ans_chars':>9}")
for r in results:
    q = queries.get(r["qid"], {})
    qclass = q.get("class", "?")
    print(
        f"{r['qid']:>5} {r['code']:>4} {r['elapsed_ms']/1000:>6.1f} {qclass:<14} "
        f"{str(r['gold_at_1']):<6} {str(r.get('critic')):<25} "
        f"{r['citations']:>4} {r.get('answer_chars',0):>9}"
    )

print("\n=== FAILURE MODES ===\n")

successes = [r for r in results if r["gold_at_1"]]
infra_fail = [r for r in results if r["code"] >= 500 or r["code"] == 0]
quality_fail = [r for r in results if r["code"] == 200 and not r["gold_at_1"]]

print(f"Successes (gold@1):  {len(successes)}/{len(results)}")
print(f"Infra failures:      {len(infra_fail)}/{len(results)} (code>=500)")
print(f"Quality failures:    {len(quality_fail)}/{len(results)} (200 but wrong)\n")

print("--- Quality failures (200 but missed gold) ---\n")
for r in quality_fail:
    q = queries.get(r["qid"], {})
    print(f"### {r['qid']} [{q.get('class')}]")
    print(f"  Q: {q.get('text','')[:200]}")
    print(f"  expected: {q.get('expected_primary_citation') or q.get('expected_minimum_citations')}")
    print(f"  primary returned: {r.get('primary')}")
    print(f"  retrieved_node_ids: {r.get('retrieved_node_ids',[])[:8]}")
    print(f"  citations: {r.get('all_citations',[])}")
    print(f"  critic verdict: {r.get('critic')}")
    print(f"  critic notes:   {r.get('critic_notes')}")
    print(f"  answer (first 600): {(r.get('answer_text','') or '')[:600]}")
    print()

print("\n--- Successes (sanity check) ---\n")
for r in successes:
    q = queries.get(r["qid"], {})
    print(
        f"  {r['qid']} [{q.get('class')}]  "
        f"primary={r.get('primary')}  critic={r.get('critic')}  "
        f"latency={r['elapsed_ms']/1000:.1f}s  "
        f"answer_chars={r.get('answer_chars')}"
    )
