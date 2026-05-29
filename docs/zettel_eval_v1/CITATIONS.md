# Citations

All research sources informing the methodology, prioritised by recency
(2024-2026 first; older only when canonical reference).

## 1. LLM-as-a-judge frameworks

- Liu et al. — G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment (2023). https://arxiv.org/abs/2303.16634
- Es et al. — Ragas: Automated Evaluation of Retrieval Augmented Generation (2023). https://arxiv.org/abs/2309.15217
- Song et al. — FineSurE: Fine-grained Summarization Evaluation using LLMs (ACL 2024). https://arxiv.org/abs/2407.00908
- Laban et al. — SummaC: NLI-based Inconsistency Detection (TACL 2022). https://arxiv.org/abs/2111.09525
- DeepMind — FACTS Grounding: A New Benchmark for Factuality (Dec 2024). https://arxiv.org/pdf/2501.03200
- "Rethinking Atomic Decomposition for LLM Judges" (Mar 2026). https://arxiv.org/abs/2603.28005
- "No Free Labels: Limitations of LLM-as-a-Judge Without Human Grounding" (2025). https://arxiv.org/html/2503.05061v1
- "Evaluating Scoring Bias in LLM-as-a-Judge" (2025). https://arxiv.org/html/2506.22316v1
- JudgeBench (ICLR 2025). https://arxiv.org/pdf/2410.12784

## 2. Atomic-fact decomposition

- Min et al. — FActScore (EMNLP 2023). https://arxiv.org/abs/2305.14251
- Wei et al. — SAFE: Search-Augmented Factuality Evaluator (2024). https://arxiv.org/pdf/2403.18802
- Tang et al. — MiniCheck (EMNLP 2024). https://arxiv.org/abs/2404.10774
- Scirè et al. — FENICE (ACL Findings 2024). https://aclanthology.org/2024.findings-acl.841/
- Wanner et al. — A Closer Look at Claim Decomposition (*SEM 2024). https://aclanthology.org/2024.starsem-1.13/
- Lu et al. — Optimizing Decomposition for Optimal Claim Verification (ACL 2025). https://arxiv.org/abs/2503.15354
- Jiang et al. — Core: Robust Factual Precision (2024). https://arxiv.org/html/2407.03572v2
- Chen et al. — Dense X Retrieval / Propositions (EMNLP 2024). https://aclanthology.org/2024.emnlp-main.845.pdf
- Aly et al. — VeriFastScore (EMNLP Findings 2025). https://aclanthology.org/2025.findings-emnlp.491/

## 3. Judge-LLM bias and mitigation

- Zheng et al. — MT-Bench / Chatbot Arena (2024). https://arxiv.org/html/2306.05685v4
- Panickssery et al. — LLM Evaluators Recognize and Favor Own Generations (2024). https://arxiv.org/abs/2404.13076
- Sanity Checking Self-Preference Evaluations (2025). https://arxiv.org/pdf/2601.22548
- Mitigating Self-Preference by Authorship Obfuscation (Dec 2025). https://arxiv.org/pdf/2512.05379
- "Justice or Prejudice?" — CALM framework (2024). https://arxiv.org/html/2410.02736v1
- Verga et al. — Replacing Judges with Juries (PoLL, 2024). https://arxiv.org/abs/2404.18796
- Chen & Mueller — BSDetector (ACL 2024). https://aclanthology.org/2024.acl-long.283/
- Judge-Aware Ranking Framework (pairwise vs pointwise, 2025). https://arxiv.org/pdf/2601.21817
- Non-Transitivity in LLM-as-a-Judge. https://openreview.net/forum?id=clJIQ4TKR0
- "Who Judges the Judge?" Jury-on-Demand (2025). https://arxiv.org/pdf/2512.01786
- LLM Meta-Judges Multi-Agent Framework (2025). https://arxiv.org/pdf/2504.17087

## 4. NLI-based faithfulness

