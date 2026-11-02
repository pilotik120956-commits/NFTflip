"""Portals (portal-market.com) adapter. Public search needs no auth."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from adapters.base import BaseAdapter, MarketError, MarketRateLimited, to_float, to_int
from config import Settings
from models import Listing
from utils.normalize import collection_key, strip_rarity

log = logging.getLogger(__name__)

SORT_PRICE_ASC = "price asc"


class PortalsAdapter(BaseAdapter):
    name = "portals"
    display_name = "Portals"
    min_interval_sec = 0.7  # the API advertises 2 req/s; stay below it

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.base = settings.portals_api_url
        self.origin = settings.portals_webapp_url
        self._collections: list[dict[str, Any]] = []
        self._index: dict[str, dict[str, Any]] = {}
        self._collections_at = 0.0

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": self.origin,
            "Referer": self.origin + "/",
            "User-Agent": self.user_agent(),
        }

    async def _load_collections(self, force: bool = False) -> None:
        if not force and self._collections and time.monotonic() - self._collections_at < 600:
            return
        await self._wait_slot()
        response = await self.http.request(
            "GET", f"{self.base}/collections", params={"limit": "500"}, headers=self._headers()
        )
        if response.status == 429:
            raise MarketRateLimited("Portals: collections rate limited", 2.0)
        if response.status >= 400:
            raise MarketError(response.status, f"Portals /collections: {response.text[:200]}")
        data = response.json() or {}
        raw = data.get("collections") if isinstance(data, dict) else data
        collections = [c for c in (raw or []) if isinstance(c, dict)]
        index: dict[str, dict[str, Any]] = {}
        for item in collections:
            for value in (item.get("name"), item.get("short_name")):
                key = collection_key(value) if value else ""
                if key:
                    index[key] = item
        self._collections = collections
        self._index = index
        self._collections_at = time.monotonic()

    async def resolve(self, collection: str) -> dict[str, Any] | None:
        await self._load_collections()
        return self._index.get(collection_key(collection))

    async def has_collection(self, collection: str) -> bool:
        try:
            return await self.resolve(collection) is not None
        except Exception:
            return False

    async def collections(self) -> list[str]:
        await self._load_collections()
        names = [str(c.get("name")) for c in self._collections if c.get("name")]
        return sorted(dict.fromkeys(names), key=str.casefold)

    async def search(
        self,
        collection: str,
        model: str | None = None,
        limit: int = 30,
        *,
        pages: int = 1,
    ) -> list[Listing]:
        info = await self.resolve(collection)
        if info is None:
            # The collection may exist only on another marketplace; that is not a health failure.
            log.info("Portals: collection %r not found, skipping", collection)
            return []

        per_page = max(1, min(limit, 50))
        out: list[Listing] = []
        seen: set[str] = set()
        page = 0

        while page < max(1, pages):
            params: list[tuple[str, str]] = [
                ("offset", str(page * per_page)),
                ("limit", str(per_page)),
                ("sort_by", SORT_PRICE_ASC),
                ("collection_ids", str(info.get("id"))),
            ]
            if model:
                params.append(("filter_by_models", strip_rarity(model)))
            params += [
                ("status", "listed"),
                ("exclude_bundled", "true"),
                ("premarket_status", "all"),
            ]

            for attempt in range(2):
                await self._wait_slot()
                response = await self.http.request(
                    "GET", f"{self.base}/nfts/search", params=params, headers=self._headers()
                )
                if response.status == 429 and attempt == 0:
                    await asyncio.sleep(2.0)
                    continue
                break

            if response.status == 429:
                raise MarketRateLimited("Portals: search rate limited", 2.0)
            if response.status in (401, 403):
                raise MarketError(response.status, f"Portals blocked the request: {response.text[:160]}")
            if response.status >= 400:
                raise MarketError(response.status, f"Portals /nfts/search: {response.text[:200]}")

            data = response.json() or {}
            results = data.get("results") if isinstance(data, dict) else []
            results = results or []
            fresh = 0
            for item in results:
                parsed = self._parse_item(item, info)
                if parsed is not None and parsed.id not in seen:
                    seen.add(parsed.id)
                    out.append(parsed)
                    fresh += 1

            # A short page means the order book ended; an all-duplicates page
            # means the API ignored offset and would repeat itself forever.
            if len(results) < per_page or fresh == 0:
                break
            page += 1

        return out

    def _parse_item(self, item: dict[str, Any], info: dict[str, Any]) -> Listing | None:
        try:
            attrs: dict[str, str] = {}
            for attr in item.get("attributes") or []:
                if isinstance(attr, dict) and attr.get("type"):
                    attrs[str(attr["type"])] = str(attr.get("value") or "")
            price = to_float(item.get("price"))
            if price <= 0:
                return None
            number = to_int(item.get("external_collection_number"))
            collection = str(item.get("name") or info.get("name") or "")
            tg_id = str(item.get("tg_id") or "").strip()
            url = f"https://t.me/nft/{tg_id}" if tg_id else None
            return Listing(
                market=self.name,
                id=str(item.get("id") or tg_id),
                collection=collection,
                model=strip_rarity(attrs.get("model")) or None,
                backdrop=strip_rarity(attrs.get("backdrop")) or None,
                symbol=strip_rarity(attrs.get("symbol")) or None,
                number=number,
                price_ton=price,
                url=url,
                listed_at=item.get("listed_at"),
                raw=item,
            )
        except (TypeError, ValueError, KeyError) as exc:
            log.debug("Portals: skipping malformed item: %s", exc)
            return None
