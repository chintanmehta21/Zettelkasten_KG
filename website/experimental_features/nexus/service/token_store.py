from __future__ import annotations

import inspect
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken

from website.core.supabase_kg import get_supabase_client
from website.experimental_features.nexus.source_ingest.common.models import (
    NexusProvider,
    ProviderTokenSet,
    StoredProviderAccount,
)

TOKEN_ENCRYPTION_KEY_ENV = "NEXUS_TOKEN_ENCRYPTION_KEY"
_ACCOUNT_TABLE = "nexus_provider_accounts"
logger = logging.getLogger("website.experimental_features.nexus.token_store")

TokenRefreshCallback = Callable[
    [StoredProviderAccount],
    ProviderTokenSet | Awaitable[ProviderTokenSet],
]


class ProviderTokenStore:
    def __init__(self, *, client: Any | None = None, encryption_key: str | None = None) -> None:
        self._client = client or get_supabase_client()
        self._fernet = Fernet(_load_encryption_key(encryption_key))

    def upsert_account(self, account: StoredProviderAccount) -> StoredProviderAccount:
        if not account.access_token:
            raise ValueError("Provider accounts must include a non-empty access token.")
        payload = {
            "user_id": str(account.user_id),
            "provider": account.provider.value,
            "account_id": account.account_id,
            "account_username": account.account_username,
            "access_token_encrypted": self._encrypt(account.access_token),
            "refresh_token_encrypted": self._encrypt(account.refresh_token)
            if account.refresh_token
            else None,
            "token_type": account.token_type,
            "scopes": account.scopes,
            "expires_at": _isoformat(account.expires_at),
            "metadata": account.metadata,
            "last_refreshed_at": _isoformat(account.last_refreshed_at),
            "last_imported_at": _isoformat(account.last_imported_at),
        }
        response = (
            self._client.table(_ACCOUNT_TABLE)
            .upsert(payload, on_conflict="user_id,provider")
            .execute()
        )
        if not response.data:
            stored = self.get_account(account.user_id, account.provider)
            if stored is None:
                raise RuntimeError("Failed to persist Nexus provider account.")
            return stored
        return self._row_to_account(response.data[0])

    def get_account(
        self,
        user_id: UUID,
        provider: NexusProvider,
    ) -> StoredProviderAccount | None:
        response = (
            self._client.table(_ACCOUNT_TABLE)
            .select("*")
            .eq("user_id", str(user_id))
            .eq("provider", provider.value)
            .limit(1)
            .execute()
        )
        if not response.data:
            return None
        return self._row_to_account(response.data[0])

    def list_accounts(self, user_id: UUID) -> list[StoredProviderAccount]:
        response = (
            self._client.table(_ACCOUNT_TABLE)
            .select("*")
            .eq("user_id", str(user_id))
            .execute()
        )
        rows = response.data or []
        accounts: list[StoredProviderAccount] = []
        for row in rows:
            try:
                accounts.append(self._row_to_account(row))
            except Exception as exc:
                logger.warning("Skipping provider account row that could not be decoded: %s", exc)
        return accounts

    def delete_account(self, user_id: UUID, provider: NexusProvider) -> bool:
        response = (
            self._client.table(_ACCOUNT_TABLE)
            .delete()
            .eq("user_id", str(user_id))
            .eq("provider", provider.value)
            .execute()
        )
        return bool(response.data)

    async def refresh_and_persist(
        self,
        user_id: UUID,
        provider: NexusProvider,
        refresh_callback: TokenRefreshCallback,
    ) -> StoredProviderAccount:
        account = self.get_account(user_id, provider)
        if account is None:
            raise LookupError(f"No Nexus provider account found for provider {provider.value}.")
        if not account.refresh_token:
            raise RuntimeError(
                f"Provider account for {provider.value} does not have a refresh token."
            )

        refreshed_tokens = refresh_callback(account)
        if inspect.isawaitable(refreshed_tokens):
            refreshed_tokens = await refreshed_tokens

        updated_account = account.model_copy(
            update={
                "access_token": refreshed_tokens.access_token,
                "refresh_token": refreshed_tokens.refresh_token or account.refresh_token,
                "token_type": refreshed_tokens.token_type or account.token_type,
                "scopes": refreshed_tokens.scopes or account.scopes,
                "expires_at": refreshed_tokens.expires_at or account.expires_at,
                "last_refreshed_at": _utcnow(),
                "metadata": account.metadata,
            }
        )
        return self.upsert_account(updated_account)

    def mark_imported(
        self,
        user_id: UUID,
        provider: NexusProvider,
        *,
        imported_at: datetime | None = None,
    ) -> StoredProviderAccount:
        account = self.get_account(user_id, provider)
        if account is None:
            raise LookupError(f"No Nexus provider account found for provider {provider.value}.")

        updated_account = account.model_copy(
            update={"last_imported_at": imported_at or _utcnow()}
        )
        return self.upsert_account(updated_account)

    def _row_to_account(self, row: dict[str, Any]) -> StoredProviderAccount:
        try:
            access_token = self._decrypt(row.get("access_token_encrypted"))
            refresh_token = self._decrypt(row.get("refresh_token_encrypted"))
        except InvalidToken as exc:
            raise RuntimeError(
                "Failed to decrypt stored Nexus provider tokens. "
                f"Verify {TOKEN_ENCRYPTION_KEY_ENV}."
            ) from exc

        # Backwards-compatible fallback for legacy rows that stored plaintext
        # while migration to encrypted storage completes.
        if not access_token:
            fallback_access_token = row.get("access_token")
            access_token = str(fallback_access_token).strip() if fallback_access_token else None
        if not refresh_token:
            fallback_refresh_token = row.get("refresh_token")
            refresh_token = str(fallback_refresh_token).strip() if fallback_refresh_token else None

        if not access_token:
            raise RuntimeError("Stored Nexus provider account does not include a usable access token.")

        return StoredProviderAccount(
            id=row.get("id"),
            user_id=row["user_id"],
            provider=NexusProvider(row["provider"]),
            account_id=row.get("account_id"),
            account_username=row.get("account_username"),
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=row.get("token_type") or "Bearer",
            scopes=row.get("scopes") or [],
            expires_at=row.get("expires_at"),
            metadata=row.get("metadata") or {},
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            last_refreshed_at=row.get("last_refreshed_at"),
            last_imported_at=row.get("last_imported_at"),
        )

    def _encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")

    def _decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        return self._fernet.decrypt(value.encode("utf-8")).decode("utf-8")


def _load_encryption_key(explicit_key: str | None) -> bytes:
    raw_key = (explicit_key or os.environ.get(TOKEN_ENCRYPTION_KEY_ENV) or "").strip()
    if not raw_key:
        raise RuntimeError(
            f"Missing required environment variable: {TOKEN_ENCRYPTION_KEY_ENV}"
        )
    try:
        Fernet(raw_key.encode("utf-8"))
    except ValueError as exc:
        raise RuntimeError(
            f"{TOKEN_ENCRYPTION_KEY_ENV} must be a valid Fernet key."
        ) from exc
    return raw_key.encode("utf-8")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


__all__ = ["ProviderTokenStore", "TOKEN_ENCRYPTION_KEY_ENV", "TokenRefreshCallback"]
