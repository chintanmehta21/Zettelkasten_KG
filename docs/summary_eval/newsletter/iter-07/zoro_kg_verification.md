# Zoro KG Verification

- Prod-parity run: iter-07 completed with `env=prod-parity`.
- Documented runbook UUID `a57e1f2f-7d89-4cd7-ae39-72c440ed4b4e` is the Zoro `render_user_id`, not the `kg_users.id`; direct writes require KG user id `8e1d63a7-f9b7-4050-a28d-540590218833`.
- KG writes: 5 newsletter nodes created for Zoro from iter-07 held-out summaries.
- Live schema compatibility: production `kg_nodes` lacks `engine_version`, `extraction_confidence`, and `summary_v2`, and still constrains newsletter-like records to legacy `source_type=substack`; repository fallback was added and verified during the write.

## Nodes Created

- `nl-platformer-substack-s-algorithmic-promotion-of-extremist-co`
- `nl-recent-chemical-research-highlights-advancements-in-organic`
- `nl-the-pragmatic-engineer-the-product-minded-engineer-in-the-a`
- `nl-beehiiv-mcp-integrates-with-ai-clients-as-a-business-os`
- `nl-beehiiv-email-boosts-enable-in-newsletter-paid-recommendati`

## RAG Check

- Direct KG retrieval verified the 5 nodes under Zoro.
- Browser RAG check was not completed because the checked `docs/login_details.txt` credentials returned invalid Supabase Auth credentials; this is recorded as a prod-parity skip reason rather than silently claiming chat verification.
