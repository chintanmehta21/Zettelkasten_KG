# Website Features

This website is the web interface for the Zettelkasten system: it lets someone paste a URL, turn it into a structured AI summary, store that result inside a personal knowledge graph, and then work with that knowledge through browsing, filtering, curation, and grounded question-answering. The public side is useful even without signing in because it can summarize content on demand and expose the shared graph view. Once a user signs in, the product becomes a personal knowledge workspace with saved zettels, curated kastens, avatar-backed profile state, and retrieval-augmented chat over their own notes. Under the hood, the website also includes its own v2 summarization engine, knowledge-graph intelligence layer, browser-side UX safeguards, and Gemini key-routing logic so the experience remains usable as volume and complexity grow. In short, the site is not just a landing page; it is a full capture, storage, exploration, and reasoning surface for a second-brain workflow.

## summarization_engine

- This is the core web summarization engine that accepts URLs from multiple source types and turns them into structured Zettelkasten-style outputs rather than loose freeform text.
- From an end-user perspective, the best part is that one workflow can handle very different inputs such as YouTube, GitHub, newsletters, Reddit-style links, and generic web pages without making the user think about the extraction details.
- It now has a v2 API layer for both single-URL and batch summarization, so the website is not limited to one-at-a-time manual usage.
- Writers are composable, which means summaries can be routed to places like Supabase, Obsidian-style markdown, or GitHub-backed storage depending on the deployment mode.
- The current limitation is that source support and output quality still depend on extractor maturity, live upstream availability, and configured AI credentials.

## knowledge_graph

- This is the interactive graph viewer that turns saved zettels into connected nodes and links so the knowledge base can be explored spatially rather than only through lists.
- The strongest end-user advantage is discoverability: people can search notes, inspect relationships, filter by source, and move between clusters of related ideas visually.
- It supports both a broader graph view and a user-scoped "My Graph" mode, which makes the same interface useful for public exploration and private knowledge work.
- The detail panel helps the graph feel practical instead of ornamental because a node can become an entry point into the actual note and its metadata.
- Its current limitation is that the value of the graph depends heavily on how rich the stored nodes, tags, and links already are; sparse data will naturally make the graph feel less insightful.

## kg_features

- This is the intelligence layer on top of the raw graph, adding entity extraction, embeddings, graph analytics, natural-language querying, traversal helpers, and hybrid retrieval.
- For end users, the biggest win is that the graph can move beyond simple tag links and start surfacing semantic and structural relationships that are harder to see manually.
- It improves future experiences such as better auto-linking, more meaningful graph neighborhoods, smarter retrieval, and richer answers inside graph-aware search or chat.
- The natural-language-to-SQL and retrieval features show that the graph is being treated as a real queryable knowledge system, not just a visual artifact.
- The limitation today is that these capabilities are more infrastructure-heavy than the visible graph page itself, so some benefits are indirect until more UI surfaces expose them explicitly.

## rag_pipeline

- This is the retrieval-augmented generation pipeline that prepares queries, retrieves context, builds citations, generates answers, and verifies the answer quality before returning it.
- The best user-facing outcome is grounded chat: answers are meant to come back tied to actual saved notes rather than generic model memory alone.
- It supports scoped retrieval using sandboxes, source filters, tags, sessions, and quality modes, which makes the system useful for both quick lookup and deeper research conversations.
- Citation building and answer criticism are especially important because they push the chat experience toward trustworthiness instead of just fluency.
- The limitation is that this path is only as good as the indexed notes and retrieval coverage available for the user, so empty or weakly curated datasets will reduce answer quality.

## user_auth

- This feature handles website authentication through Supabase Auth with Google OAuth and the supporting browser behavior needed for login, redirect, and profile hydration.
- For users, the best part is that the website can transition from a public summarizer into a personal workspace without forcing a separate product or complicated account flow.
- It also supports a stable signed-in UI state with avatar rendering and protected API access, which makes the rest of the personalized features possible.
- The auth flow is intentionally paired with minimal browser persistence so convenience does not require storing sensitive session material in custom client-side caches.
- The practical limitation is that the richer parts of the website depend on Supabase being configured correctly; without that setup, signed-in features are naturally unavailable.

