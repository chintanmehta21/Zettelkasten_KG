# Summarization Criteria for GitHub, YouTube, Reddit, and Newsletter Sources

## Overview

Automatic summarization metrics such as G-Eval, FineSurE, QAFactEval, and SummaC converge on a common set of quality dimensions: factual faithfulness to the source, coverage/completeness of key content, relevance/focus, and coherence/fluency of the wording. High‑scoring summaries under these evaluators are those that accurately reflect source facts, capture all major points without hallucinations, remain concise and topic‑focused, and read as well‑structured text. These generic dimensions can be instantiated in source‑specific criteria tailored to GitHub repositories, YouTube videos, Reddit threads, and newsletters while keeping the same underlying principles.[^1][^2][^3][^4][^5][^6]

The following sections define concrete criteria for each of the four required components of a Zettel—brief summary, detailed summary, tags, and label—for each source type. Each criterion is designed so that a summary optimized for it will generally score well under G‑Eval (coherence, consistency, fluency, relevance), FineSurE (faithfulness, completeness, conciseness), and QA/NLI‑based factuality measures like QAFactEval and SummaC.[^2][^3][^4][^7][^8][^5][^6][^1]

## Shared evaluation dimensions

Regardless of source type, a high‑quality Zettel should be judged against four shared dimensions derived from modern summarization evaluation work:[^9][^3][^4][^5][^6][^1][^2]

- **Faithfulness / Consistency**: Every claim in the summary must be entailed by or directly supported by the source; no hallucinated features, events, or opinions.
- **Coverage / Completeness**: All major facts, sections, arguments, and perspectives present in the source’s main content are represented somewhere in the brief or detailed summary, with no systematic omissions.
- **Relevance / Focus / Conciseness**: The summary prioritizes the most important information, avoids minor tangents, and remains compact while still complete, aligning with “focus” and “conciseness” dimensions in the literature.[^8][^6][^9][^2]
- **Coherence / Fluency**: Sentences are grammatical, logically ordered, and form a coherent narrative, reflecting G‑Eval’s coherence and fluency criteria.[^5][^1]

In the source‑specific criteria below, each bullet implicitly targets one or more of these dimensions.

***

## GitHub repository Zettel

### Brief summary (5–7 sentence paragraph)

- Clearly state what the repository does in user‑facing terms (problem solved, domain, typical use cases), grounded strictly in README, code, or docs content (faithfulness, relevance).[^10]
- Identify the main components or architecture at a high level (e.g., CLI tool, web API, library modules) without speculating beyond the code or documentation (faithfulness, coverage).[^10]
- Mention the primary programming languages and major frameworks or libraries as indicated in the repo metadata or files (coverage, consistency).
- Describe how the project is used in practice (installation, basic usage pattern, or workflow) only if this is explicitly documented (faithfulness, focus).
- If the repo exposes a web service or UI, summarize the main endpoints or user flows (e.g., REST routes, web pages) derived from routes, configuration, or docs (coverage, factual consistency).
- Convey the maturity or status of the project only when clearly signaled (e.g., “experimental”, “production‑ready”, version tags), avoiding inferred judgments (faithfulness, conciseness).

### Detailed summary (bulleted list of major topics)

- List core functionalities and features as bullets, each tied to explicit functions, modules, or documented capabilities; avoid inferred features not present in the code or docs (faithfulness, QAFactEval‑style QA alignment).[^3][^11]
- Include bullets for architecture and structure: major directories/modules, key classes, and how they interact (coverage, coherence).
- Add bullets for interfaces: public APIs, CLI commands, configuration options, or web endpoints, referencing names and parameters exactly as in the repo (faithfulness, SummaC‑style consistency).[^4][^12]
- Capture operational aspects: installation steps, dependencies, environment variables, build tools, and deployment instructions where available (coverage, relevance).
- Note any documented limitations, assumptions, or security/privacy considerations instead of inventing them (faithfulness, completeness).
- If benchmarks, tests, or examples exist, summarize what they demonstrate (datasets, metrics, example scenarios) without extrapolating beyond reported results (faithfulness, focus).
- Keep each bullet focused on one coherent aspect (feature, component, workflow) to maximize readability and coherence.

### Tags (7–10 tags)

Criteria for selecting tags:

