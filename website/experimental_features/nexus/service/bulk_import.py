"""Bulk import orchestration for Nexus provider ingestion."""

from __future__ import annotations

import importlib
import inspect
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from telegram_bot.config.settings import get_settings
from telegram_bot.pipeline.summarizer import GeminiSummarizer, build_tag_list
from telegram_bot.sources import get_extractor
from telegram_bot.sources.registry import detect_source_type
from telegram_bot.utils.url_utils import normalize_url, resolve_redirects
from website.core.supabase_kg import get_supabase_client, is_supabase_configured
from website.experimental_features.nexus.service.persist import (
    PersistenceOutcome,
    get_supabase_scope,
    persist_summarized_result,
)
from website.experimental_features.nexus.service.token_store import ProviderTokenStore
from website.experimental_features.nexus.source_ingest.common.models import (
    ImportRequest,
    ImportRun,
    NexusProvider,
    ProviderArtifact,
    StoredProviderAccount,
)

logger = logging.getLogger("website.experimental_features.nexus.bulk_import")


@dataclass(slots=True)
class BulkImportResult:
    provider: NexusProvider
    run: ImportRun | None
    total_artifacts: int
    imported_count: int
    skipped_count: int
    failed_count: int
    results: list[dict[str, Any]]
    credentials_forgotten: bool = False


def get_provider_account(user_id: str, provider: NexusProvider) -> StoredProviderAccount | None:
    """Return a stored provider account for a KG user."""

    if not is_supabase_configured():
        return None

    try:
        user_uuid = UUID(str(user_id))
    except (TypeError, ValueError):
        logger.warning("Invalid KG user id passed to get_provider_account: %s", user_id)
        return None

    return ProviderTokenStore().get_account(user_uuid, provider)


def list_provider_accounts(user_id: str) -> dict[NexusProvider, StoredProviderAccount]:
    """Return all stored provider accounts for a KG user."""

    if not is_supabase_configured():
        return {}

    try:
        user_uuid = UUID(str(user_id))
    except (TypeError, ValueError):
        logger.warning("Invalid KG user id passed to list_provider_accounts: %s", user_id)
        return {}

    decrypted_accounts = ProviderTokenStore().list_accounts(user_uuid)
    accounts: dict[NexusProvider, StoredProviderAccount] = {}
    for account in decrypted_accounts:
        accounts[account.provider] = account
    return accounts


def upsert_provider_account(account: StoredProviderAccount) -> StoredProviderAccount:
    """Insert or update a Nexus provider account."""
    return ProviderTokenStore().upsert_account(account)


def disconnect_provider_account(user_id: str, provider: NexusProvider) -> bool:
    """Delete a stored provider account."""

    if not is_supabase_configured():
        return False

    try:
        user_uuid = UUID(str(user_id))
    except (TypeError, ValueError):
        logger.warning("Invalid KG user id passed to disconnect_provider_account: %s", user_id)
        return False

    return ProviderTokenStore().delete_account(user_uuid, provider)


def list_import_runs(user_id: str, limit: int = 20) -> list[ImportRun]:
    """Return recent Nexus ingest runs for a KG user."""

    if not is_supabase_configured():
        return []

    client = get_supabase_client()
    response = (
        client.table("nexus_ingest_runs")
        .select("*")
        .eq("user_id", user_id)
        .order("started_at", desc=True)
        .limit(max(1, min(limit, 100)))
        .execute()
    )
    runs: list[ImportRun] = []
    for row in response.data or []:
        try:
            runs.append(ImportRun(**row))
        except Exception as exc:
            logger.warning("Skipping invalid ingest run row: %s", exc)
    return runs


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _load_provider_module(provider: NexusProvider, module_name: str):
    module_path = f"website.experimental_features.nexus.source_ingest.{provider.value}.{module_name}"
    return importlib.import_module(module_path)


def provider_handler_available(provider: NexusProvider, handler_type: str) -> bool:
    try:
        module = _load_provider_module(provider, handler_type)
    except Exception:
        return False

    return _resolve_callable(
        module,
        _oauth_handler_names() if handler_type == "oauth" else ("ingest_artifacts", "run_import", "import_artifacts"),
    ) is not None


