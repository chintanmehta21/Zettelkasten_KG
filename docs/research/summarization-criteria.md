# Source-Specific Zettel Summarization Criteria

## What the literature rewards

The strongest automatic evaluators do not mainly reward pretty prose. They reward summaries that are faithful to the source, complete on salient content, coherent in structure, and selective enough to avoid fluff. G-Eval improves alignment with human judgments by scoring summaries against explicit criteria such as coherence, consistency, fluency, and relevance through a structured evaluation form, but it also warns that LLM-based evaluators are prompt-sensitive and may prefer LLM-like writing styles. citeturn10view0turn10view3turn20view0turn10view2

FineSurE sharpens that picture for modern summarization. It argues that the most important failure modes are hallucination, omission of key facts, and verbosity, so it centers **faithfulness**, **completeness**, and **conciseness**. It defines completeness as including all key facts from the source and conciseness as excluding non-key-fact material, and it shows the value of sentence-level and keyfact-level assessment rather than only giving one coarse summary score. citeturn9view1turn9view4

QAFactEval and SummaC explain how to operationalize those ideas. QAFactEval tests whether facts in the summary can be converted into questions whose answers are recoverable from the source, while SummaC checks source-summary consistency by scoring sentence pairs instead of relying on coarse document-level comparisons. The same literature also notes an important limitation: factual-consistency benchmarks are still heavily concentrated in news-like domains, so source-specific criteria for GitHub, YouTube, Reddit, and newsletters must be an adaptation of shared principles rather than a literal copy of one benchmark. citeturn11view4turn11view1turn11view3turn14view1turn13view0turn23view0

So the right design principle for your zettels is this: **source-grounded accuracy first, coverage of all major source units second, concise structure third, stylistic smoothness last**. A fluent but generic summary should score below a denser summary that is fully traceable to the source. citeturn9view1turn10view2

## Universal output contract

The academic metrics directly evaluate summary quality, not retrieval metadata like tags and labels. Still, the same logic transfers cleanly: the brief and detailed summaries should optimize for faithfulness, completeness, conciseness, and coherence; tags and labels should optimize for specificity, disambiguation, and fast retrieval. citeturn9view1turn20view0turn11view4turn13view0

Use one scoring frame for all four source types:

- **Brief summary — 25 points.** One paragraph, operationalized as **5–7 sentences** rather than literal rendered lines because line wrapping changes across UIs. Full credit only if a reader can answer: *what is this source, what is it mainly about, what are its major units, and what makes it distinctive?*
- **Detailed summary — 45 points.** Bulleted, with **one bullet per major source unit** in logical order. Full credit only if every major unit is covered once, no major unit is omitted, and no unsupported material is added.
- **Tags — 15 points.** Exactly **7–10 tags**. Full credit only if the set is specific, non-redundant, retrieval-friendly, and tied to the actual source rather than generic summary language.
- **Label — 15 points.** A short title for the zettel. Full credit only if it is the fastest reliable identifier for the source and would still make sense when seen alone in a note list.

Recommended caps make the rubric harder to game:

- Any **invented fact, invented interface, invented person, or invented conclusion** should cap the zettel at **60/100**.
- Missing the **primary thesis, purpose, question, or central source unit** should cap it at **75/100**.
- Generic tags or an ambiguous label should prevent a score higher than **90/100**, even when the prose summary is good.

A **major source unit** is any structurally marked or substantively necessary unit that a reader would expect to recover in a QA-style audit: a repo module or public interface, a video chapter or major topic turn, a Reddit discussion branch or consensus cluster, or a newsletter section/resource block. If that unit would matter in a QAFactEval-style question or a FineSurE-style completeness check, it belongs in the detailed summary.

## GitHub criteria

For repositories, the highest-value signals are not just prose. They are the README, language composition, topic metadata, and any documented public surface such as a website, package API, CLI, demo, or GitHub Pages deployment. GitHub’s own documentation says READMEs should explain what the project does, why it is useful, how to get started, where to get help, and who maintains it; GitHub separately exposes repository languages through Linguist, supports topic metadata for purpose and subject area, and can publish a project site through GitHub Pages. citeturn8view10turn8view5turn19view0turn8view11

