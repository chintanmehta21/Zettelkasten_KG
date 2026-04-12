from __future__ import annotations

import json
from pathlib import Path


TEST_USER_UUID = "00000000-0000-0000-0000-000000000123"
BASE_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = BASE_DIR / "fixtures"


def _node(
    node_id: str,
    title: str,
    source_type: str,
    summary: str,
    tags: list[str],
    node_date: str,
) -> dict:
    return {
        "id": node_id,
        "user_id": TEST_USER_UUID,
        "name": title,
        "source_type": source_type,
        "summary": summary,
        "tags": tags,
        "url": f"https://example.com/{source_type}/{node_id}",
        "node_date": node_date,
        "metadata": {
            "fixture": True,
            "token_estimate": max(80, min(420, len(summary.split()) * 6)),
            "source_family": source_type,
        },
    }


def build_corpus() -> list[dict]:
    items = [
        _node("yt-ml-attention-primer", "Attention Primer for Builders", "youtube", "Self-attention lets each token weigh other tokens directly, which replaces strict recurrence and improves long-range context handling in transformer models.", ["ml", "attention", "transformers", "youtube"], "2026-01-01"),
        _node("yt-ml-transformer-block", "Inside a Transformer Block", "youtube", "A transformer block combines attention, feed-forward layers, residual paths, and normalization so models can refine representations without losing stability.", ["ml", "transformer", "architecture", "youtube"], "2026-01-02"),
        _node("yt-ml-embedding-intuition", "Embedding Space Intuition", "youtube", "Embeddings place text in vector space so semantically related passages stay close, making cosine similarity practical for search and clustering.", ["ml", "embeddings", "retrieval", "youtube"], "2026-01-03"),
        _node("yt-ml-rag-basics", "RAG for Product Teams", "youtube", "Retrieval augmented generation improves grounding by fetching evidence before writing an answer, which reduces unsupported claims and enables citations.", ["ml", "rag", "retrieval", "youtube"], "2026-01-04"),
        _node("yt-ml-eval-basics", "Evaluating LLM Systems", "youtube", "The note separates retrieval quality, answer faithfulness, latency, and live review loops because a single metric rarely exposes the whole failure surface.", ["ml", "evaluation", "ragas", "youtube"], "2026-01-05"),
        _node("yt-ml-hnsw-walkthrough", "HNSW Graph Search Walkthrough", "youtube", "HNSW uses layered proximity graphs to move quickly toward promising vector neighborhoods, trading additional memory for better recall and insert behavior.", ["ml", "hnsw", "vector-db", "youtube"], "2026-01-06"),
        _node("yt-ml-pgvector-indexes", "pgvector Index Tradeoffs", "youtube", "The summary compares IVFFlat and HNSW for mixed write and read workloads, noting HNSW often wins on recall and update-friendliness while costing more RAM.", ["ml", "pgvector", "hnsw", "youtube"], "2026-01-07"),
        _node("yt-ml-reranker-demo", "When to Add a Reranker", "youtube", "A reranker helps when first-pass retrieval is close but noisy, because cross-encoder scoring can promote semantically stronger passages near the top.", ["ml", "reranker", "bge", "youtube"], "2026-01-08"),
        _node("yt-ml-query-rewrite", "Query Rewriting for Search", "youtube", "Vague or multi-part questions often benefit from expansion, decomposition, or hypothetical answer generation before search to recover enough signal.", ["ml", "query-rewriting", "retrieval", "youtube"], "2026-01-09"),
        _node("yt-ml-context-window", "Context Windows Are Not Memory", "youtube", "Long context helps but does not replace selective retrieval, because too much irrelevant text raises cost and dilutes attention on useful evidence.", ["ml", "context-window", "generation", "youtube"], "2026-01-10"),
        _node("yt-ml-chunking-semantic", "Semantic Chunking in Practice", "youtube", "Semantic chunking follows meaning boundaries rather than raw token windows, which often improves retrieval on transcripts and long-form notes.", ["ml", "chunking", "semantic", "youtube"], "2026-01-11"),
        _node("yt-ml-agent-memory", "Memory Patterns for Agents", "youtube", "Agent systems need short-term conversational context and durable external memory, because chat history alone is too fragile for long-lived knowledge work.", ["ml", "agents", "memory", "youtube"], "2026-01-12"),
        _node("ss-ml-transformer-math", "Transformer Math Without Tears", "substack", "This essay reduces the transformer to weighted lookup, non-linear refinement, and residual stabilization so the architecture feels mechanical instead of magical.", ["ml", "transformers", "math", "substack"], "2026-01-13"),
        _node("ss-ml-retrieval-checklist", "A Retrieval Checklist for Real Systems", "substack", "A practical checklist recommends verifying embedding dimensions, hybrid baselines, failure modes, and citation rendering before tuning clever heuristics.", ["ml", "retrieval", "checklist", "substack"], "2026-01-14"),
        _node("ss-ml-faithfulness-notes", "Faithfulness Before Fluency", "substack", "The author argues that polished prose is dangerous when evidence is weak, so groundedness checks must come before aesthetic answer preferences.", ["ml", "faithfulness", "evaluation", "substack"], "2026-01-15"),
        _node("ss-ml-multi-hop-search", "Multi-hop Search Needs Structure", "substack", "Broad knowledge questions often span several notes, so the system should retrieve clusters and assemble them into a structured context pack.", ["ml", "multi-hop", "retrieval", "substack"], "2026-01-16"),
        _node("ax-ml-attention-paper", "Attention Is All You Need", "arxiv", "The paper introduces the Transformer architecture and shows that self-attention alone can replace recurrence while still modeling sequence structure effectively.", ["ml", "paper", "attention", "transformers"], "2026-01-17"),
        _node("ax-ml-contrastive-search", "Dense Retrieval with Contrastive Training", "arxiv", "Contrastive training reshapes embedding space so relevant query-document pairs align more tightly, especially when hard negatives are sampled well.", ["ml", "paper", "retrieval", "contrastive"], "2026-01-18"),
        _node("rd-ml-rag-mistakes", "RAG Mistakes Thread", "reddit", "A practitioner thread warns against over-chunking, skipping reranking, and trusting summary metrics without inspecting concrete failures.", ["ml", "rag", "mistakes", "reddit"], "2026-01-19"),
        _node("rd-ml-pgvector-tips", "pgvector Tuning Tips", "reddit", "This note emphasizes measuring vector recall under real user filters because scoping and query plans can change behavior more than index theory suggests.", ["ml", "pgvector", "tuning", "reddit"], "2026-01-20"),
        _node("yt-cook-sourdough-crumb", "Reading a Sourdough Crumb", "youtube", "Crumb structure reveals fermentation timing, hydration, and shaping quality, so the loaf itself becomes a diagnostic tool for the baker.", ["cooking", "bread", "fermentation", "youtube"], "2026-02-01"),
        _node("yt-cook-stirfry-heat", "Stir-Fry Heat Management", "youtube", "A good stir-fry depends on high heat, small batches, and late sauce additions so ingredients sear instead of steaming in pooled moisture.", ["cooking", "stir-fry", "heat", "youtube"], "2026-02-02"),
        _node("yt-cook-pan-sauce", "Weeknight Pan Sauces", "youtube", "Pan sauces come from fond, acid, stock, and butter, with reduction happening before the butter goes in so the texture stays glossy instead of greasy.", ["cooking", "sauce", "technique", "youtube"], "2026-02-03"),
        _node("yt-cook-rice-texture", "Rice Texture Control", "youtube", "Rice texture depends on water ratio, heat control, and a final covered rest that lets moisture redistribute instead of rushing straight to the plate.", ["cooking", "rice", "technique", "youtube"], "2026-02-04"),
        _node("yt-cook-knife-prep", "Knife Prep for Faster Weeknights", "youtube", "Consistent cuts cook evenly and make timing easier, which means prep quality quietly improves both speed and final texture.", ["cooking", "prep", "knives", "youtube"], "2026-02-05"),
        _node("yt-cook-stock-basics", "Building Better Stock", "youtube", "White stock and roasted stock differ in flavor depth and clarity, while gentle heat and skimming help keep the liquid clean and useful.", ["cooking", "stock", "basics", "youtube"], "2026-02-06"),
        _node("ss-cook-pasta-water", "Why Pasta Water Matters", "substack", "Starchy pasta water helps bind fat and cheese into a unified sauce, and its thickening power falls quickly when the pot is over-diluted.", ["cooking", "pasta", "emulsion", "substack"], "2026-02-07"),
        _node("ss-cook-braising-guide", "The Gentle Logic of Braising", "substack", "Braising succeeds when low steady heat converts collagen gradually without driving off too much moisture, making patience a texture tool.", ["cooking", "braise", "slow-cooking", "substack"], "2026-02-08"),
        _node("tw-cook-breakfast-thread", "Breakfast Sandwich Workflow", "twitter", "A compact workflow uses staggered pan timing, pre-toasted buns, and a quick sauce mix to make a repeatable breakfast sandwich with less chaos.", ["cooking", "breakfast", "workflow", "twitter"], "2026-02-09"),
        _node("tw-cook-salad-thread", "Layered Salad Thread", "twitter", "Good salads rely on contrast between bitter, crunchy, creamy, and warm elements, which turns leftovers into a composed meal instead of a bowl of scraps.", ["cooking", "salad", "composition", "twitter"], "2026-02-10"),
        _node("yt-hist-roman-roads", "Why Roman Roads Lasted", "youtube", "Roman roads lasted because layered construction, drainage, and maintenance supported a logistics system that mattered to imperial power.", ["history", "rome", "infrastructure", "youtube"], "2026-03-01"),
        _node("yt-hist-printing-press", "Printing Press and Social Change", "youtube", "The press accelerated literacy, debate, and coordination, amplifying movements that were already present rather than creating change from nothing.", ["history", "printing", "media", "youtube"], "2026-03-02"),
        _node("yt-hist-silk-road", "The Silk Road as Network", "youtube", "The Silk Road worked as a shifting network of routes rather than a single road, carrying goods, beliefs, and disease across many linked regions.", ["history", "trade", "silk-road", "youtube"], "2026-03-03"),
        _node("yt-hist-industrial-cities", "Industrial Cities and Time Discipline", "youtube", "Factory life made clock time far more important to urban rhythm, work discipline, and family life than many agrarian systems had required.", ["history", "industrial-revolution", "labor", "youtube"], "2026-03-04"),
        _node("ss-hist-archives", "How Historians Read Archives", "substack", "Archives preserve power as much as truth, so historians treat silence, omission, and bureaucratic framing as evidence too.", ["history", "archives", "method", "substack"], "2026-03-05"),
        _node("ss-hist-maritime-empire", "Ships, Wind, and Empire", "substack", "Maritime empire depended on ship design, seasonal wind knowledge, and port finance, which made logistics more decisive than maps alone suggest.", ["history", "maritime", "empire", "substack"], "2026-03-06"),
        _node("rd-hist-byzantine-thread", "Byzantine Survival Notes", "reddit", "Byzantium lasted through diplomatic flexibility, defensive depth, and fiscal resilience rather than through a single unbeatable advantage.", ["history", "byzantium", "strategy", "reddit"], "2026-03-07"),
        _node("rd-hist-reformation-debate", "Reformation Debate Notes", "reddit", "The Reformation spread through a mix of doctrine and political incentives, so ideas and institutions moved together rather than separately.", ["history", "reformation", "politics", "reddit"], "2026-03-08"),
        _node("tw-hist-map-thread", "Reading Old Maps", "twitter", "Maps reveal what states found measurable and worth controlling, so borders, omissions, and routes all speak to historical priorities.", ["history", "maps", "statecraft", "twitter"], "2026-03-09"),
        _node("ax-hist-climate-paper", "Climate Shocks and Historical Fragility", "arxiv", "Climate shocks matter most when they collide with weak storage, brittle trade systems, and political stress, making them a force multiplier.", ["history", "climate", "fragility", "paper"], "2026-03-10"),
        _node("yt-finance-bond-duration", "Bond Duration in Plain Language", "youtube", "Duration measures how strongly a bond price reacts to rate changes, which is why long-duration bonds move more when rates shift.", ["finance", "bonds", "rates", "youtube"], "2026-03-11"),
        _node("yt-finance-index-funds", "Why Index Funds Work", "youtube", "Index funds combine diversification, low fees, and a long horizon into a strong default, though investor behavior still determines outcomes.", ["finance", "index-funds", "investing", "youtube"], "2026-03-12"),
        _node("ss-finance-cashflow", "Cash Flow Beats Narrative", "substack", "This note values durable cash generation over market storytelling and treats estimation confidence as part of the valuation problem.", ["finance", "cash-flow", "valuation", "substack"], "2026-03-13"),
        _node("rd-finance-risk-thread", "Risk Is Position Size", "reddit", "The thread argues that oversized positions turn manageable uncertainty into portfolio-threatening damage faster than conviction can justify.", ["finance", "risk", "portfolio", "reddit"], "2026-03-14"),
        _node("ax-finance-market-microstructure", "Microstructure and Price Discovery", "arxiv", "Liquidity is dynamic because spreads, order flow, and dealer inventory interact continuously during price formation.", ["finance", "market-microstructure", "liquidity", "paper"], "2026-03-15"),
        _node("yt-travel-night-trains", "Night Trains Without Chaos", "youtube", "Overnight train travel feels smoother when berth choice, station transitions, and sleep protection are planned before departure.", ["travel", "trains", "planning", "youtube"], "2026-04-01"),
        _node("yt-travel-carry-on", "Carry-On Packing Logic", "youtube", "Carry-on packing works best when each item must justify weight and redundancy, which favors systems over one-off outfit decisions.", ["travel", "packing", "carry-on", "youtube"], "2026-04-02"),
        _node("ss-travel-walkable-cities", "Choosing Walkable Cities", "substack", "Walkable travel neighborhoods are better chosen by transit rhythm, groceries, and safety than by landmark density alone.", ["travel", "cities", "walkability", "substack"], "2026-04-03"),
        _node("rd-travel-airport-thread", "Airport Buffer Strategy", "reddit", "The right airport buffer depends on connection complexity, immigration friction, and the cost of missing the onward leg.", ["travel", "airports", "planning", "reddit"], "2026-04-04"),
        _node("tw-travel-cafe-thread", "Finding Better Cafe Stops", "twitter", "Useful cafe stops are chosen for light, seating turnover, and transit adjacency because pace matters as much as destination count.", ["travel", "cafes", "pace", "twitter"], "2026-04-05"),
    ]

    assert len(items) == 50
    return items


