"""Normalisation helpers used to match the same gift across marketplaces."""

from __future__ import annotations

import re

from models import Listing

# Tonnel appends the rarity to attribute names: "Wizard (1.5%)" -> "Wizard".
_RARITY_RE = re.compile(r"^(.*?)\s*\(\s*[\d.]+\s*%\s*\)\s*$")
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+")


def strip_rarity(value: str | None) -> str:
    if not value:
        return ""
    match = _RARITY_RE.match(value)
    return (match.group(1) if match else value).strip()


def norm_attr(value: str | None) -> str:
    """Case/spacing/punctuation-insensitive attribute key, without the rarity suffix."""
    return " ".join(strip_rarity(value).casefold().split())


def collection_key(value: str | None) -> str:
    """'Durov's Cap' -> 'durovscap' (also matches t.me/nft slugs)."""
    return _NON_ALNUM_RE.sub("", strip_rarity(value).casefold())


def gift_key(listing: Listing) -> str:
    """Identity of a concrete Telegram gift.

    A Telegram gift number is unique inside a collection, so collection + number is the
    strongest key. When a market omits the number, fall back to the visual attributes.
    """
    coll = collection_key(listing.collection)
    if listing.number is not None:
        return f"{coll}#{listing.number}"
    attrs = "|".join(norm_attr(x) for x in (listing.model, listing.backdrop, listing.symbol))
    return f"{coll}?{attrs}"


def same_model(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True
    return norm_attr(a) == norm_attr(b)
