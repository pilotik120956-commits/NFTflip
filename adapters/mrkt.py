"""MRKT (api.tgmrkt.io) adapter.

Reading /gifts/saling needs auth. We support three ways, in order:
  1. MRKT_TOKEN       — a ready token copied from the web app / a community client;
  2. MRKT_INIT_DATA   — Telegram Mini App initData, exchanged for a token;
  3. TG_API_ID/HASH   — a Telethon session that fetches fresh initData automatically.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from adapters.base import BaseAdapter, MarketAuthError, MarketError, MarketRateLimited, to_float, to_int
from config import Settings
from models import Listing
from utils.normalize import collection_key, strip_rarity

log = logging.getLogger(__name__)

NANO = 1_000_000_000
AUTH_SENSITIVE_PATHS = {"/gifts/saling", "/gifts/collections", "/balance"}

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://cdn.tgmrkt.io",
    "Referer": "https://cdn.tgmrkt.io/",
    "Accept-Language": "en-US,en;q=0.9",
}


class MrktAdapter(BaseAdapter):
    name = "mrkt"
    display_name = "MRKT"
    min_interval_sec = 0.25

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.base = settings.mrkt_api_base
        self._token: str | None = settings.mrkt_token or None
        self._init_provider: Any = None
        self._auth_lock = asyncio.Lock()
        self._last_reauth = 0.0
        self._collections: list[dict[str, Any]] = []
        self._collections_at = 0.0

    @property
    def enabled(self) -> bool:
        return self.settings.mrkt_configured

    def _headers(self) -> dict[str, str]:
        headers = dict(DEFAULT_HEADERS)
        headers["User-Agent"] = self.user_agent()
        if self._token:
            # The MRKT web app sends the raw token (no "Bearer") and mirrors it into a cookie.
            headers["Authorization"] = self._token
            headers["Cookie"] = f"access_token={self._token}"
        return headers

    async def _auth_with_init_data(self, init_data: str) -> None:
        response = await self.http.request(
            "POST", f"{self.base}/auth", json={"data": init_data, "appId": None}, headers=dict(DEFAULT_HEADERS)
        )
        if response.status != 200:
            raise MarketAuthError(response.status, f"MRKT /auth failed: {response.text[:200]}")
        data = response.json() or {}
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise MarketAuthError(response.status, "MRKT /auth returned no token")
        self._token = str(token)
        log.info("MRKT token refreshed")

    async def _ensure_token(self, force: bool = False) -> None:
        async with self._auth_lock:
            if self._token and not force:
                return
            if self.settings.mrkt_init_data:
                await self._auth_with_init_data(self.settings.mrkt_init_data)
                return
            if self.settings.tg_api_id and self.settings.tg_api_hash:
                from utils.tg_auth import InitDataProvider

                if self._init_provider is None:
                    self._init_provider = InitDataProvider(self.settings)
                init_data = await self._init_provider.get(force=force)
                await self._auth_with_init_data(init_data)
                return
            if self._token:
                # Static token and a forced refresh: leave it as is, the caller will report the error.
                return
            raise MarketAuthError(
                0,
                "MRKT не налаштований: додайте MRKT_TOKEN, MRKT_INIT_DATA або TG_API_ID/TG_API_HASH у .env",
            )

    async def _request(self, method: str, path: str, *, json: Any = None, retry_auth: bool = True) -> Any:
        await self._ensure_token()
        await self._wait_slot()
        response = await self.http.request(method, f"{self.base}{path}", json=json, headers=self._headers())

        status = response.status
        needs_auth = status in (401, 403) or (status == 404 and path in AUTH_SENSITIVE_PATHS)
        if needs_auth and retry_auth:
            # MRKT answers 404 (not 401) for an invalid token on known endpoints.
            if time.monotonic() - self._last_reauth > 30:
                self._last_reauth = time.monotonic()
                await self._ensure_token(force=True)
                return await self._request(method, path, json=json, retry_auth=False)
        if status == 429:
            retry_after = response.headers.get("retry-after")
            try:
                delay = float(retry_after) if retry_after else 5.0
            except ValueError:
                delay = 5.0
            raise MarketRateLimited("MRKT: rate limited", delay)
        if status in (401, 403):
            raise MarketAuthError(status, f"MRKT auth: {response.text[:200]}")
        if status >= 400:
            raise MarketError(status, f"MRKT {method} {path}: {response.text[:240]}")
        return response.json()

    async def _load_collections(self, force: bool = False) -> None:
        if not force and self._collections and time.monotonic() - self._collections_at < 600:
            return
        try:
            data = await self._request("GET", "/gifts/collections")
        except MarketError as exc:
            log.debug("MRKT collections unavailable: %s", exc)
            return
        raw = data.get("gifts") if isinstance(data, dict) else data
        if isinstance(data, dict) and not raw:
            raw = data.get("collections") or data.get("data")
        items = [c for c in (raw or []) if isinstance(c, dict)]
        self._collections = items
        self._collections_at = time.monotonic()

    async def resolve_name(self, collection: str) -> str:
        await self._load_collections()
        key = collection_key(collection)
        for item in self._collections:
            for value in (item.get("name"), item.get("title")):
                if value and collection_key(str(value)) == key:
                    return str(item.get("name") or item.get("title") or collection)
        return collection

    async def collections(self) -> list[str]:
        await self._load_collections()
        names = [str(c.get("name") or c.get("title")) for c in self._collections if c.get("name") or c.get("title")]
        return sorted(dict.fromkeys(names), key=str.casefold)

    async def search(
        self,
        collection: str,
        model: str | None = None,
        limit: int = 30,
        *,
        pages: int = 1,
    ) -> list[Listing]:
        resolved = await self.resolve_name(collection)
        per_page = max(1, min(int(limit), 50))
        body = {
            "count": per_page,
            "cursor": "",
            "collectionNames": [resolved],
            "modelNames": [strip_rarity(model)] if model else [],
            "backdropNames": [],
            "symbolNames": [],
            "minPrice": None,
            "maxPrice": None,
            "number": None,
            "isPremarket": None,
            "isNew": None,
            "luckyBuy": None,
            "luckybuyCashback": None,
            "giftType": None,
            "craftable": None,
            "isCrafted": None,
            "tgCanBeCraftedFrom": None,
            "removeSelfSales": True,
            "isTransferable": None,
            "availableForStaking": None,
            "forGame": None,
            "ordering": "Price",
            "lowToHigh": True,
            "query": None,
        }

        out: list[Listing] = []
        seen: set[str] = set()
        cursor: Any = ""
        page = 0

        while page < max(1, pages):
            body["cursor"] = cursor
            data = await self._request("POST", "/gifts/saling", json=body)
            if isinstance(data, dict):
                gifts = data.get("gifts") or data.get("data") or []
                cursor = (
                    data.get("cursor")
                    or data.get("nextCursor")
                    or data.get("next_cursor")
                    or ""
                )
            else:
                gifts = data or []
                cursor = ""
            gifts = gifts or []

            fresh = 0
            for item in gifts:
                parsed = self._parse_item(item)
                if parsed is not None and parsed.id not in seen:
                    seen.add(parsed.id)
                    out.append(parsed)
                    fresh += 1

            if len(gifts) < per_page or not cursor or fresh == 0:
                break
            page += 1

        return out

    def _parse_item(self, item: dict[str, Any]) -> Listing | None:
        try:
            gift_id = item.get("id")
            if not gift_id:
                return None
            price_nano = item.get("salePrice")
            price = to_float(price_nano) / NANO if price_nano not in (None, "") else 0.0
            if price <= 0:
                return None
            number = to_int(item.get("number"))
            collection = str(item.get("collectionName") or item.get("collectionTitle") or item.get("title") or "")
            return Listing(
                market=self.name,
                id=str(gift_id),
                collection=collection,
                model=strip_rarity(item.get("modelName")) or None,
                backdrop=strip_rarity(item.get("backdropName")) or None,
                symbol=strip_rarity(item.get("symbolName")) or None,
                number=number,
                price_ton=price,
                url=None,
                listed_at=item.get("listedAt") or item.get("saleDate") or item.get("updatedAt"),
                raw=item,
            )
        except (TypeError, ValueError, KeyError) as exc:
            log.debug("MRKT: skipping malformed item: %s", exc)
            return None