def _oauth_handler_names() -> tuple[str, ...]:
    return (
        "start_oauth",
        "begin_oauth",
        "start_connect",
        "build_authorization_url",
        "handle_callback",
        "oauth_callback",
        "complete_oauth",
        "exchange_code_for_tokens",
    )


def _resolve_callable(module: Any, names: tuple[str, ...]) -> Any | None:
    for name in names:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


def _call_with_supported_kwargs(func: Any, **candidate_kwargs: Any) -> Any:
    signature = inspect.signature(func)
    accepted_kwargs = {}
    has_var_keyword = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )

    for name, value in candidate_kwargs.items():
        if value is None:
            continue
        if has_var_keyword or name in signature.parameters:
            accepted_kwargs[name] = value

    return func(**accepted_kwargs)


def _normalize_artifacts(raw_result: Any, provider: NexusProvider) -> tuple[list[ProviderArtifact], dict[str, Any]]:
    metadata: dict[str, Any] = {}
    raw_artifacts = raw_result

    if hasattr(raw_result, "model_dump"):
        raw_result = raw_result.model_dump()

    if isinstance(raw_result, dict):
        metadata = {
            key: value
            for key, value in raw_result.items()
            if key != "artifacts"
        }
        raw_artifacts = raw_result.get("artifacts", [])

    if raw_artifacts is None:
        return [], metadata

    artifacts: list[ProviderArtifact] = []
    for item in raw_artifacts:
        try:
            if isinstance(item, ProviderArtifact):
                artifact = item
            elif hasattr(item, "model_dump"):
                artifact = ProviderArtifact.model_validate(item.model_dump())
            else:
                payload = dict(item)
                payload.setdefault("provider", provider.value)
                artifact = ProviderArtifact.model_validate(payload)
            artifacts.append(artifact)
        except Exception as exc:
            logger.warning("Skipping invalid %s artifact: %s", provider.value, exc)

    return artifacts, metadata


async def summarize_artifact_url(url: str) -> dict[str, Any]:
    """Summarize an artifact URL using the current web pipeline steps."""

    settings = get_settings()

    resolved = await resolve_redirects(url)
    normalized = normalize_url(resolved)
    source_type = detect_source_type(normalized)
    extractor = get_extractor(source_type, settings)
    extracted = await extractor.extract(normalized)

    # Use flash-lite for high-volume bulk imports. GeminiSummarizer now
    # honors explicit model overrides while keeping default routing elsewhere.
    summarizer = GeminiSummarizer(model_name="gemini-2.5-flash-lite")
    summarized = await summarizer.summarize(extracted)
    tags = build_tag_list(source_type, summarized.tags)
    if summarized.is_raw_fallback:
        tags = [tag for tag in tags if not tag.startswith("status/")]
        tags.append("status/Raw")

    return {
        "title": extracted.title,
        "summary": summarized.summary,
        "brief_summary": summarized.brief_summary,
        "tags": tags,
        "source_type": source_type.value,
        "source_url": normalized,
        "one_line_summary": summarized.one_line_summary,
        "is_raw_fallback": summarized.is_raw_fallback,
        "tokens_used": summarized.tokens_used,
        "latency_ms": summarized.latency_ms,
        "metadata": extracted.metadata,
    }


def _create_run(
    user_id: str,
    provider: NexusProvider,
    *,
    provider_account_id: str | None = None,
) -> ImportRun:
    client = get_supabase_client()
    payload = {
        "user_id": user_id,
        "provider": provider.value,
        "provider_account_id": provider_account_id,
        "status": "running",
        "started_at": _utcnow().isoformat(),
        "metadata": {},
    }
    response = client.table("nexus_ingest_runs").insert(payload).execute()
    if not response.data:
        raise RuntimeError("Failed to create ingest run")
    return ImportRun(**response.data[0])


def _update_run(run_id: str, **fields: Any) -> ImportRun:
    client = get_supabase_client()
    response = (
        client.table("nexus_ingest_runs")
        .update(fields)
        .eq("id", run_id)
        .execute()
    )
    if not response.data:
        raise RuntimeError("Failed to update ingest run")
    return ImportRun(**response.data[0])