- **Brief summary.** Full credit only if the paragraph clearly states the repo’s **core function**, **artifact type** (library, web app, CLI, model, template, infra repo, SDK, etc.), **intended user or use case**, **major programming languages**, and any **documented public interface** such as a website, API surface, CLI entry point, or install/run path. A weak GitHub brief summary is one that says only “this repository is a tool/library/app” without explaining what problem it solves.

- **Detailed summary.** Full credit only if the bullet list covers the repo’s **major features or modules**, **main stack**, **how it is meant to be used**, and every **important public-facing surface** that is clearly documented or implemented, including API routes, package exports, CLI commands, UI routes, demo sites, or Pages deployments when present. Good repo summaries also capture the repo’s **state of usability** when the source makes that plain: examples, docs, tests, releases, contribution guidance, or major limitations. Do **not** award full credit for a file-by-file dump, a restatement of headings, or inferred claims like “it has an API” when the repo only contains placeholder routes or scaffolding.

- **Tags.** Use 7–10 tags drawn from these slots: **domain/problem area**, **primary language(s)**, **framework/runtime**, **interface type** (`cli`, `api`, `web-app`, `sdk`, `extension`, `infra`), **deployment or ecosystem context**, and **strong repo topics**. Full-credit tags are specific enough to retrieve the repo later, such as `fastapi`, `browser-extension`, `rag`, `terraform`, `postgres`, `electron`, or `vector-search`. Generic tags like `code`, `github`, `software`, or `project` should count against the score unless your broader note system truly needs one source-type marker.

- **Label.** Use the **exact `owner/repo` slug**. For GitHub, the stable repository identifier is more useful than the 3–5-word preference. If the repo is a monorepo, keep the root slug as the label and express the subproject in the brief summary or tags instead of rewriting the canonical identifier.

## YouTube criteria

For videos, the portable high-quality signals are thesis preservation, chapter or topic coverage, chronological coherence, and retention of demonstrations, examples, or conclusions. YouTube’s own structure supports this directly: chapters divide a video into sections that add context, and transcripts make spoken content searchable and time-addressable. A strong YouTube zettel should therefore behave like a compressed topic map of the actual video, not a generic description of its theme. citeturn8view6turn8view7turn20view0turn9view1

- **Brief summary.** Full credit only if the paragraph captures the video’s **central thesis or promise**, **format** (tutorial, interview, commentary, lecture, review, debate, walkthrough, reaction), **intended audience**, and the **major segments** of the video. For tutorials, it should state the outcome or skill the viewer gets. For interviews or debates, it should identify the main parties and the core positions they take. A weak brief summary is one that names the topic but loses the argument or teaching arc.

- **Detailed summary.** Full credit only if the bullet list covers **every substantive chapter or topic turn** in the video. If creator-defined chapters exist, each substantive chapter should appear. If chapters do not exist, segment by major topic shifts, demonstrations, examples, and conclusions. Missing one major topic is a major completeness failure. Strong detailed summaries preserve **chronological order**, **demonstrations or examples**, **warnings or caveats**, **recommended actions**, and the **closing takeaway**. Do not waste bullets on generic intros, sponsor reads, or “like and subscribe” material unless they materially affect the content.

- **Tags.** Use 7–10 tags covering **topic/domain**, **creator or channel**, **format**, **named tools/concepts**, **audience or use case**, and any **signature examples**. Full-credit tags make the video retrievable both by subject and by context, such as `tutorial`, `interview`, `react`, `macroeconomics`, `cinematography`, `langchain`, `beginner`, or `case-study`.

- **Label.** Use a **3–5-word neutral title** that preserves the real subject rather than the source’s clickbait phrasing. If creator identity materially changes the meaning, include the creator or channel compactly; otherwise prefer a content-first title. In other words, label the zettel by what the video is **actually about**, not by the hook it used to get opened.