- Include tags for the main domain or application (e.g., `web-scraping`, `time-series-forecasting`, `static-site-generator`) derived directly from README or docs (faithfulness, relevance).
- Add tags for primary programming languages and frameworks (e.g., `python`, `typescript`, `react`, `django`).
- Include key technical concepts present in the repo (e.g., `rest-api`, `cli-tool`, `data-visualization`, `ml-model-serving`).
- Reflect deployment/usage context if explicitly stated (e.g., `docker`, `kubernetes`, `serverless`).
- Avoid tags that are not clearly supported by the repo content (e.g., claiming `production-ready` without evidence) to satisfy factual consistency metrics.

### Label (3–5 word title)

- Always use the canonical GitHub form `user-name/repo-name` as the Zettel title (e.g., `openai/gym`), exactly matching the repository path (faithfulness, consistency).
- Do not prepend or append extra descriptors; qualifiers should appear only in the summary or tags.

***

## YouTube video Zettel

### Brief summary (5–7 sentence paragraph)

- Begin with the overall topic, format, and purpose of the video (e.g., tutorial, lecture, interview, documentary), anchored in title, description, and content (faithfulness, relevance).
- Summarize the main thesis or learning objective of the video in one sentence, reflecting the central message rather than a list of details (coverage, focus).[^13][^14]
- Describe the high‑level structure (e.g., intro, several main sections, demo, Q&A) and how the speaker progresses through topics, preserving the order of major segments (coherence, coverage).
- Mention key entities: host/speaker, guests, product or library discussed, and any important datasets, tools, or case studies explicitly referenced (faithfulness, completeness).
- Highlight 2–3 most important takeaways or conclusions that a viewer would remember after watching, ensuring they are directly supported by the video (faithfulness, G‑Eval consistency).[^1]
- If the video includes code, math, or step‑by‑step procedures, summarize only those steps that are central to the main outcome, not every minor action (relevance, conciseness).

### Detailed summary (bulleted list of major topics)

- Use bullets ordered according to the video timeline, grouping content into coherent segments (e.g., “Problem definition”, “Method explanation”, “Live demo”, “Limitations and next steps”) to maximize coherence and coverage.[^9]
- For each segment, include key claims, definitions, or steps, using wording that is faithful to what was said rather than inferred extrapolations (faithfulness, QA‑style factuality).[^11][^3]
- Capture all major topics the creator appears to intend as learning objectives (e.g., core concepts taught, major API calls shown, main arguments made) to optimize completeness.[^2][^8]
- When examples, analogies, or stories are used to clarify a concept, summarize their purpose and what they illustrate rather than reproducing them verbatim (relevance, conciseness).
- Note any explicit caveats, limitations, or alternative viewpoints that the speaker mentions to maintain factual balance (faithfulness, coverage).
- Avoid introducing external facts, criticisms, or context not present in the video unless clearly labeled as external commentary (faithfulness, SummaC‑style consistency).[^4]

### Tags (7–10 tags)

Criteria for selecting tags:

- Include topical tags capturing the main subject matter (e.g., `transformers`, `options-trading`, `docker-basics`).
- Add tags for the content type and level (e.g., `tutorial`, `conference-talk`, `beginner`, `advanced`).
- Tag key technologies, libraries, or frameworks explicitly used (e.g., `pytorch`, `nextjs`, `pandas`).
- Tag the primary domain or application field (e.g., `cloud-infrastructure`, `personal-finance`, `sports-analytics`).
- Include the channel or speaker name as a tag only if the Zettel is part of a recurring series where author identity matters.
- Avoid speculative tags that imply topics not actually covered in the video to preserve evaluator‑friendly faithfulness.

### Label (3–5 word title)

- Condense the video’s main promise into a short, declarative title (e.g., `Building a REST API`, `Intro to Fourier Transforms`) that closely mirrors the actual YouTube title but removes clickbait and non‑informative fragments (relevance, conciseness).
- Ensure the label reflects the primary topic, not side tangents or minor segments, to keep focus aligned with relevance metrics.[^5][^1]

***

## Reddit thread Zettel

### Brief summary (5–7 sentence paragraph)