def _artifact_exists(user_id: str, provider: NexusProvider, external_id: str) -> bool:
    client = get_supabase_client()
    response = (
        client.table("nexus_ingested_artifacts")
        .select("id")
        .eq("user_id", user_id)
        .eq("provider", provider.value)
        .eq("external_id", external_id)
        .limit(1)
        .execute()
    )
    return bool(response.data)


def _record_artifact(
    *,
    user_id: str,
    provider: NexusProvider,
    provider_account_id: str | None,
    artifact: ProviderArtifact,
    ingest_run_id: str,
    status: str,
    persistence: PersistenceOutcome | None = None,
    error_message: str | None = None,
) -> None:
    try:
        metadata = dict(artifact.metadata or {})
        node_id = (
            (persistence.supabase_node_id or persistence.file_node_id)
            if persistence is not None
            else None
        )

        payload = {
            "user_id": user_id,
            "provider": provider.value,
            "provider_account_id": provider_account_id,
            "run_id": ingest_run_id,
            "ingest_run_id": ingest_run_id,
            "status": status,
            "error_message": error_message,
            "node_id": node_id,
            "external_id": artifact.external_id,
            "url": artifact.url,
            "title": artifact.title or "",
            "description": artifact.description or "",
            "source_type": artifact.source_type,
            "metadata": metadata,
            "imported_at": _utcnow().isoformat(),
        }
        client = get_supabase_client()
        (
            client.table("nexus_ingested_artifacts")
            .upsert(payload, on_conflict="user_id,provider,external_id")
            .execute()
        )
    except Exception as exc:
        logger.warning(
            "Failed to record Nexus artifact %s for %s: %s",
            artifact.external_id,
            provider.value,
            exc,
        )


def _touch_account_imported_at(account: StoredProviderAccount) -> None:
    try:
        ProviderTokenStore().mark_imported(account.user_id, account.provider)
    except Exception as exc:
        logger.warning("Failed to update last_imported_at for %s: %s", account.provider.value, exc)


def _should_forget_credentials(account: StoredProviderAccount, request: ImportRequest) -> bool:
    request_forget = not bool(request.remember_connection)
    metadata_value = (account.metadata or {}).get("remember_connection")
    if metadata_value is None:
        return request_forget
    if isinstance(metadata_value, bool):
        return not metadata_value
    if isinstance(metadata_value, str):
        return metadata_value.strip().lower() in {"0", "false", "no", "off"}
    return request_forget


async def _invoke_ingest_handler(
    provider: NexusProvider,
    account: StoredProviderAccount,
    request: ImportRequest,
) -> tuple[list[ProviderArtifact], dict[str, Any]]:
    module = _load_provider_module(provider, "ingest")
    handler = _resolve_callable(module, ("ingest_artifacts", "run_import", "import_artifacts"))
    if handler is None:
        raise RuntimeError(f"No ingest handler available for provider '{provider.value}'")

    result = _call_with_supported_kwargs(
        handler,
        account=account,
        provider_account=account,
        stored_account=account,
        provider=provider,
        limit=request.limit,
        force=request.force,
    )
    if inspect.isawaitable(result):
        result = await result
    return _normalize_artifacts(result, provider)


def _resolve_user_scope(auth_user_sub: str) -> str:
    scope = get_supabase_scope(auth_user_sub)
    if not scope:
        raise RuntimeError("Supabase is required for Nexus imports")
    _repo, kg_user_id = scope
    return kg_user_id


