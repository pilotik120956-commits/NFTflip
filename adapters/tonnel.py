"""Tonnel (market.tonnel.network) adapter. Public pageGifts needs no auth for reads."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from adapters.base import BaseAdapter, MarketError, MarketRateLimited, to_float, to_int
from config import Settings
from models import Listing
from utils.normalize import strip_rarity

log = logging.getLogger(__name__)

SORT_PRICE_ASC = '{"price":1,"gift_id":-1}'


def tonnel_title(text: str) -> str:
    """The Tonnel front-end capitalises every word: 'durov's cap' -> 'Durov's Cap'."""
    text = " ".join((text or "").split())
    return " ".join(word[:1].upper() + word[1:] for word in text.split(" "))


def _attr_filter(value: str) -> Any:
    cleaned = strip_rarity(value)
    if not cleaned:
        return None
    # Tonnel stores the rarity suffix inside the field: "Wizard (1.5%)".
    return {"$regex": f"^{re.escape(tonnel_title(cleaned))} \\("}


class TonnelAdapter(BaseAdapter):
    name = "tonnel"
    display_name = "Tonnel"
    min_interval_sec = 0.35

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.base = settings.tonnel_api_url
        self.origin = settings.tonnel_origin

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": self.origin,
            "Referer": self.origin + "/",
            "User-Agent": self.user_agent(),
        }

    async def search(
        self,
        collection: str,
        model: str | None = None,
        limit: int = 30,
        *,
        pages: int = 1,
    ) -> list[Listing]:
        flt: dict[str, Any] = {
            "price": {"$exists": True},
            "buyer": {"$exists": False},
            "asset": "TON",
            "refunded": {"$ne": True},
            "export_at": {"$exists": True},
            "gift_name": tonnel_title(collection),
        }
        if model:
            model_filter = _attr_filter(model)
            if model_filter:
                flt["model"] = model_filter

        per_page = max(1, min(int(limit), 30))
        out: list[Listing] = []
        seen: set[str] = set()
        page = 1

        while page <= max(1, pages):
            payload = {
                "page": page,
                "limit": per_page,
                "sort": SORT_PRICE_ASC,
                "filter": json.dumps(flt, separators=(",", ":")),
                "ref": 0,
                "price_range": 0,
                "user_auth": "",
            }

            await self._wait_slot()
            response = await self.http.request(
                "POST", f"{self.base}/pageGifts", json=payload, headers=self._headers()
            )
            if response.status == 403:
                raise MarketRateLimited("Tonnel: Cloudflare/403", 5.0)
            if response.status == 429:
                raise MarketRateLimited("Tonnel: rate limited", 3.0)
            if response.status >= 400:
                raise MarketError(response.status, f"Tonnel pageGifts: {response.text[:200]}")

            data = response.json()
            if isinstance(data, dict) and data.get("status") == "error":
                raise MarketError(response.status, f"Tonnel: {data.get('message') or data}")
            if not isinstance(data, list):
                raise MarketError(response.status, f"Tonnel: unexpected response {str(data)[:160]}")

            fresh = 0
            for item in data:
                parsed = self._parse_item(item)
                if parsed is not None and parsed.id not in seen:
                    seen.add(parsed.id)
                    out.append(parsed)
                    fresh += 1

            if len(data) < per_page or fresh == 0:
                break
            page += 1

        return out

    def _parse_item(self, item: dict[str, Any]) -> Listing | None:
        try:
            gift_id = to_int(item.get("gift_id"))
            if gift_id is None or gift_id < 0 or item.get("auction"):
                return None
            price = to_float(item.get("price"))
            if price <= 0:
                return None
            collection = str(item.get("name") or item.get("gift_name") or "")
            number = to_int(item.get("gift_num"))
            return Listing(
                market=self.name,
                id=str(gift_id),
                collection=collection,
                model=strip_rarity(item.get("model")) or None,
                backdrop=strip_rarity(item.get("backdrop")) or None,
                symbol=strip_rarity(item.get("symbol")) or None,
                number=number,
                price_ton=price,
                url=None,
                listed_at=item.get("message_post_time") or item.get("listed_at"),
                raw=item,
            )
        except (TypeError, ValueError, KeyError) as exc:
            log.debug("Tonnel: skipping malformed item: %s", exc)
            return None
