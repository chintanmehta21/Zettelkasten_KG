# Ingest — Psychedelic Drugs Kasten (operator-run, gated)

The harness does **not** ingest. The operator runs this once, then runs the
offline harness (`docs/rag_eval_v2/scripts/run_eval_v2.py`).

## Curated links (8, 3 source types)

| # | source_type | url |
|---|---|---|
| 1 | youtube | https://www.youtube.com/watch?v=hhjhU5MXZOo |
| 2 | youtube | https://www.youtube.com/watch?v=KtL5fafpRKc |
| 3 | youtube | https://www.youtube.com/watch?v=eOGG_5FzlJ4 |
| 4 | reddit  | https://www.reddit.com/r/consciousness/comments/1izjzk0/if_psychedelics_alter_the_perception_of/ |
| 5 | reddit  | https://www.reddit.com/r/philosophy/comments/1fzo0f4/psychedelic_experiences_disrupt_the_certainty_of/ |
| 6 | reddit  | https://www.reddit.com/r/IAmA/comments/9ke63/i_did_heroin_yesterday_i_am_not_a_drug_user_and/ |
| 7 | reddit  | https://www.reddit.com/r/philosophy/comments/9il3p/what_does_philosophy_reddit_know_about_drugs/ |
| 8 | web/arxiv | https://arxiv.org/abs/2011.08892 |

Link-set change (Defect 4 fix): the 2 medium.com essays (`humanparts`
LSD/Tibetan-Buddhism cosmic-joke, `cosmocat27` Awakening-from-the-Meaning-
Crisis) were unreachable server-side (medium anti-bot) and are replaced with
two reachable, extractor-handled Reddit threads from `kasten1.md`
(`r/IAmA 9ke63`, `r/philosophy 9il3p`). `queries.json` q5/q6/q7/q10 gold was
rewritten to the new sources. 3 source types (youtube/reddit/arxiv), 8 links.

Excluded from `kasten1.md`: every `google.com/search?q=` redirect-wrapper
(items Others 2-5), the unreachable Medium items, and the
`psychedelicspotlight.com` / `microdosinginstitute.com` thin-content pages —
per the Phase E curation rule (direct YouTube/Reddit/arXiv only).

## Exact operator command (Git Bash, repo root)

```bash
cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/pedantic-nash-324d30"
python -m website.api.module_runners.create_kasten \
  --name "Psychedelic Drugs" \
  --user-id f2105544-b73d-4946-8329-096d82f070d3 \
  --client-action-id rag-eval-v2-psychedelic-drugs \
  --links-file docs/rag_eval_v2/psychedelic-drugs/links.txt \
  --load-env
```

Equivalent explicit form (if `--links-file` is not preferred):

```bash
cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/pedantic-nash-324d30"
python -m website.api.module_runners.create_kasten \
  --name "Psychedelic Drugs" \
  --user-id f2105544-b73d-4946-8329-096d82f070d3 \
  --client-action-id rag-eval-v2-psychedelic-drugs \
  --links https://www.youtube.com/watch?v=hhjhU5MXZOo \
  --links https://www.youtube.com/watch?v=KtL5fafpRKc \
  --links https://www.youtube.com/watch?v=eOGG_5FzlJ4 \
  --links https://www.reddit.com/r/consciousness/comments/1izjzk0/if_psychedelics_alter_the_perception_of/ \
  --links https://www.reddit.com/r/philosophy/comments/1fzo0f4/psychedelic_experiences_disrupt_the_certainty_of/ \
  --links https://www.reddit.com/r/IAmA/comments/9ke63/i_did_heroin_yesterday_i_am_not_a_drug_user_and/ \
  --links https://www.reddit.com/r/philosophy/comments/9il3p/what_does_philosophy_reddit_know_about_drugs/ \
  --links https://arxiv.org/abs/2011.08892 \
  --load-env
```

After this returns, note the printed `kasten.id` (a UUID). Then run:

```bash
python docs/rag_eval_v2/scripts/run_eval_v2.py --kasten psychedelic-drugs --iter 1 --settle-seconds 45
```

`--load-env` loads `.env`/`.env.v2`/`supabase/.env` + `api_env` (3 Gemini keys)
from the repo root. KG population is fire-and-forget; the harness `--settle-seconds`
poll waits for chunks before querying.
