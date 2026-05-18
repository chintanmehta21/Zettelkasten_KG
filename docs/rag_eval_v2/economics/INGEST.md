# Ingest — Economics Kasten (operator-run, gated)

The harness does **not** ingest. The operator runs this once, then runs the
offline harness (`docs/rag_eval_v2/scripts/run_eval_v2.py`).

## Curated links (9, >=5 source types)

| # | source_type | url |
|---|---|---|
| 1 | youtube  | https://www.youtube.com/watch?v=HGe-SUyPZ38 |
| 2 | youtube  | https://www.youtube.com/watch?v=CtrhU7GOjOg |
| 3 | youtube  | https://www.youtube.com/watch?v=it8urKsgs44 |
| 4 | reddit   | https://www.reddit.com/r/AskEconomics/comments/na8pe1/what_are_some_of_the_most_interesting_little/ |
| 5 | reddit   | https://www.reddit.com/r/AskHistorians/comments/emq127/the_incas_were_able_to_construct_one_of_the/ |
| 6 | web/medium | https://medium.com/the-ascent/the-microeconomics-of-the-dark-web-23f4b4a1e9a |
| 7 | web/arxiv  | https://arxiv.org/abs/1812.01047 |
| 8 | github   | https://github.com/TheEconomist/big-mac-data |
| 9 | substack | https://adamtooze.substack.com/p/chartbook-448-price-controls-nationalization |

Excluded from `kasten2.md`: the `usitc.gov/.../pub3196.pdf` (PDF-thin), the
`academic.oup.com` paywalled abstract, the two non-curated arXiv items + the
non-curated Medium/Reddit entries (kept the set at 9 across 5 source types per
the Phase E curation rule). HN item 25841029 was dropped in favour of the
GitHub + Substack direct sources to keep >=5 distinct source types without a
bare HN scrape.

## Exact operator command (Git Bash, repo root)

```bash
cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/pedantic-nash-324d30"
python -m website.api.module_runners.create_kasten \
  --name "Economics" \
  --user-id f2105544-b73d-4946-8329-096d82f070d3 \
  --client-action-id rag-eval-v2-economics \
  --links-file docs/rag_eval_v2/economics/links.txt \
  --load-env
```

Equivalent explicit form:

```bash
cd "C:/Users/LENOVO/Documents/Claude_Code/Projects/Obsidian_Vault/.claude/worktrees/pedantic-nash-324d30"
python -m website.api.module_runners.create_kasten \
  --name "Economics" \
  --user-id f2105544-b73d-4946-8329-096d82f070d3 \
  --client-action-id rag-eval-v2-economics \
  --links https://www.youtube.com/watch?v=HGe-SUyPZ38 \
  --links https://www.youtube.com/watch?v=CtrhU7GOjOg \
  --links https://www.youtube.com/watch?v=it8urKsgs44 \
  --links https://www.reddit.com/r/AskEconomics/comments/na8pe1/what_are_some_of_the_most_interesting_little/ \
  --links https://www.reddit.com/r/AskHistorians/comments/emq127/the_incas_were_able_to_construct_one_of_the/ \
  --links https://medium.com/the-ascent/the-microeconomics-of-the-dark-web-23f4b4a1e9a \
  --links https://arxiv.org/abs/1812.01047 \
  --links https://github.com/TheEconomist/big-mac-data \
  --links https://adamtooze.substack.com/p/chartbook-448-price-controls-nationalization \
  --load-env
```

After this returns, note the printed `kasten.id` (a UUID). Then run:

```bash
python docs/rag_eval_v2/scripts/run_eval_v2.py --kasten economics --iter 1 --settle-seconds 45
```
