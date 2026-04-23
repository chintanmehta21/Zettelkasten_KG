# Newsletter ingest landscape - 2026-04-22

## Real URL set used for Phase 0.5
- `https://www.platformer.news/substack-nazi-push-notification/`
- `https://organicsynthesis.beehiiv.com/p/organic-synthesis-beehiiv`
- `https://product.beehiiv.com/p/introducing-email-boosts`

## Markup patterns observed locally
- Platformer currently renders as a Ghost-powered custom domain, not `substack.com`.
- The Platformer page exposes `meta[property="og:site_name"] = Platformer`, `meta[name="generator"] = Ghost 6.33`, `h1.gh-article-title`, and `div.gh-content`.
- Beehiiv posts on custom domains expose `meta[property="og:site_name"]`, `meta[property="og:title"]`, `meta[name="description"]`, and a `div.rendered-post` body container.
- Direct `beehiiv.com` post URLs may redirect to the publication's custom domain, so ingest logic must rely on DOM markers as well as the original host.

## Routing notes
- `platformer.news` was initially routed as `web`, which forced the generic schema in `/api/v2/summarize`.
- Adding `platformer.news` to newsletter routing and preserving custom-domain DOM detection fixed the website end-user path for branded newsletter URLs.

## Stance classifier notes
- The newsletter stance prompt originally contained unescaped braces in the JSON-shape instruction.
- Escaping that example fixed formatter crashes and allowed newsletter-specific structured extraction to run instead of falling back to the generic section-list result.