- MiniCheck GitHub + LLM-AggreFact leaderboard. https://github.com/Liyan06/MiniCheck and https://llm-aggrefact.github.io/
- AlignScore (Zha et al., ACL 2023). https://aclanthology.org/2023.acl-long.634/
- FENICE on HF. https://huggingface.co/Babelscape/FENICE
- Vectara HHEM-2.1-Open (Apache-2.0). https://huggingface.co/vectara/hallucination_evaluation_model
- Vectara HHEM-2.1 blog. https://www.vectara.com/blog/hhem-2-1-a-better-hallucination-detection-model
- Vectara hallucination leaderboard. https://github.com/vectara/hallucination-leaderboard
- Patronus Lynx (2024). https://arxiv.org/html/2407.08488v1
- Re-evaluating Hallucination Detection in LLMs (EMNLP 2025). https://aclanthology.org/2025.emnlp-main.1761.pdf
- DeBERTa-v3-large MNLI baseline. https://huggingface.co/MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli

## 5. Meta-evaluation / human-correlation methodology

- Bonett & Wright (2000) — Sample Size Requirements for Correlations. https://link.springer.com/article/10.1007/BF02294183
- Ruscio (2008) — CIs for Spearman with Ordinal Data. https://ruscio.pages.tcnj.edu/files/2016/08/Ruscio-2008-JMASM-CIs-for-Spearmans-Rho.pdf
- Deutsch, Dror, Roth (NAACL 2022) — Re-Examining System-Level Correlations. https://aclanthology.org/2022.naacl-main.442/
- Fabbri et al. — SummEval (TACL 2021). https://aclanthology.org/2021.tacl-1.24.pdf
- Liu et al. — RoSE (ACL 2023). https://aclanthology.org/2023.acl-long.228.pdf
- "Evaluating the Consistency of LLM Evaluators" (COLING 2025). https://aclanthology.org/2025.coling-main.710.pdf
- Chiang et al. — Chatbot Arena / Bradley-Terry with Bootstrap CIs (2024). https://arxiv.org/pdf/2403.04132
- Aligning with Human Judgement: Pairwise Preference (2024). https://arxiv.org/abs/2403.16950
- Krippendorff (2018) — Content Analysis (textbook reference for α). https://doi.org/10.4135/9781071878781

## 6. Industry practice

- OpenAI Evaluation Best Practices. https://developers.openai.com/api/docs/guides/evaluation-best-practices
- Anthropic — Demystifying Evals for AI Agents. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic–OpenAI Alignment Eval Findings (2025). https://alignment.anthropic.com/2025/openai-findings/
- Galileo — LLM-as-a-Judge vs Human Evaluation. https://galileo.ai/blog/llm-as-a-judge-vs-human-evaluation
- Arize — LLM-as-a-Judge primer. https://arize.com/llm-as-a-judge/
- FutureAGI — 2026 review of evaluation tools. https://futureagi.com/blog/top-5-llm-evaluation-tools-2025/
- Patronus / Vectara / Bedrock 2026 round-up. https://www.bestaiweb.ai/patronus-lynx-vectara-hhem-and-bedrock-contextual-grounding-how-rag-faithfulness-tooling-evolved-in-2026/

## 7. Per-source-type / surgical evaluation (sweep-2)

