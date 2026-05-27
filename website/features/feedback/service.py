"""Top-level orchestrator: validated input → Slack uploads → Slack post.

Caller (the API route) is responsible for:
  - Parsing multipart form data
  - Running rate-limit + auth gates
  - Validating + image-pipelining the screenshots BEFORE handing to .submit()
  - Wrapping .submit() in fire_and_forget if the response should return early

Returns a freshly minted FB-XXXX confirmation ID.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from website.features.feedback.core.identity import Identity
from website.features.feedback.core.ids import generate_feedback_id
from website.features.feedback.intake.models import FeedbackSubmitRequest
from website.features.feedback.slack.block_kit import build_feedback_blocks

logger = logging.getLogger("feedback.service")


@dataclass
class FeedbackService:
    """Stateless orchestrator. Holds a Slack client; no DB."""
    slack_client: object  # Duck-typed FeedbackSlackClient

    async def submit(
        self,
        *,
        request: FeedbackSubmitRequest,
        identity: Identity,
        processed_images: list[tuple[str, bytes]],
    ) -> str:
        """Upload images, post the message, return the feedback ID.

        processed_images: list of (filename, body) tuples — already validated
                          + EXIF-stripped by the API route.
        """
        feedback_id = generate_feedback_id()

        file_ids: list[str] = []
        for filename, body in processed_images:
            fid = await self.slack_client.upload_image(content=body, filename=filename)
            file_ids.append(fid)

        blocks = build_feedback_blocks(
            intent=request.intent,
            subject=request.subject,
            description=request.description,
            identity=identity,
            feedback_id=feedback_id,
            follow_up_email=bool(request.follow_up_email and identity.email),
            slack_file_ids=file_ids,
        )
        fallback = f"New feedback from {identity.full_name}: {request.subject}"

        ts = await self.slack_client.post_message(blocks=blocks, fallback_text=fallback)
        logger.info(
            "feedback delivered",
            extra={"feedback_id": feedback_id, "slack_ts": ts,
                   "intent": request.intent.value, "n_images": len(file_ids)},
        )
        return feedback_id


# Convenience for tests / scripts that need a free-standing call.
async def submit_feedback(
    *, service: FeedbackService, **kwargs,
) -> str:
    return await service.submit(**kwargs)
