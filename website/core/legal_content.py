"""Single source of truth for the public legal documents.

Why this module exists: Google OAuth brand verification requires the Privacy
Policy and Terms of Service to each live at a **distinct, directly-reachable
URL** that is server-rendered (viewable with JS disabled / in incognito), does
**not** require login, does **not** redirect, and is hosted on the verified
domain. The ``/about`` page renders these as JS modals, which is great UX but
isn't a crawlable URL on its own.

``render_legal_page_html()`` renders the standalone pages at ``/privacy``,
``/terms``, ``/data-security`` (wired in ``website/app.py``).

The ``/about`` page renders the same documents as in-page modals from its own
copy in ``website/footer/about/js/about.js`` (UI intentionally unchanged). That
copy is a MIRROR of the dicts below — ⚠️ when legal wording changes, update BOTH
this file and ``about.js``.

Keep the wording here in plain English and accurate to actual app behaviour.
"""
from __future__ import annotations

import html

# NOTE: Canonical copy for the standalone /privacy /terms /data-security pages.
# about.js holds a MIRROR of this for the /about modals — edit BOTH together.
LEGAL_DOCS: dict[str, dict] = {
    "privacy": {
        "eyebrow": "Privacy Policy",
        "title": "What We Keep, What We Never Keep",
        "intro": "The browser remembers only the smallest bits of state needed to keep sign-in smooth and the page flow calm.",
        "meta": [
            {"label": "Storage", "value": "Tiny browser hints only"},
            {"label": "Retention", "value": "Return path auto-expires"},
            {"label": "Sensitive data", "value": "Never stored here"},
        ],
        "highlights": [
            "Local storage holds a compact login hint, not your password.",
            "Session storage keeps a short-lived return path for the auth callback.",
            "The theme placeholder is blank for now and ready for future use.",
        ],
        "note": "Designed to reduce friction without turning the browser into a vault.",
        "sections": [
            {
                "title": "What is stored",
                "body": "We store only compact browser hints: whether the browser has logged in before, whether credential persistence was allowed, the preferred landing path, and a blank theme placeholder for the future. When you sign in with Google, we use your name, email address, and profile photo only to create and secure your account and to label your private library.",
            },
            {
                "title": "What is never stored",
                "body": "Passwords, access tokens, refresh tokens, cookies, and other secrets stay out of the custom cache. The browser cache exists for UX continuity, not for secret storage. We do not sell your personal data.",
            },
            {
                "title": "How it behaves",
                "body": "Redirect state is short-lived and is consumed once. If the state is stale or unsafe, it gets dropped automatically so the app falls back to /home instead of guessing.",
            },
        ],
        "footer": "Plain-language summary: keep the cache tiny, keep secrets out, and let the page recover gracefully.",
    },
    "terms": {
        "eyebrow": "Terms of Service",
        "title": "The Rules In Plain English",
        "intro": "Use the app to capture links, organize ideas, and build your graph. The service works best when everyone plays fair.",
        "meta": [
            {"label": "Allowed use", "value": "Personal capture & note-taking"},
            {"label": "Service scope", "value": "Web app and linked capture flow"},
            {"label": "Responsibility", "value": "You own the sources you capture"},
        ],
        "highlights": [
            "You can use the service for your own capture and organization workflows.",
            "Do not abuse the app, overload the service, or use it in ways that break the experience for others.",
            "Content from external sources belongs to those sources and their owners.",
        ],
        "note": "A clean product works best with a clean set of expectations.",
        "sections": [
            {
                "title": "What you can do",
                "body": "You can paste links, create summaries, browse your zettels, and explore the graph. The product is meant to help you keep track of what you have read and captured.",
            },
            {
                "title": "What we ask from you",
                "body": "Use the service responsibly, do not attempt to disrupt the app, and do not rely on it as a substitute for backup copies of important personal material.",
            },
            {
                "title": "What can change",
                "body": "Features may evolve as the product grows. When the experience changes, the goal stays the same: keep capture fast, useful, and easy to revisit.",
            },
        ],
        "footer": "Plain-language summary: capture with care, expect reasonable service behavior, and keep a backup of anything critical.",
    },
    "security": {
        "eyebrow": "Data & Security",
        "title": "How Data Stays Small, Safe, and Useful",
        "intro": "The system is built to keep the useful parts available while keeping the sensitive parts narrow and controlled.",
        "meta": [
            {"label": "Browser cache", "value": "Non-sensitive hints only"},
            {"label": "Login", "value": "Supabase session storage"},
            {"label": "Network friendliness", "value": "Lightweight pages & fallback paths"},
        ],
        "highlights": [
            "The custom browser cache keeps only tiny, non-secret state.",
            "Auth stays in Supabase session storage so the browser can remember a session after the first login.",
            "Fallbacks protect the flow when source extraction or network conditions are rough.",
        ],
        "note": "Security here is about reducing attack surface and reducing surprises at the same time.",
        "sections": [
            {
                "title": "Access model",
                "body": "Authenticated pages fetch profile and graph data with the current session, and the browser cache only stores hints that help the UI decide where to send you next.",
            },
            {
                "title": "Retention model",
                "body": "Return-path data expires after a short time and is consumed once. Anything that is no longer useful is pruned rather than left behind indefinitely.",
            },
            {
                "title": "Reliability model",
                "body": "The app prefers small payloads, graceful fallbacks, and low-friction flows so it remains usable on slow or unstable connections.",
            },
        ],
        "footer": "Plain-language summary: data stays small, sign-in remains persistent, and the browser keeps only what it needs.",
    },
}