- AdaRubric: Task-Adaptive Rubrics (2025). https://arxiv.org/html/2603.21362
- Rulers: Locked Rubrics, Evidence-Anchored Scoring. https://arxiv.org/html/2601.08654
- LLM-Rubric: Multidimensional, Calibrated. https://arxiv.org/html/2501.00274v1
- Tuning LLM Judge Design Decisions for 1/1000 of the Cost. https://arxiv.org/pdf/2501.17178
- Patronus Evaluators / Glider. https://www.patronus.ai/blog/patronus-evaluators
- Vectara HHEM-v2 / FaithJudge (May 2025). https://www.vectara.com/blog/introducing-the-next-generation-of-vectaras-hallucination-leaderboard
- FacetSum (faceted scientific summarization). https://arxiv.org/abs/2106.00130
- ScholarSum / Facet-aware metric. https://arxiv.org/abs/2402.14359
- CodeXGLUE. https://arxiv.org/pdf/2102.04664
- Semantic Similarity for Code Summaries. https://arxiv.org/pdf/2204.01632
- M3-SLU: Speaker-Attributed Reasoning (Oct 2025). https://arxiv.org/pdf/2510.19358
- PodSumm. https://arxiv.org/pdf/2009.10315
- IJPREMS Podcast Diarization Summarization (March 2025). https://www.ijprems.com/uploadedfiles/paper/issue_3_march_2025/39234/final/fin_ijprems1742912787.pdf
- Contextual Sarcasm Detection w/ BART summaries (MDPI 14/3/95, March 2025). https://www.mdpi.com/2073-431X/14/3/95
- Trafilatura evaluation. https://trafilatura.readthedocs.io/en/latest/evaluation.html
- jusText repo. https://github.com/miso-belica/justext

## 8. Failure-mode taxonomy (sweep-2)

- FRANK (Pagnoni et al. NAACL 2021). https://aclanthology.org/2021.naacl-main.383/
- FineSurE (Song et al. ACL 2024). https://arxiv.org/abs/2407.00908
- FaithBench (NAACL 2025). https://arxiv.org/html/2410.13210v1
- RAGTruth (ACL 2024). https://aclanthology.org/2024.acl-long.585.pdf
- Survey of Hallucination in NLG (ACM CSUR v7, Jul 2024). https://arxiv.org/abs/2202.03629
- Survey on Hallucination in LLMs (ACM TOIS 2024). https://dl.acm.org/doi/10.1145/3703155
- AggreFact (ACL 2023). https://aclanthology.org/2023.acl-long.650.pdf
- LLM-AggreFact Leaderboard. https://llm-aggrefact.github.io/
- Patronus Lynx (arXiv 2407.08488). https://arxiv.org/abs/2407.08488
- Galileo Luna (arXiv 2406.00975). https://arxiv.org/abs/2406.00975
- Vectara Hallucination Leaderboard. https://github.com/vectara/hallucination-leaderboard
- Bespoke-MiniCheck. https://www.bespokelabs.ai/bespoke-minicheck
- Comprehensive Taxonomy of Hallucinations (arXiv 2508.01781). https://arxiv.org/pdf/2508.01781
- Tang et al. Omissions in Medical Summarization (2023). https://arxiv.org/pdf/2311.08303

## 9. Eval-set sample design (sweep-2)

- NanoFlux: Adversarial Dual-LLM Evaluation (Sep 2025). https://www.arxiv.org/pdf/2509.23252
- EvalAssist / IBM (EMNLP 2025). https://research.ibm.com/publications/synthetic-data-for-evaluation-supporting-llm-as-a-judge-workflows-with-evalassist
- Hard Negative Mining for Domain-Specific Retrieval (ACL 2025 Industry). https://aclanthology.org/2025.acl-industry.72.pdf
- BEACON Bayesian Optimal Stopping (2025). https://arxiv.org/pdf/2510.15945
- FAQ Factorized Active Querying (2026). https://arxiv.org/pdf/2601.20251
- IRT for LLM eval (2025). https://arxiv.org/html/2505.15055v3
- Adaptive Testing for LLM Eval. https://arxiv.org/pdf/2511.04689
- MetaBench (ICLR 2025). https://proceedings.iclr.cc/paper_files/paper/2025/file/4ebc26584810a189ef1e4f173aba4319-Paper-Conference.pdf
- Holm-Bonferroni method. https://en.wikipedia.org/wiki/Holm%E2%80%93Bonferroni_method
- Patronus FinanceBench. https://huggingface.co/datasets/PatronusAI/financebench
- Statsig — Golden datasets evaluation standards. https://www.statsig.com/perspectives/golden-datasets-evaluation-standards
- Maxim — Building a Golden Dataset. https://www.getmaxim.ai/articles/building-a-golden-dataset-for-ai-evaluation-a-step-by-step-guide/