async def run_provider_import(
    *,
    auth_user_sub: str,
    provider: NexusProvider,
    request: ImportRequest,
) -> BulkImportResult:
    """Import artifacts from one provider, summarize them, and persist them."""

    kg_user_id = _resolve_user_scope(auth_user_sub)
    account = get_provider_account(kg_user_id, provider)
    if account is None:
        raise ValueError(f"No connected account for provider '{provider.value}'")

    provider_account_id = str(account.id) if account.id else None
    run = _create_run(
        kg_user_id,
        provider,
        provider_account_id=provider_account_id,
    )
    forget_after_import = _should_forget_credentials(account, request)
    credentials_forgotten = False

    try:
        artifacts, run_metadata = await _invoke_ingest_handler(provider, account, request)
        processed = await _process_artifacts(
            artifacts=artifacts,
            request=request,
            provider=provider,
            provider_account_id=provider_account_id,
            kg_user_id=kg_user_id,
            auth_user_sub=auth_user_sub,
            ingest_run_id=str(run.id),
        )
        run = _finalize_run(
            run_id=str(run.id),
            total_artifacts=len(artifacts),
            imported_count=processed["imported_count"],
            skipped_count=processed["skipped_count"],
            failed_count=processed["failed_count"],
            metadata=run_metadata,
        )
        _touch_account_imported_at(account)
        credentials_forgotten = _forget_credentials_if_requested(
            kg_user_id=kg_user_id,
            provider=provider,
            forget_after_import=forget_after_import,
        )

        return BulkImportResult(
            provider=provider,
            run=run,
            total_artifacts=len(artifacts),
            imported_count=processed["imported_count"],
            skipped_count=processed["skipped_count"],
            failed_count=processed["failed_count"],
            results=processed["results"],
            credentials_forgotten=credentials_forgotten,
        )
    except Exception as exc:
        run = _update_run(
            str(run.id),
            status="failed",
            total_artifacts=0,
            imported_count=0,
            skipped_count=0,
            failed_count=1,
            completed_at=_utcnow().isoformat(),
            error_message=str(exc),
        )
        if forget_after_import:
            try:
                credentials_forgotten = disconnect_provider_account(kg_user_id, provider)
            except Exception as disconnect_exc:
                logger.warning(
                    "Failed to forget provider credentials for %s after failed import: %s",
                    provider.value,
                    disconnect_exc,
                )
        raise RuntimeError(f"{provider.value} import failed: {exc}") from exc


async def _process_artifacts(
    *,
    artifacts: list[ProviderArtifact],
    request: ImportRequest,
    provider: NexusProvider,
    provider_account_id: str | None,
    kg_user_id: str,
    auth_user_sub: str,
    ingest_run_id: str,
) -> dict[str, Any]:
    imported_count = 0
    skipped_count = 0
    failed_count = 0
    results: list[dict[str, Any]] = []

    for artifact in artifacts:
        artifact_result, status = await _process_single_artifact(
            artifact=artifact,
            request=request,
            provider=provider,
            provider_account_id=provider_account_id,
            kg_user_id=kg_user_id,
            auth_user_sub=auth_user_sub,
            ingest_run_id=ingest_run_id,
        )
        results.append(artifact_result)
        if status == "imported":
            imported_count += 1
        elif status == "skipped":
            skipped_count += 1
        else:
            failed_count += 1

    return {
        "imported_count": imported_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "results": results,
    }


