"""POST /api/feedback/submit and GET /api/feedback/health."""
from __future__ import annotations

import logging
from typing import Callable

from fastapi import (
    APIRouter, File, Form, HTTPException, Request, Response, UploadFile,
)
from pydantic import ValidationError as PydanticValidationError

from website.features.feedback.api.cookie import (
    COOKIE_MAX_AGE_SECONDS, COOKIE_NAME, issue_cookie_value, validate_cookie_value,
)
from website.features.feedback.api.deps import (
    enforce_rate_limit_or_429,
    get_feedback_rate_limiter,
)
from website.features.feedback.core.identity import resolve_identity
from website.features.feedback.core.settings import get_feedback_settings
from website.features.feedback.intake.image_pipeline import (
    ImageProcessingError, process_image,
)
from website.features.feedback.intake.models import (
    FeedbackIntent, FeedbackSubmitRequest, FeedbackSubmitResponse,
)
from website.features.feedback.intake.validation import (
    ValidationError, sniff_and_validate_image,
)
from website.features.feedback.service import FeedbackService
from website.features.feedback.slack.client import (
    FeedbackSlackClient, build_production_client, SlackPostError,
)

logger = logging.getLogger("feedback.routes")

MAX_IMAGES = 3
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


def build_router(
    *,
    slack_client_factory: Callable[[], FeedbackSlackClient] | None = None,
) -> APIRouter:
    """Construct the router. The factory parameter lets tests inject a mock."""
    router = APIRouter(tags=["feedback"])

    def _resolve_slack_client() -> FeedbackSlackClient | None:
        if slack_client_factory is not None:
            return slack_client_factory()
        settings = get_feedback_settings()
        if not settings.slack_bot_token_feedback or not settings.slack_channel_feedback:
            return None
        return build_production_client(
            token=settings.slack_bot_token_feedback,
            channel=settings.slack_channel_feedback,
        )

    @router.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @router.post("/submit", response_model=FeedbackSubmitResponse, status_code=202)
    async def submit(
        request: Request,
        response: Response,
        intent: FeedbackIntent = Form(...),
        subject: str = Form(..., min_length=1, max_length=120),
        description: str = Form(..., min_length=10, max_length=4000),
        anon_name: str | None = Form(default=None, max_length=80),
        follow_up_email: bool = Form(default=False),
        anon_email: str | None = Form(default=None),
        images: list[UploadFile] = File(default=[]),
    ) -> FeedbackSubmitResponse:
        # 1. Check the feature is enabled.
        slack_client = _resolve_slack_client()
        if slack_client is None:
            raise HTTPException(status_code=503, detail="Feedback is temporarily unavailable.")

        # 2. Identity (auth integration is a follow-up; treat all as anon for now).
        claims = None  # placeholder — will be Depends(get_optional_user) once registered
        identity = resolve_identity(
            claims=claims,
            anon_name=anon_name,
            anon_email=anon_email,
            headers={k.lower(): v for k, v in request.headers.items()},
            profile_country_code=None,
        )
        user_id = (claims or {}).get("sub") if claims else None

        # 3. Cookie handling for anonymous traffic.
        settings = get_feedback_settings()
        secret = settings.secret_feedback_cookie.encode("utf-8")
        cookie_value = request.cookies.get(COOKIE_NAME)
        if not (cookie_value and validate_cookie_value(cookie_value, secret)):
            cookie_value = issue_cookie_value(secret) if secret else None
            if cookie_value:
                response.set_cookie(
                    key=COOKIE_NAME,
                    value=cookie_value,
                    max_age=COOKIE_MAX_AGE_SECONDS,
                    httponly=True,
                    secure=True,
                    samesite="lax",
                )

        # 4. Rate-limit gate.
        client_ip = request.client.host if request.client else None
        enforce_rate_limit_or_429(
            limiter=get_feedback_rate_limiter(),
            user_id=user_id,
            cookie_value=cookie_value,
            client_ip=client_ip,
        )

        # 5. Validate the model (Pydantic also catches the form-level checks above).
        try:
            req_model = FeedbackSubmitRequest(
                intent=intent, subject=subject, description=description,
                anon_name=anon_name, follow_up_email=follow_up_email,
                anon_email=anon_email,
            )
        except PydanticValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        # 6. Image validation + EXIF strip.
        processed: list[tuple[str, bytes]] = []
        if len(images) > MAX_IMAGES:
            raise HTTPException(status_code=400, detail=f"Maximum {MAX_IMAGES} images.")
        for upload in images:
            blob = await upload.read()
            if len(blob) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413,
                                    detail="Image too large (max 5 MB each).")
            try:
                validated = sniff_and_validate_image(
                    blob, filename=upload.filename or "img.jpg")
                rewritten = process_image(blob, source_ext=validated.normalized_extension)
            except (ValidationError, ImageProcessingError) as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            processed.append((rewritten.filename, rewritten.body))

        # 7. Orchestrate.
        service = FeedbackService(slack_client=slack_client)
        try:
            feedback_id = await service.submit(
                request=req_model, identity=identity, processed_images=processed,
            )
        except SlackPostError as exc:
            logger.warning("slack delivery failed", extra={"err": str(exc)})
            raise HTTPException(
                status_code=502,
                detail="Feedback delivery failed. Please try again.",
            ) from exc

        return FeedbackSubmitResponse(feedback_id=feedback_id, status="accepted")

    return router