## 10. Drift detection & longitudinal monitoring (sweep-2)

- When +1% Is Not Enough: Paired Bootstrap Protocol (arXiv 2511.19794). https://arxiv.org/pdf/2511.19794
- LLM Output Drift cross-provider validation (arXiv 2511.07585). https://arxiv.org/pdf/2511.07585
- LLM Model Drift Detection 2026 (Stack Pulsar). https://stackpulsar.com/blog/llm-model-drift-detection/
- What is LLM Drift 2026 (Future AGI). https://futureagi.com/blog/what-is-llm-drift-2026
- Galileo Signals — Databricks Summit 2025. https://www.databricks.com/dataaisummit/session/sponsored-galileo-technologies-inc-taming-rogue-ai-agents-observability
- Galileo: 9 Best LLM Output Drift Monitoring Platforms. https://galileo.ai/blog/best-llm-output-drift-monitoring-platforms
- Gemini API release notes / changelog. https://ai.google.dev/gemini-api/docs/changelog
- Gemini model versions and lifecycle. https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions
- Model version aliases. https://docs.cloud.google.com/gemini-enterprise-agent-platform/machine-learning/model-registry/model-alias
- AI Model Release Monitoring (PageCrawl.io). https://pagecrawl.io/blog/ai-model-release-monitoring-openai-google-meta
- AI evals as compute bottleneck (HuggingFace EvalEval). https://huggingface.co/blog/evaleval/eval-costs-bottleneck
- Random Prompt Sampling vs. Golden Dataset (DEV). https://dev.to/practicaldeveloper/random-prompt-sampling-vs-golden-dataset-which-works-better-for-llm-regression-tests-1ln7
- TestQuality — LLM Regression Testing Pipeline. https://testquality.com/llm-regression-testing-pipeline/
- Traceloop — Automated Prompt Regression Testing with LLM-as-Judge and CI/CD. https://www.traceloop.com/blog/automated-prompt-regression-testing-with-llm-as-a-judge-and-ci-cd

## 11. Reproducibility / versioning / observability (sweep-2)

- OpenTelemetry GenAI Semantic Conventions. https://opentelemetry.io/docs/specs/semconv/gen-ai/
- OpenTelemetry GenAI attribute registry. https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/
- OpenInference Semantic Conventions (Arize). https://arize-ai.github.io/openinference/spec/semantic_conventions.html
- Langfuse Token & Cost Tracking. https://langfuse.com/docs/observability/features/token-and-cost-tracking
- Helicone Cost Tracking. https://docs.helicone.ai/guides/cookbooks/cost-tracking
- MLflow LLM Tracking. https://mlflow.org/docs/latest/llms/llm-tracking/index.html
- Pydantic Evals overview. https://ai.pydantic.dev/evals/
- Braintrust eval framework. https://www.braintrust.dev/docs/evaluate
- LangSmith Evaluation. https://docs.langchain.com/langsmith/evaluation
- Arize Phoenix (OSS observability). https://github.com/Arize-ai/phoenix
- Patronus Experiments. https://patronus-ai.github.io/patronus-py/experiments/running/
- Caching for LLMs (Brenndoerfer). https://mbrenndoerfer.com/writing/caching-prompt-semantic-invalidation-hit-rates-llm
- Time Travel — LLM-Assisted Semantic Bisection (arXiv 2511.18854). https://arxiv.org/pdf/2511.18854
- Datasette LLM logging. https://llm.datasette.io/en/stable/logging.html
- Simon Willison: Tracking SQLite Database Changes in Git. https://simonwillison.net/2023/Nov/1/tracking-sqlite-database-changes-in-git/
- LLM Observability Guide (Inference.net). https://inference.net/content/llm-observability-monitoring-production-deployments/
- OpenAI system_fingerprint limitations. https://community.openai.com/t/ai-model-fingerprints-are-not-unique-making-them-fairly-useless-for-tracking-model-updates/715497