## user_home

- This is the signed-in dashboard that acts as the entry point to the personal workspace after login.
- Its best user-facing quality is orientation: instead of dropping someone into raw infrastructure, it gives them a recognizable home for profile access, note creation, and navigation to zettels, kastens, RAG chat, and related tools.
- It also handles avatar setup and lightweight personalization, which helps the product feel like an owned workspace rather than a temporary demo surface.
- The ability to add new zettels directly from the home area shortens the distance between capture and organization.
- The limitation is that it is mainly a hub, so its value depends on the surrounding features already being populated and working.

## user_zettels

- This is the per-user zettel management view for browsing the notes a signed-in user has already captured.
- From the user side, the best part is control: notes can be searched, filtered, sorted, opened in a summary view, and managed from one dedicated place instead of being scattered across the graph or hidden behind APIs.
- It gives the personal knowledge base a library-like surface, which is important for people who want direct access to individual notes before moving into curation or chat.
- The add-zettel flow inside this area makes it possible to keep expanding the vault without leaving the management screen.
- The current limitation is that this view is still centered on note operations rather than deeper synthesis, so users usually step into kastens, graph, or RAG when they want higher-level reasoning.

## user_kastens

- This feature lets users create curated "kasten" workspaces by selecting exactly which zettels belong to a given line of thought.
- The strongest end-user benefit is focus: instead of querying the whole vault every time, a user can build a smaller, intentional context pack for a topic, project, or research question.
- It supports creating, editing, and deleting these curated collections, reviewing their members, and sending a chosen kasten directly into the chat flow.
- The search-and-add workflow makes the curation step feel practical, not theoretical, because users can assemble context from their real saved notes.
- The limitation is that the usefulness of a kasten still depends on the quality and coverage of the zettels inside it; a weak collection will produce a weak scoped chat.

## user_rag

- This is the user-facing chat interface built on top of the RAG pipeline, where saved knowledge can be interrogated through conversational queries.
- The best part for end users is that answers are scoped and inspectable: they can choose a kasten, adjust quality mode, narrow by tags or source, and review citation-rich responses.
- Session history and example queries lower the barrier to repeated use, so the feature behaves more like a working research assistant than a one-off demo box.
- It is especially valuable when someone wants synthesis across many saved notes without manually opening and comparing them all.
- The limitation is that it is still bounded by retrieval quality and available context, so it will perform best when the underlying notes are already clean, relevant, and well-curated.

## api_key_switching

- This is the Gemini API routing and key-pool layer that keeps the website usable under quota pressure by rotating keys and shifting between model tiers.
- The best user-facing part is invisible reliability: users get fewer hard failures because the site can retry with another key or a lighter model before giving up.
- It also enables more cost-aware routing, helping simple requests avoid consuming the highest-value model capacity unnecessarily.
- Backward compatibility is preserved because the system can still fall back to a single legacy key when multi-key configuration is not available.
- The limitation is that this is resilience logic, not magic; if every configured key and model path is exhausted, quality must degrade or the request must fail gracefully.

## browser_cache

- This is a deliberately tiny browser-side cache used mainly to stabilize the public auth and redirect experience.
- For users, the best part is smoother navigation: the site can remember safe, non-sensitive hints such as return paths and lightweight state without exposing tokens or profile payloads.
- The feature matters because it helps the landing page, login flow, and post-login redirection feel consistent even across reloads.
- Its security posture is a strength in itself: it is explicitly designed to avoid treating local browser storage as trusted auth state.
- The limitation is intentional minimalism, which means it should not be expected to behave like full offline storage, a user profile cache, or a persistence layer for sensitive data.
