"""Token cache for evohome_enhanced, backed by Home Assistant's Store."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, NotRequired, TypedDict, override

from evohomeasync.auth import (
    SZ_SESSION_ID,
    SZ_SESSION_ID_EXPIRES,
    AbstractSessionManager,
)
from evohomeasync2.auth import AbstractTokenManager
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import STORAGE_VER


class _SessionIdEntryT(TypedDict):
    session_id: str
    session_id_expires: NotRequired[str]


class _TokenStoreT(TypedDict):
    username: str
    refresh_token: str
    access_token: str
    access_token_expires: str
    session_id: NotRequired[str]
    session_id_expires: NotRequired[str]


class TokenManager(AbstractTokenManager, AbstractSessionManager):
    """Persist v1 session ids and v2 access tokens in a per-entry Store."""

    def __init__(
        self,
        hass: HomeAssistant,
        *args: Any,
        storage_key: str,
        **kwargs: Any,
    ) -> None:
        """Initialise the token manager with a dedicated storage key."""
        super().__init__(*args, **kwargs)
        self._store: Store[_TokenStoreT] = Store(hass, STORAGE_VER, storage_key)
        self._store_initialized = False

    @override
    async def get_access_token(self) -> str:
        if not self._store_initialized:
            await self._load_cache_from_store()
        return await super().get_access_token()

    @override
    async def get_session_id(self) -> str:
        if not self._store_initialized:
            await self._load_cache_from_store()
        return await super().get_session_id()

    async def _load_cache_from_store(self) -> None:
        cache = await self._store.async_load() or {}
        self._store_initialized = True

        if not cache or cache["username"] != self._client_id:
            return

        if SZ_SESSION_ID in cache:
            self._import_session_id(cache)
        self._import_access_token(cache)

    @override
    def _import_session_id(self, session: _SessionIdEntryT) -> None:
        self._session_id = session[SZ_SESSION_ID]
        expires = session.get(SZ_SESSION_ID_EXPIRES)
        self._session_id_expires = (
            dt_util.utcnow() + timedelta(minutes=15)
            if expires is None
            else datetime.fromisoformat(expires)
        )

    @override
    async def save_access_token(self) -> None:
        await self.save_cache_to_store()

    @override
    async def save_session_id(self) -> None:
        await self.save_cache_to_store()

    async def save_cache_to_store(self) -> None:
        cache = {"username": self._client_id} | self._export_access_token()
        if self._session_id:
            cache |= self._export_session_id()
        await self._store.async_save(cache)