## 12. Iter design / anchors / sizing (sweep-3, 2026-05-28)

- When +1% Is Not Enough — Paired Bootstrap Protocol (Nov 2025). https://arxiv.org/abs/2511.19794
- JudgeBench (ICLR 2025). https://arxiv.org/abs/2410.12784
- FACTS Grounding (DeepMind 2025). https://arxiv.org/abs/2501.03200
- FaithJudge / Vectara hallucination benchmark v2 (2025). https://arxiv.org/html/2505.04847v1
- FineSurE (ACL 2024). https://aclanthology.org/2024.acl-long.51/
- tinyBenchmarks (Polo ICML 2024). https://arxiv.org/html/2402.14992v1
- metabench (Kipnis 2024). https://arxiv.org/html/2407.12844v2
- MetaEval (AAAI 2026). https://ojs.aaai.org/index.php/AAAI/article/view/40668
- Mediocrity is the Key — anchor-model selection (Mar 2026). https://arxiv.org/abs/2603.16848
- Easy2Hard-Bench: Standardized Difficulty Labels (NeurIPS 2024). https://arxiv.org/abs/2409.18433
- Constructing Domain-Specific Evaluation Sets for LLM-as-a-judge (2024). https://arxiv.org/pdf/2408.08808
- LASER: Stratified Selective Sampling for Instruction Tuning (May 2025). https://arxiv.org/pdf/2505.22157
- Metritocracy: Representative Metrics for Lite Benchmarks (2025). https://arxiv.org/pdf/2506.09813
- Adversarially Constructed Eval Sets Are More Challenging, but May Not Be Fair (Phang). https://arxiv.org/pdf/2111.08181
- How Much Annotation Is Needed (2024). https://arxiv.org/abs/2402.18756
- Limits to Scalable Eval (2024). https://arxiv.org/html/2410.13341v1
- FinanceBench. https://arxiv.org/pdf/2311.11944
- Sample-size-for-rare-events (Win Vector). https://win-vector.com/2013/12/03/sample-size-and-power-for-rare-events/
- USDA NASS / Eval Academy stratified sampling guidance. https://www.evalacademy.com/articles/stratified-random-sampling-in-evaluation
- Hamel Husain — LLM Evals FAQ. https://hamel.dev/blog/posts/evals-faq/
- Pragmatic Engineer — A pragmatic guide to LLM evals. https://newsletter.pragmaticengineer.com/p/evals
- IBM/Anchor-Selection (reference impl for Mediocrity paper). https://github.com/IBM/Anchor-Selection

## 13. Budget-trim sizing (sweep-3-budget, 2026-05-28)

- Steiger paired-correlation difference formula (`2(1−r)·(z_{α/2}+z_{β})²/Δ²+3`). https://powerandsamplesize.com/calculator/pwrss-power-z-steiger/
- tinyBenchmarks IRT-anchor: <2% error from a fixed 100-item anchor reused across all systems. https://arxiv.org/pdf/2402.14992
- tinyBenchmarks GitHub README. https://github.com/felipemaiapolo/tinyBenchmarks
- Chatbot Arena anchor reuse across all C(K,2) pairs. https://arxiv.org/pdf/2406.12319
- Less-is-More (2024) — atomic-fact extractor swap is the lowest-info-gain knob. https://ar5iv.labs.arxiv.org/html/2404.06579v1
- Gemini 2.5 Flash pricing (May 2026): $0.30/M in, $2.50/M out. https://ai.google.dev/gemini-api/docs/pricing
- pricepertoken — Gemini 2.5 Flash. https://pricepertoken.com/pricing-page/model/google-gemini-2.5-flash
