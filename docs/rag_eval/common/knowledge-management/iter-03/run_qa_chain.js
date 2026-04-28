/* iter-03 verification — paste into the browser DevTools Console on
 * https://zettelkasten.in/home/rag while signed in as Naruto.
 *
 * Endpoints (verified against website/api/chat_routes.py + sandbox_routes.py):
 *   GET  /api/rag/sandboxes          → discovers the Knowledge Management Kasten by name
 *   POST /api/rag/adhoc              → creates a fresh session per query and runs it
 *
 * Response shape used (verified against website/features/rag_pipeline/types.py:AnswerTurn):
 *   { session_id, session, turn: { content, citations[{id,node_id,...}],
 *     critic_verdict, llm_model, latency_ms, retrieved_node_ids, ... } }
 *
 * Usage:
 *   1. Open https://zettelkasten.in/home/rag (signed in as Naruto).
 *   2. DevTools → Console.
 *   3. Paste this whole file → Enter.
 *   4. Wait ~3-5 minutes (sequential to avoid the iter-02 burst-503 path).
 *   5. JSON downloads automatically; share the path back.
 */
(async () => {
  const TARGET_KASTEN_NAME = "Knowledge Management & Personal Productivity";
  const REFUSAL_PATTERNS = [
    /i can'?t find/i,
    /i cannot find/i,
    /i don'?t (have|see)/i,
    /no information/i,
    /not in your zettels/i,
  ];

  const QUERIES = [
    { qid: "q1",  quality: "fast", expected: "gh-zk-org-zk",
      text: "Which programming language is the zk-org/zk command-line tool written in, and what file format does it use for notes?" },
    { qid: "q2",  quality: "fast", expected: "yt-steve-jobs-2005-stanford",
      text: "What metaphor did Steve Jobs use at the Stanford 2005 commencement to describe the role of death in motivating life choices?" },
    { qid: "q3",  quality: "fast", expected: "yt-effective-public-speakin",
      text: "In Patrick Winston's MIT lecture on effective public speaking, what does he mean by 'verbal punctuation' and why does it matter?" },
    { qid: "q4",  quality: "high", expected: ["yt-matt-walker-sleep-depriv","yt-programming-workflow-is"],
      text: "Walker links sleep loss to specific cognitive deficits; the programming-workflow zettel claims certain habits protect engineering output. Synthesize what these two together say a knowledge worker should change about their nightly routine." },
    { qid: "q5",  quality: "fast", expected: ["yt-matt-walker-sleep-depriv","yt-programming-workflow-is","nl-the-pragmatic-engineer-t","yt-steve-jobs-2005-stanford","web-transformative-tools-for"],
      text: "Across these zettels, what is the implicit theory of how a knowledge worker should design their week — what do the authors collectively prescribe versus discourage?" },
    { qid: "q6",  quality: "fast", expected: ["web-transformative-tools-for","gh-zk-org-zk","yt-effective-public-speakin"],
      text: "The Matuschak essay calls for 'tools for thought.' Which other zettels in this Kasten describe concrete tools or techniques that fit that lineage, and how?" },
    { qid: "q7",  quality: "fast", expected: "yt-steve-jobs-2005-stanford",
      text: "Anything about commencement?" },
    { qid: "q8",  quality: "fast", expected: "gh-zk-org-zk",
      text: "Of the items in this Kasten, which one would I open first if I wanted to start building a personal wiki tonight?" },
    { qid: "q9",  quality: "fast", expected: [], adversarialNegative: true,
      text: "Summarize what this Kasten says about Notion's database features." },
    { qid: "q10", quality: "fast", expected: "yt-steve-jobs-2005-stanford",
      text: "Steve Jobs and Naval Ravikant both speak about meaningful work. Compare their views as captured in this Kasten." },
    { qid: "av-1", quality: "fast", expected: "gh-zk-org-zk", actionVerb: true,
      text: "What should I install tonight to start a personal wiki?" },
    { qid: "av-2", quality: "fast", expected: "gh-zk-org-zk", actionVerb: true,
      text: "Which guide do I run first to set up my Zettelkasten?" },
    { qid: "av-3", quality: "fast", expected: "gh-zk-org-zk", actionVerb: true,
      text: "Step-by-step setup commands for a personal wiki." },
  ];

  // Auth — Supabase JWT lives in localStorage under 'zk-auth-token' (see
  // website/features/user_rag/js/user_rag.js getAuthToken()). The API uses
  // Authorization: Bearer <jwt>, NOT cookies.
  function readBearer() {
    try {
      const raw = localStorage.getItem("zk-auth-token");
      if (!raw) return "";
      const parsed = JSON.parse(raw);
      // Supabase v2 stores either { access_token, ... } directly or wraps it
      // under currentSession; cover both.
      return (
        (parsed && parsed.access_token) ||
        (parsed && parsed.currentSession && parsed.currentSession.access_token) ||
        ""
      );
    } catch (e) {
      console.error("[iter-03] could not parse zk-auth-token", e);
      return "";
    }
  }
  const TOKEN = readBearer();
  if (!TOKEN) {
    console.error(
      "[iter-03] FATAL: no Supabase JWT in localStorage['zk-auth-token']. " +
        "Are you signed in as Naruto on this tab? If yes, refresh the page once and rerun."
    );
    return;
  }
  const AUTH_HEADERS = { Authorization: "Bearer " + TOKEN };

  console.log("[iter-03] discovering Kasten via /api/rag/sandboxes...");
  const sboxResp = await fetch("/api/rag/sandboxes?limit=50", {
    credentials: "include",
    headers: AUTH_HEADERS,
  });
  if (!sboxResp.ok) {
    console.error("[iter-03] FATAL: /api/rag/sandboxes returned HTTP", sboxResp.status);
    return;
  }
  const sboxBody = await sboxResp.json();
  const target = (sboxBody.sandboxes || []).find((s) => s.name === TARGET_KASTEN_NAME);
  if (!target) {
    console.error("[iter-03] FATAL: Kasten not found by name. Found:",
      (sboxBody.sandboxes || []).map((s) => s.name));
    return;
  }
  console.log("[iter-03] Kasten:", target.name, "id:", target.id, "members:", target.member_count);

  const fired = [];
  let infraFailures = 0;

  for (const q of QUERIES) {
    const t0 = performance.now();
    const result = { qid: q.qid, quality: q.quality, expected: q.expected, text: q.text };
    try {
      const r = await fetch("/api/rag/adhoc", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...AUTH_HEADERS },
        credentials: "include",
        body: JSON.stringify({
          sandbox_id: target.id,
          content: q.text,
          quality: q.quality,
          stream: false,
          scope_filter: {},
          title: `iter-03 ${q.qid}`,
        }),
      });
      result.http_status = r.status;
      result.elapsed_ms = Math.round(performance.now() - t0);
      if (!r.ok) {
        result.error = `HTTP ${r.status}`;
        if (r.status >= 500 && r.status < 600) infraFailures += 1;
        try { result.body = await r.text(); } catch (e) { result.body = String(e); }
      } else {
        const body = await r.json();
        const turn = body.turn || {};
        result.answer = turn.content || "";
        result.citations = (turn.citations || []).map((c) => ({
          id: c.id, node_id: c.node_id, title: c.title || null,
        }));
        // Verified shape: Citation has both `id` and `node_id`. The expected
        // values in queries.json are node-IDs ("gh-zk-org-zk", etc.) so the
        // gold-at-1 check uses node_id of the first citation.
        result.primary_citation = result.citations[0] ? result.citations[0].node_id : null;
        result.critic_verdict = turn.critic_verdict || null;
        result.llm_model = turn.llm_model || null;
        result.query_class = turn.query_class || null;
        result.latency_ms_server = turn.latency_ms || null;
        result.retrieved_node_ids = turn.retrieved_node_ids || [];
        result.session_id = body.session_id || null;

        const expectedSet = Array.isArray(q.expected) ? new Set(q.expected) : new Set(q.expected ? [q.expected] : []);
        const refused = REFUSAL_PATTERNS.some((p) => p.test(result.answer));
        if (q.adversarialNegative) {
          result.gold_at_1 = (result.citations.length === 0) || refused;
        } else if (expectedSet.size === 0) {
          result.gold_at_1 = false;
        } else {
          result.gold_at_1 = !!(result.primary_citation && expectedSet.has(result.primary_citation));
        }
        result.refused = refused;
        result.over_refusal = refused && !q.adversarialNegative;
      }
    } catch (e) {
      result.error = String(e);
      result.elapsed_ms = Math.round(performance.now() - t0);
      infraFailures += 1;
    }
    fired.push(result);
    console.log(
      `[iter-03] ${q.qid} ${result.http_status || "ERR"} ${result.elapsed_ms}ms gold@1=${result.gold_at_1} refused=${result.refused || false} primary=${result.primary_citation || "-"} critic=${result.critic_verdict || "-"}`
    );
  }

  const passes = fired.filter((r) => r.gold_at_1).length;
  const overRefusals = fired.filter((r) => r.over_refusal).length;
  const summary = {
    iter: "iter-03",
    deployed_origin: location.origin,
    captured_at: new Date().toISOString(),
    kasten: { id: target.id, name: target.name, member_count: target.member_count },
    total: fired.length,
    end_to_end_gold_at_1: +(passes / fired.length).toFixed(4),
    synthesizer_over_refusals: overRefusals,
    infra_failures: infraFailures,
    p95_latency_ms: (() => {
      const xs = fired.map((r) => r.elapsed_ms || 0).sort((a, b) => a - b);
      return xs[Math.floor(xs.length * 0.95)] || 0;
    })(),
    queries: fired,
  };

  console.log("[iter-03] DONE", {
    gold_at_1: summary.end_to_end_gold_at_1,
    over_refusals: overRefusals,
    infra_failures: infraFailures,
    p95_latency_ms: summary.p95_latency_ms,
  });

  const blob = new Blob([JSON.stringify(summary, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `iter-03_qa_results_${Date.now()}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  console.log("[iter-03] saved:", a.download);
  window.__ITER_03_QA = summary;
})();
