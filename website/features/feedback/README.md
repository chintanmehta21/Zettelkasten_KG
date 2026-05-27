# Feedback feature

Self-contained module providing a footer "Send feedback" button + popup that
posts Issues / Suggestions to Slack `#zk-testing`.

## Module layout

```
website/features/feedback/
├── api/          FastAPI routes + deps + cookie helpers
├── core/         Settings, identity resolver, ID generator
├── intake/       DTOs, validation, image pipeline, rate limit
├── slack/        Slack client + Block Kit builder
├── ui/           CSS, JS, SVG, HTML templates
├── tests/        unit / integration / live
├── __init__.py   register(app) entry point
├── service.py    Top-level orchestrator
└── README.md     this file
```

## Spec

[docs/superpowers/specs/2026-05-27-feedback-button-design.md](../../../docs/superpowers/specs/2026-05-27-feedback-button-design.md)

## Operational setup

[docs/mockups/feedback/SLACK_SETUP.md](../../../docs/mockups/feedback/SLACK_SETUP.md)

## Tests

```bash
# Unit + integration (default — no network)
pytest website/features/feedback/

# Live Slack delivery (requires SLACK_BOT_TOKEN_FEEDBACK + SLACK_CHANNEL_FEEDBACK)
pytest website/features/feedback/ --live
```

## How to swap the icon

Edit `SVG_MEGAPHONE_SOLID` / `SVG_MEGAPHONE_OUTLINE` constants in `ui/static/feedback.js`. Five alternates documented in [docs/mockups/feedback/icons.html](../../../docs/mockups/feedback/icons.html).
