# PageIndex Knowledge Management iter-01 Manual Review

## Scope

- User: Naruto
- Kasten: Knowledge Management
- Query source: docs/rag_eval/common/knowledge-management/iter-03/queries.json

## Findings

| qid | verdict | notes |
|---|---|---|
| q1 | supported | expected `gh-zk-org-zk`; recall@5=1.000; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| q2 | supported | expected `yt-steve-jobs-2005-stanford`; recall@5=1.000; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| q3 | supported | expected `yt-effective-public-speakin`; recall@5=1.000; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| q4 | supported | expected `yt-matt-walker-sleep-depriv`, `yt-programming-workflow-is`; recall@5=1.000; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| q5 | partial | expected `yt-matt-walker-sleep-depriv`, `yt-programming-workflow-is`, `nl-the-pragmatic-engineer-t`, `yt-steve-jobs-2005-stanford`, `web-transformative-tools-for`; recall@5=0.800; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| q6 | partial | expected `web-transformative-tools-for`, `gh-zk-org-zk`, `yt-effective-public-speakin`; recall@5=0.667; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| q7 | supported | expected `yt-steve-jobs-2005-stanford`; recall@5=1.000; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| q8 | supported | expected `gh-zk-org-zk`; recall@5=1.000; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| q9 | miss | expected none; recall@5=0.000; mrr=0.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| q10 | supported | expected `yt-steve-jobs-2005-stanford`; recall@5=1.000; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| av-1 | supported | expected `gh-zk-org-zk`; recall@5=1.000; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| av-2 | supported | expected `gh-zk-org-zk`; recall@5=1.000; mrr=0.500; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
| av-3 | supported | expected `gh-zk-org-zk`; recall@5=1.000; mrr=1.000; cited=gh-zk-org-zk, nl-the-pragmatic-engineer-t, web-transformative-tools-for, yt-effective-public-speakin, yt-matt-walker-sleep-depriv, yt-programming-workflow-is, yt-steve-jobs-2005-stanford |
