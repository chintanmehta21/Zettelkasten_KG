"""Build the Slack Block Kit payload for a feedback submission.

The payload references already-uploaded files via slack_file blocks (private
to the workspace; no public URLs). See:
https://slack.com/blog/developers/uploading-private-images-blockkit
"""
from __future__ import annotations

from website.features.feedback.core.identity import Identity
from website.features.feedback.intake.models import FeedbackIntent


_INTENT_HEADER = {
    FeedbackIntent.ISSUE:      ("\U0001F4E3", "Issue"),       # 📣
    FeedbackIntent.SUGGESTION: ("\U0001F4A1", "Suggestion"),  # 💡
}


def _quote(description: str) -> str:
    """Format as Slack blockquote (prefix '> ' per line)."""
    return "\n".join(f"> {line}" for line in description.splitlines() or [""])


def build_feedback_blocks(
    *,
    intent: FeedbackIntent,
    subject: str,
    description: str,
    identity: Identity,
    feedback_id: str,
    follow_up_email: bool,
    slack_file_ids: list[str],
) -> list[dict]:
    """Return the full blocks array for chat.postMessage."""
    emoji, label = _INTENT_HEADER[intent]

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} New feedback — {label}",
            },
        },
    ]

    # Context line
    parts = [
        f"*From:* {identity.full_name}",
        f"*Country:* {identity.country_label}",
        f"*ID:* `{feedback_id}`",
    ]
    if follow_up_email and identity.email:
        parts.append(f"*Reply:* {identity.email}")
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "  •  ".join(parts)}],
    })

    blocks.append({"type": "divider"})

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Subject:* {subject}\n{_quote(description)}",
        },
    })

    for idx, file_id in enumerate(slack_file_ids, start=1):
        blocks.append({
            "type": "image",
            "alt_text": f"Screenshot {idx}",
            "slack_file": {"id": file_id},
        })

    return blocks