## Reddit criteria

For Reddit, quality depends on preserving community context as well as content. Reddit is organized around communities, posts, comments, voting, and engagement signals; posts and comments can be edited; and visible comment counts can exceed visible comments because removed comments still remain counted. That means a strong Reddit zettel must separate the original post, the dominant answer clusters, visible engagement signals, and any uncertainty created by edits, moderation, or missing comments. Upvotes can indicate perceived contribution, but they are not proof of factual correctness. citeturn22view1turn8view8turn16view0turn16view1turn16view2turn9view1

- **Brief summary.** Full credit only if the paragraph captures the **subreddit context**, the **OP’s question/claim/story**, the **dominant response pattern**, the **strongest disagreement or alternative view**, and the **apparent consensus or lack of consensus**. If the thread is polarized, anecdotal, or lightly evidenced, the brief summary should say so instead of presenting false certainty.

- **Detailed summary.** Full credit only if the bullets separate **OP intent**, **major reply clusters**, **strongest supporting examples or evidence**, **counterarguments**, **moderator or rule context** when it shaped the discussion, and any **unresolved questions**. Order should follow argumentative importance, not just chronology. Good Reddit summaries also understand thread type: advice, troubleshooting, AMA, support, news reaction, meta discussion, rumor checking, or community drama. Do not over-reward joke chains or side chatter unless they become the dominant tone of the thread.

- **Tags.** Use 7–10 tags covering **subreddit**, **topic/problem**, **thread type**, **stance or outcome**, **evidence style** (`anecdotal`, `expert-reply`, `news-reaction`, `troubleshooting`), and the **affected audience**. Avoid tagging individual usernames unless a specific person is central to the thread’s meaning. Tags should help you recover both the subject matter and the social shape of the discussion.

- **Label.** Prefer **`r/subreddit` plus a compact issue title**, ideally still fitting the 3–5-word spirit. A good label is neutral and descriptive, such as `r/sysadmin backup policy debate` or `r/AskHistorians Roman roads`. Do not use meme phrasing, sarcasm, or outrage framing in the label, because that reduces retrieval value.

## Newsletter criteria

For newsletters, the summary has to preserve both editorial meaning and inbox context. Mailchimp’s guidance treats the **from name**, **subject line**, **preheader**, **body copy**, and **call to action** as distinct elements; it emphasizes concise body copy, hierarchy, and mobile-first scannability; and it treats the subject/preheader pair as part of the message framing before readers even open the issue. A strong newsletter zettel should therefore capture **publication identity**, **issue thesis**, **section structure**, **important linked resources**, and the **reader action or implication**, not merely paraphrase the headline. citeturn18view0turn8view9turn17search2

- **Brief summary.** Full credit only if the paragraph states the **publication or sender identity**, the **main thesis or agenda of the issue**, the **intended audience**, the **major sections or themes**, and any **concrete implication, ask, or CTA**. If the newsletter mixes editorial analysis with promotion or product announcements, the brief summary should preserve that balance instead of flattening everything into one generic topic sentence.

- **Detailed summary.** Full credit only if the bullet list follows the newsletter’s real hierarchy: **opening promise**, **headline/thesis**, **major sections**, **important examples/data/links/resources**, and the **final CTA or next step**. Ignore footer boilerplate, unsubscribe language, and repetitive house style unless they materially affect meaning. Sponsor or promotional content should only get a bullet if it is substantively part of the issue; otherwise it should not displace editorial content in the summary.

- **Tags.** Use 7–10 tags covering **publication**, **industry/topic**, **recurring section name if relevant**, **named people/companies/products**, **content type** (`analysis`, `roundup`, `product-update`, `market-note`, `operator-advice`), and the **intended action**. Full-credit tags should make the zettel retrievable both by source and by thesis.

- **Label.** Use **publication plus thesis** in **3–5 words when possible**. If the issue belongs to a strongly named series, that series can substitute for the full publication name when it is the more durable retrieval handle. The label should read like a clean archive title, not marketing copy.