def build_golden_qa() -> list[dict]:
    qa = [
        ("What does self-attention replace in the transformer story?", "It replaces strict recurrence and lets tokens weigh one another directly in parallel.", "Self-attention replaces recurrence as the primary mechanism for relating tokens in the Transformer.", ["yt-ml-attention-primer", "ax-ml-attention-paper"]),
        ("Why do transformer blocks use residual paths and normalization?", "They stabilize training while attention and feed-forward layers refine the representation.", "Residual connections and normalization keep transformer training stable while deeper layers add useful computation.", ["yt-ml-transformer-block", "ss-ml-transformer-math"]),
        ("How do embeddings help retrieval systems?", "They place text in a vector space where semantically related passages stay near each other for similarity search.", "Embeddings support retrieval by mapping semantically similar text to nearby points in vector space.", ["yt-ml-embedding-intuition", "ax-ml-contrastive-search"]),
        ("What is the main benefit of retrieval augmented generation?", "It grounds answers in fetched evidence before generation, reducing unsupported claims.", "RAG improves grounding by retrieving evidence before answer generation.", ["yt-ml-rag-basics", "ss-ml-retrieval-checklist"]),
        ("Why is faithfulness tracked separately from fluency?", "Because smooth answers can still be unsupported by the retrieved evidence.", "Faithfulness must be measured separately because fluent answers can still hallucinate.", ["yt-ml-eval-basics", "ss-ml-faithfulness-notes"]),
        ("What trade-off does HNSW introduce?", "It improves recall and insert behavior at the cost of more memory and tuning complexity.", "HNSW trades higher memory use for strong recall and practical incremental search.", ["yt-ml-hnsw-walkthrough", "yt-ml-pgvector-indexes"]),
        ("When is a reranker worth the latency?", "When first-pass retrieval is close but noisy and a small top slice can be re-scored for precision.", "A reranker helps when coarse retrieval needs a precision boost on a limited candidate set.", ["yt-ml-reranker-demo", "rd-ml-rag-mistakes"]),
        ("Why might a query rewriting stage matter?", "Because vague or multi-part questions often need expansion, decomposition, or a hypothesis before search.", "Query rewriting helps retrieve better evidence when the user question is vague or structurally hard to search.", ["yt-ml-query-rewrite", "ss-ml-multi-hop-search"]),
        ("What do the notes say about long context windows?", "They help, but they do not replace selective retrieval because irrelevant text still adds cost and noise.", "Long context is useful but does not replace focused retrieval.", ["yt-ml-context-window", "ss-ml-retrieval-checklist"]),
        ("When is semantic chunking preferable?", "It is preferable on long materials with clear meaning boundaries, such as transcripts and essays.", "Semantic chunking works best when the source has natural meaning boundaries.", ["yt-ml-chunking-semantic", "yt-ml-rag-basics"]),
        ("How is agent memory different from chat history?", "Chat history is short-term context, while durable memory is an external store the agent can retrieve later.", "Agent memory combines short-term context with durable external knowledge stores.", ["yt-ml-agent-memory", "yt-ml-context-window"]),
        ("What can sourdough crumb reveal?", "It can reveal fermentation timing, hydration, and shaping quality.", "A sourdough crumb acts as a diagnostic signal for fermentation, hydration, and shaping.", ["yt-cook-sourdough-crumb"]),
        ("How should a cook avoid steaming a stir-fry?", "Use high heat, keep batches small, and add sauce late.", "Stir-fry ingredients stay crisp when heat is high, batches are small, and sauce comes late.", ["yt-cook-stirfry-heat"]),
        ("Why does pasta water matter?", "Its starch helps emulsify and thicken the sauce.", "Starchy pasta water helps bind and thicken sauces.", ["ss-cook-pasta-water", "yt-cook-pan-sauce"]),
        ("What is the core logic of braising?", "Low steady heat converts collagen without driving off too much moisture.", "Braising depends on slow collagen conversion under gentle heat.", ["ss-cook-braising-guide", "yt-cook-stock-basics"]),
        ("Why did Roman roads last?", "Layered construction, drainage, and maintenance kept them useful for imperial logistics.", "Roman roads lasted through layered construction, drainage, and maintenance.", ["yt-hist-roman-roads"]),
        ("How did the printing press change society?", "It accelerated literacy, debate, and coordination, amplifying existing movements.", "The printing press accelerated circulation of ideas and social coordination.", ["yt-hist-printing-press", "rd-hist-reformation-debate"]),
        ("What is the Silk Road misconception corrected here?", "It was not one road but a network of routes.", "The Silk Road is better understood as a network rather than a single path.", ["yt-hist-silk-road"]),
        ("How do historians read archives critically?", "They read silence, omission, and bureaucratic framing as evidence too.", "Historians treat archives as shaped by power and read both presence and absence.", ["ss-hist-archives", "tw-hist-map-thread"]),
        ("What kept Byzantium alive in the thread?", "Diplomatic flexibility, defensive depth, and fiscal resilience.", "Byzantine survival came from adaptation, diplomacy, and resilience.", ["rd-hist-byzantine-thread"]),
        ("What does duration measure for bonds?", "It measures how strongly bond prices react to interest-rate changes.", "Bond duration expresses price sensitivity to rate moves.", ["yt-finance-bond-duration"]),
        ("Why do the notes favor index funds for many investors?", "They offer diversification, low fees, and a repeatable long-horizon default.", "Index funds combine diversification and low fees into a strong long-term baseline.", ["yt-finance-index-funds"]),
        ("What does the cash-flow essay prioritize over narrative?", "It prioritizes durable cash generation and reliable forecasting.", "Sustainable cash flow matters more than market storytelling in valuation.", ["ss-finance-cashflow"]),
        ("What is the risk lesson from the portfolio thread?", "Position sizing often determines whether uncertainty stays manageable.", "Oversized positions are a major source of investing risk.", ["rd-finance-risk-thread"]),
        ("How does the microstructure note describe liquidity?", "Liquidity is dynamic and depends on spreads, order flow, and inventory management.", "Liquidity changes with market-making conditions and order flow.", ["ax-finance-market-microstructure"]),
        ("How should someone reduce friction on overnight train travel?", "Plan berth choice, station transitions, and sleep protection before departure.", "Overnight train travel improves when sleeping conditions and station handoffs are planned.", ["yt-travel-night-trains"]),
        ("What packing principle drives the carry-on note?", "Each item must justify its weight and redundancy, which favors systems over one-offs.", "Carry-on packing works when every item earns its space.", ["yt-travel-carry-on"]),
        ("How should a traveler choose a walkable neighborhood?", "Judge it by groceries, transit rhythm, and safety instead of landmark count alone.", "Walkable neighborhoods should be chosen by everyday rhythm factors, not sightseeing density.", ["ss-travel-walkable-cities"]),
        ("What determines the right airport buffer?", "Transfer complexity, immigration friction, and the cost of missing the connection.", "Airport buffer time depends on hub complexity and the consequences of failure.", ["rd-travel-airport-thread"]),
        ("How do the retrieval notes combine initial search and reranking?", "They retrieve broadly, then rerank a smaller candidate slice for precision and better citations.", "A practical retrieval pipeline searches broadly first and reranks a limited candidate set second.", ["yt-ml-reranker-demo", "ss-ml-retrieval-checklist", "yt-ml-rag-basics"]),
    ]

    payload = [
        {
            "user_input": user_input,
            "retrieved_contexts": [],
            "response": response,
            "reference": reference,
            "ground_truth_support": support,
        }
        for user_input, response, reference, support in qa
    ]
    assert len(payload) == 30
    return payload


def write_json(path: Path, payload: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def main() -> None:
    corpus = build_corpus()
    golden = build_golden_qa()
    write_json(FIXTURES_DIR / "synthetic_corpus.json", corpus)
    write_json(FIXTURES_DIR / "golden_qa.json", golden)
    print(f"synthetic_corpus={len(corpus)}")
    print(f"golden_qa={len(golden)}")


if __name__ == "__main__":
    main()