async def _process_single_artifact(
    *,
    artifact: ProviderArtifact,
    request: ImportRequest,
    provider: NexusProvider,
    provider_account_id: str | None,
    kg_user_id: str,
    auth_user_sub: str,
    ingest_run_id: str,
) -> tuple[dict[str, Any], str]:
    artifact_result = {
        "external_id": artifact.external_id,
        "url": artifact.url,
        "title": artifact.title,
        "status": "pending",
    }

    if not artifact.external_id or not artifact.url:
        return _fail_artifact(
            artifact=artifact,
            artifact_result=artifact_result,
            error_message="Artifact is missing required external_id or url",
            provider=provider,
            provider_account_id=provider_account_id,
            kg_user_id=kg_user_id,
            ingest_run_id=ingest_run_id,
        )

    if not request.force and _artifact_exists(kg_user_id, provider, artifact.external_id):
        artifact_result["status"] = "skipped"
        artifact_result["reason"] = "Artifact already imported"
        _record_artifact(
            user_id=kg_user_id,
            provider=provider,
            provider_account_id=provider_account_id,
            artifact=artifact,
            ingest_run_id=ingest_run_id,
            status="skipped",
        )
        return artifact_result, "skipped"

    try:
        summary_result = await summarize_artifact_url(artifact.url)
        persistence = await persist_summarized_result(
            summary_result,
            user_sub=auth_user_sub,
        )
        if persistence.supabase_duplicate and not request.force:
            artifact_result["status"] = "skipped"
            artifact_result["reason"] = "Artifact URL already exists in the knowledge graph"
            status = "skipped"
        else:
            artifact_result["status"] = "imported"
            artifact_result["node_id"] = persistence.supabase_node_id or persistence.file_node_id
            status = "imported"
        _record_artifact(
            user_id=kg_user_id,
            provider=provider,
            provider_account_id=provider_account_id,
            artifact=artifact,
            ingest_run_id=ingest_run_id,
            status=artifact_result["status"],
            persistence=persistence,
        )
        return artifact_result, status
    except Exception as exc:
        return _fail_artifact(
            artifact=artifact,
            artifact_result=artifact_result,
            error_message=str(exc),
            provider=provider,
            provider_account_id=provider_account_id,
            kg_user_id=kg_user_id,
            ingest_run_id=ingest_run_id,
        )


def _fail_artifact(
    *,
    artifact: ProviderArtifact,
    artifact_result: dict[str, Any],
    error_message: str,
    provider: NexusProvider,
    provider_account_id: str | None,
    kg_user_id: str,
    ingest_run_id: str,
) -> tuple[dict[str, Any], str]:
    artifact_result["status"] = "failed"
    artifact_result["error"] = error_message
    _record_artifact(
        user_id=kg_user_id,
        provider=provider,
        provider_account_id=provider_account_id,
        artifact=artifact,
        ingest_run_id=ingest_run_id,
        status="failed",
        error_message=error_message,
    )
    return artifact_result, "failed"


def _finalize_run(
    *,
    run_id: str,
    total_artifacts: int,
    imported_count: int,
    skipped_count: int,
    failed_count: int,
    metadata: dict[str, Any] | None,
) -> ImportRun:
    status = _resolve_run_status(
        imported_count=imported_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )
    return _update_run(
        run_id,
        status=status,
        total_artifacts=total_artifacts,
        imported_count=imported_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        completed_at=_utcnow().isoformat(),
        metadata=dict(metadata or {}),
    )


def _resolve_run_status(
    *,
    imported_count: int,
    skipped_count: int,
    failed_count: int,
) -> str:
    if failed_count and (imported_count or skipped_count):
        return "partial_success"
    if failed_count:
        return "failed"
    return "completed"


def _forget_credentials_if_requested(
    *,
    kg_user_id: str,
    provider: NexusProvider,
    forget_after_import: bool,
) -> bool:
    if not forget_after_import:
        return False
    forgotten = disconnect_provider_account(kg_user_id, provider)
    if not forgotten:
        logger.warning(
            "Testing mode requested forget_connection for %s, but account delete returned false.",
            provider.value,
        )
    return forgotten


async def run_all_imports(
    *,
    auth_user_sub: str,
    request: ImportRequest,
) -> list[BulkImportResult]:
    """Run imports across every connected provider account for the user."""

    kg_scope = get_supabase_scope(auth_user_sub)
    if not kg_scope:
        raise RuntimeError("Supabase is required for Nexus imports")
    _repo, kg_user_id = kg_scope

    accounts = list_provider_accounts(kg_user_id)
    if not accounts:
        return []

    results: list[BulkImportResult] = []
    for provider in NexusProvider:
        if provider not in accounts:
            continue
        try:
            results.append(
                await run_provider_import(
                    auth_user_sub=auth_user_sub,
                    provider=provider,
                    request=request,
                )
            )
        except Exception as exc:
            logger.warning("Nexus import/all failed for %s: %s", provider.value, exc)
            results.append(
                BulkImportResult(
                    provider=provider,
                    run=None,
                    total_artifacts=0,
                    imported_count=0,
                    skipped_count=0,
                    failed_count=1,
                    results=[{"status": "failed", "error": str(exc)}],
                )
            )
    return results
