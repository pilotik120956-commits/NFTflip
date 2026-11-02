"""Plain data structures shared by adapters, matcher, storage and the bot."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MARKET_NAMES = {
    "portals": "Portals",
    "tonnel": "Tonnel",
    "mrkt": "MRKT",
}


def market_name(market: str) -> str:
    return MARKET_NAMES.get(market.lower(), market)


def slugify(value: str) -> str:
    """Telegram NFT slug fragment: only ASCII letters and digits."""
    return re.sub(r"[^A-Za-z0-9]", "", value or "")


@dataclass(slots=True)
class Listing:
    """One listing on one marketplace. Price is the displayed ask, in TON."""

    market: str
    id: str
    collection: str
    model: str | None = None
    backdrop: str | None = None
    symbol: str | None = None
    number: int | None = None
    price_ton: float = 0.0
    url: str | None = None
    listed_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def market_title(self) -> str:
        return market_name(self.market)

    @property
    def tg_slug(self) -> str | None:
        if self.number is None or not self.collection:
            return None
        return f"{slugify(self.collection)}-{self.number}"

    @property
    def tg_url(self) -> str | None:
        slug = self.tg_slug
        return f"https://t.me/nft/{slug}" if slug else None

    @property
    def link(self) -> str | None:
        return self.url or self.tg_url

    @property
    def title(self) -> str:
        number = f" #{self.number}" if self.number is not None else ""
        return f"{self.collection}{number}"

    @property
    def traits(self) -> str:
        parts = [x for x in (self.model, self.backdrop, self.symbol) if x]
        return " / ".join(parts) if parts else "—"


@dataclass(slots=True)
class Offer:
    """A cross-market opportunity: buy cheap here, resell higher there."""

    gift_key: str
    collection: str
    model: str | None
    backdrop: str | None
    symbol: str | None
    number: int | None

    buy: Listing
    sell_reference: Listing

    buy_cost: float
    sell_ask: float
    est_sale: float
    resale_net: float
    profit: float

    roi_pct: float
    margin_pct: float

    buy_fee_pct: float
    sell_fee_pct: float
    withdraw_fee_ton: float

    market_asks: dict[str, float]
    other_listings: list[Listing]
    match_type: str  # "number" | "attributes"

    @property
    def offer_key(self) -> str:
        return f"{self.gift_key}:{self.buy.market}:{self.buy.price_ton:.6f}"

    @property
    def gap_pct(self) -> float:
        """How much cheaper the buy ask is than the cheapest other-market ask."""
        if self.sell_ask <= 0:
            return 0.0
        return (self.sell_ask - self.buy.price_ton) / self.sell_ask * 100.0

    @property
    def link(self) -> str | None:
        return self.buy.tg_url or self.buy.link