# key -> public path. ``security`` is exposed as /data-security (clearer URL).
DOC_ROUTES: dict[str, str] = {
    "privacy": "/privacy",
    "terms": "/terms",
    "security": "/data-security",
}

_NAV_ORDER = ["privacy", "terms", "security"]


def render_legal_page_html(key: str) -> str:
    """Render a self-contained, server-side legal page for ``key``.

    Falls back to the privacy doc for an unknown key (so the routes never 500).
    Pure string build (no Jinja dependency) escaped with :func:`html.escape`.
    """
    doc = LEGAL_DOCS.get(key) or LEGAL_DOCS["privacy"]
    active = key if key in LEGAL_DOCS else "privacy"
    e = html.escape

    meta_html = "".join(
        f'<div class="meta-item"><span class="meta-k">{e(m["label"])}</span>'
        f'<span class="meta-v">{e(m["value"])}</span></div>'
        for m in doc["meta"]
    )
    highlights_html = "".join(f"<li>{e(h)}</li>" for h in doc["highlights"])
    sections_html = "".join(
        f'<section class="sec"><h2>{e(s["title"])}</h2><p>{e(s["body"])}</p></section>'
        for s in doc["sections"]
    )
    nav_html = "".join(
        '<a href="{path}"{aria}>{label}</a>'.format(
            path=DOC_ROUTES[k],
            aria=' aria-current="page"' if k == active else "",
            label=e(LEGAL_DOCS[k]["eyebrow"]),
        )
        for k in _NAV_ORDER
    )

    title = e(doc["eyebrow"])
    canonical = f"https://zettelkasten.in{DOC_ROUTES[active]}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="{title} for Zettelkasten — what is stored, how data is handled, and how your account information is used.">
  <link rel="icon" type="image/svg+xml" href="/favicon.svg">
  <title>{title} | Zettelkasten</title>
  <link rel="canonical" href="{canonical}">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Zettelkasten">
  <meta property="og:title" content="{title} | Zettelkasten">
  <meta property="og:description" content="{title} for Zettelkasten — what is stored, how data is handled, and how your account information is used.">
  <meta property="og:url" content="{canonical}">
  <meta property="og:image" content="https://zettelkasten.in/artifacts/og-cover.png">
  <meta property="og:image:type" content="image/png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="{title} | Zettelkasten">
  <meta property="og:locale" content="en_US">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title} | Zettelkasten">
  <meta name="twitter:image" content="https://zettelkasten.in/artifacts/og-cover.png">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{ --bg:#070b12; --panel:rgba(12,17,26,.7); --border:rgba(255,255,255,.08);
             --text:#e6edf3; --muted:#9aa6b6; --teal:#14b8a6; }}
    * {{ margin:0; padding:0; box-sizing:border-box; }}
    body {{ font-family:'Inter',system-ui,sans-serif; background:var(--bg); color:var(--text);
            line-height:1.6; -webkit-font-smoothing:antialiased; }}
    a {{ color:var(--teal); text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .wrap {{ max-width:760px; margin:0 auto; padding:2rem 1.25rem 4rem; }}
    .top {{ display:flex; align-items:center; justify-content:space-between; gap:1rem;
            padding-bottom:1.5rem; border-bottom:1px solid var(--border); }}
    .brand {{ display:flex; align-items:center; gap:.55rem; font-weight:700; color:var(--text); }}
    .brand img {{ width:28px; height:28px; }}
    .top .back {{ font-size:.9rem; }}
    .kicker {{ color:var(--teal); font-size:.8rem; font-weight:600; letter-spacing:.08em;
               text-transform:uppercase; margin-top:2rem; }}
    h1 {{ font-size:1.9rem; font-weight:700; margin:.4rem 0 .6rem; line-height:1.2; }}
    .intro {{ color:var(--muted); font-size:1.02rem; }}
    .meta {{ display:flex; flex-wrap:wrap; gap:.75rem; margin:1.6rem 0; }}
    .meta-item {{ background:var(--panel); border:1px solid var(--border); border-radius:14px;
                  padding:.7rem .9rem; min-width:160px; flex:1; }}
    .meta-k {{ display:block; color:var(--muted); font-size:.72rem; text-transform:uppercase;
               letter-spacing:.05em; }}
    .meta-v {{ display:block; font-size:.92rem; font-weight:500; margin-top:.15rem; }}
    .glance {{ background:var(--panel); border:1px solid var(--border); border-radius:16px;
               padding:1.1rem 1.25rem; margin:1.4rem 0; }}
    .glance h3 {{ font-size:.78rem; text-transform:uppercase; letter-spacing:.06em;
                  color:var(--muted); margin-bottom:.6rem; }}
    .glance ul {{ list-style:none; display:grid; gap:.5rem; }}
    .glance li {{ padding-left:1.2rem; position:relative; font-size:.94rem; color:var(--text); }}
    .glance li::before {{ content:"›"; position:absolute; left:0; color:var(--teal); font-weight:700; }}
    .sec {{ margin:1.5rem 0; }}
    .sec h2 {{ font-size:1.12rem; font-weight:600; margin-bottom:.4rem; }}
    .sec p {{ color:var(--muted); }}
    .note {{ font-style:italic; color:var(--muted); border-left:2px solid var(--teal);
             padding-left:.9rem; margin:1.5rem 0; }}
    .docnav {{ display:flex; flex-wrap:wrap; gap:1rem; margin:2.5rem 0 0; padding-top:1.5rem;
               border-top:1px solid var(--border); font-size:.92rem; }}
    .docnav a[aria-current="page"] {{ color:var(--muted); font-weight:600; }}
    footer {{ margin-top:2.5rem; padding-top:1.25rem; border-top:1px solid var(--border);
              color:var(--muted); font-size:.85rem; display:flex; flex-wrap:wrap; gap:1rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <a class="brand" href="/" aria-label="Zettelkasten home">
        <img src="/artifacts/logo-zettelkasten.svg" alt=""> Zettelkasten
      </a>
      <a class="back" href="/about">&larr; About</a>
    </div>

    <p class="kicker">{title}</p>
    <h1>{e(doc["title"])}</h1>
    <p class="intro">{e(doc["intro"])}</p>

    <div class="meta">{meta_html}</div>

    <div class="glance">
      <h3>At a glance</h3>
      <ul>{highlights_html}</ul>
    </div>

    {sections_html}

    <p class="note">{e(doc["footer"])}</p>

    <nav class="docnav" aria-label="Legal documents">{nav_html}</nav>

    <footer>
      <a href="/">Home</a>
      <a href="/about">About</a>
      <a href="/privacy">Privacy Policy</a>
      <a href="/terms">Terms of Service</a>
      <a href="/data-security">Data &amp; Security</a>
    </footer>
  </div>
</body>
</html>"""