- Start by stating the original post’s core question, problem, or claim, using neutral wording faithful to the OP (faithfulness, relevance).
- Summarize the range of responses: main solution(s), common advice patterns, disagreements, and notable edge‑case opinions, without over‑weighting a single comment (coverage, completeness).
- Describe whether there is consensus, partial agreement, or strong disagreement, grounded in the distribution and upvotes of comments where observable (faithfulness, coherence).
- Mention any frequently cited resources, tools, or evidence (e.g., links, benchmarks, anecdotes) that shape the discussion (coverage, QA‑style factuality).[^3][^11]
- Highlight any important caveats (e.g., regional differences, legal constraints, risks) that commenters repeatedly emphasize, avoiding personal speculation (faithfulness, relevance).
- Maintain a neutral tone that reports the community’s views rather than adding the summarizer’s own judgment, aligning with factual consistency metrics.[^4]

### Detailed summary (bulleted list of major topics)

- Use bullets to represent major clusters of opinions or themes (e.g., “Pro‑X arguments”, “Concerns about Y”, “Alternative approach Z”) instead of individual comments, reflecting an opinion‑summarization style.[^14][^13]
- Within each bullet, capture the key reasoning and representative examples provided by commenters, but do not attribute unverified facts as truths; mark them as claims where needed (faithfulness, SummaC‑style consistency).[^12][^4]
- Include bullets for minority or contrarian viewpoints when they introduce substantively different information or risks, even if they are less upvoted (coverage, completeness).
- Note any data, experiments, or external references that multiple commenters use to support their positions, but do not fabricate quantitative details (faithfulness, QAFactEval‑aligned factuality).[^11][^3]
- Avoid summarizing off‑topic jokes, tangents, or meta‑discussion unless they materially affect how the main question is answered (relevance, conciseness).
- Keep bullets thematically coherent and avoid mixing unrelated subtopics in a single bullet to improve coherence.

### Tags (7–10 tags)

Criteria for selecting tags:

- Include tags for the subreddit (e.g., `r/aws`, `r/investing`) and its domain (e.g., `cloud-infrastructure`, `personal-finance`).
- Add tags for the OP’s core topic or decision (e.g., `career-advice`, `tool-comparison`, `data-engineering`).
- Tag key technologies, products, or services discussed (e.g., `hetzner`, `digitalocean`, `kubernetes`).
- Include tags describing the type of discussion (e.g., `q-and-a`, `experience-reports`, `best-practices`).
- Avoid tags that encode value judgments (e.g., `bad-tool`, `scam`) unless these labels are widely and explicitly agreed upon in the thread (faithfulness, neutrality).

### Label (3–5 word title)

- Form the label from the OP’s core question or decision framed neutrally (e.g., `Hetzner vs DigitalOcean`, `Switching Careers to Data`), removing Reddit‑specific phrasing.
- Ensure the label captures the central issue that the majority of comments address, not side discussions.

***

## Newsletter / email essay Zettel

### Brief summary (5–7 sentence paragraph)

- State the newsletter’s main topic, central thesis, or question in one sentence (e.g., “The author argues that X is reshaping Y”), grounded in the author’s own framing (faithfulness, relevance).
- Summarize how the author structures their argument: key sections or narrative arc (e.g., context, problem, proposed solution, implications) to reflect coverage of the essay’s logic.
- Mention the most important evidence or examples the author uses (data points, case studies, anecdotes) without inventing numbers or sources (faithfulness, QA‑style factuality).[^3][^11]
- Capture the author’s main conclusions or recommendations, clearly distinguishing them from descriptive background (coverage, coherence).
- If the piece includes explicit caveats, limitations, or counterarguments, summarize how the author addresses them (faithfulness, completeness).[^6][^2]
- Maintain a tone that reflects the author’s stance (optimistic, skeptical, cautionary) without editorializing beyond what is in the text.

### Detailed summary (bulleted list of major topics)

- Use bullets to represent major sections or argumentative steps (e.g., “Historical context”, “Current challenges”, “Proposed framework”, “Implications for practitioners”), preserving the article’s logical flow (coherence, coverage).[^9]
- Within each bullet, capture key claims, supporting evidence, and important definitions or distinctions, avoiding any new claims not present in the source (faithfulness, FineSurE faithfulness).[^8][^6][^2]
- Include bullets for notable examples, case studies, or data that the author uses to anchor their argument, but do not extrapolate beyond what is actually stated (faithfulness, consistency).[^4]
- Add a bullet for explicit action items or practical takeaways if the newsletter offers them (e.g., steps to implement a strategy, metrics to track) to maximize perceived completeness.
- If multiple viewpoints or scenarios are discussed (e.g., optimistic vs pessimistic outlooks), dedicate bullets to each, summarizing the assumptions behind them (coverage, coherence).
- Keep bullets concise yet specific, avoiding vague paraphrases that would be penalized by coverage‑oriented evaluators.

### Tags (7–10 tags)

Criteria for selecting tags:

- Tag the main domain and subdomain (e.g., `macroeconomics`, `cloud-cost-optimization`, `time-series-analysis`).
- Include tags for key concepts or frameworks introduced (e.g., `unit-economics`, `moats`, `risk-management`).
- Add tags for any important technologies, sectors, or geographies discussed (e.g., `saas`, `semiconductors`, `china-eu-relations`).
- Tag the type and intent of the piece (e.g., `opinion`, `research-summary`, `how-to`, `case-study`).
- Optionally include the newsletter or author name as a tag when it is a recurring source you track.
- Avoid tags that misrepresent the stance or scope of the piece (e.g., `bullish-call` when the article is neutral), preserving faithfulness and relevance.

### Label (3–5 word title)

- Create a compact, declarative phrase that reflects the main thesis or theme (e.g., `Cloud Cost Optimization Playbook`, `Time Series Clustering Pitfalls`).
- Prefer informative over catchy wording, aligning with relevance and focus dimensions; it should be obvious from the label what the Zettel is about.[^1][^5]

---

## References

1. [Evaluating the performance of LLM summarization prompts with G ...](https://learn.microsoft.com/en-us/ai/playbook/technology-guidance/generative-ai/working-with-llms/evaluation/g-eval-metric-for-summarization) - A technique known as G-Eval has been developed, which uses GPT-4 to evaluate the quality of summarie...

2. [[PDF] FineSurE: Fine-grained Summarization Evaluation using LLMs](https://aclanthology.org/2024.acl-long.51.pdf) - We aim to evaluate summaries using this framework along three vital criteria: the faithfulness of mi...

3. [QAFactEval: Improved QA-Based Factual Consistency ...](https://arxiv.org/abs/2112.08542) - Factual consistency is an essential quality of text summarization models in practical settings. Exis...

4. [SummaC: Re-Visiting NLI-based Models for Inconsistency Detection ...](https://direct.mit.edu/tacl/article/doi/10.1162/tacl_a_00453/109470/SummaC-Re-Visiting-NLI-based-Models-for) - We provide a highly effective and light-weight method called SummaC Conv that enables NLI models to ...

5. [What Is the G-Eval Metric and How Does It Work - Galileo AI](https://galileo.ai/blog/g-eval-metric) - The framework established four evaluation dimensions: coherence, consistency, fluency, and relevance...

6. [FineSurE: Fine-grained Summarization Evaluation using LLMs](https://alphaxiv.org/overview/2407.00908v3) - FineSurE introduces a fine-grained, multi-dimensional framework for summarization evaluation, levera...

7. [FineSurE: Fine-grained Summarization Evaluation using LLMs - arXiv](https://arxiv.org/html/2407.00908v3) - In contrast to similarity-based evaluators, which provide a single composite score, UniEval and G-Ev...

8. [Fine-grained, Multi-dimensional Summarization Evaluation ...](https://arxiv.org/html/2407.00908v2)

9. [FFCI: A Framework for Interpretable Automatic Evaluation of Summarization](https://www.jair.org/index.php/jair/article/view/13167) - In this paper, we propose FFCI, a framework for fine-grained summarization evaluation that comprises...

10. [ReFEree: Reference-Free and Fine-Grained Method for Evaluating ...](https://arxiv.org/html/2604.10520v1) - To address this, we propose ReFEree, a reference-free and fine-grained method for evaluating factual...

11. [[PDF] QAFactEval: Improved QA-Based Factual Consistency Evaluation for ...](https://aclanthology.org/2022.naacl-main.187.pdf)

12. [Codebase, data and models for the SummaC paper in TACL - GitHub](https://github.com/tingofurro/summac) - The SummaC Benchmark consists of 6 summary consistency datasets that have been standardized to a bin...

13. [LLMs as Architects and Critics for Multi-Source Opinion Summarization](https://arxiv.org/abs/2507.04751) - Multi-source Opinion Summarization (M-OS) extends beyond traditional opinion summarization by incorp...

14. [One Prompt To Rule Them All: LLMs for Opinion Summary Evaluation](https://arxiv.org/abs/2402.11683) - Evaluation of opinion summaries using conventional reference-based metrics rarely provides a holisti...

