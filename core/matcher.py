"""Cross-market matching: the same gift cheaper on one market than the others."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from core.calculator import Fees, buy_cost, evaluate, resale_net  # noqa: F401
from models import Listing, Offer
from utils.normalize import collection_key, gift_key, norm_attr

FeesFor = Callable[[str], Fees]


def _cheapest_per_market(group: list[Listing], fees_for: FeesFor) -> dict[str, Listing]:
    best: dict[str, Listing] = {}
    for listing in group:
        if listing.price_ton <= 0:
            continue
        current = best.get(listing.market)
        if current is None or buy_cost(listing.price_ton, fees_for(listing.market)) < buy_cost(
            current.price_ton, fees_for(current.market)
        ):
            best[listing.market] = listing
    return best


def _models_conflict(group: list[Listing]) -> bool:
    """The same Telegram number must have the same model on every market.

    A mismatch means one marketplace has stale/incorrect metadata; skip such a group
    instead of producing a false signal.
    """
    models = {norm_attr(x.model) for x in group if x.model}
    return len(models) > 1


def build_offers(
    listings: list[Listing],
    fees_for: FeesFor,
    *,
    min_margin_pct: float = 0.0,
    resale_discount_pct: float = 0.0,
    max_buy_cost: float | None = None,
) -> list[Offer]:
    """Return fee-aware opportunities, best profit first.

    A signal requires the buy ask to be cheaper than *every other* market that has the
    same gift (two cheaper markets when three are present), and the estimated net margin
    to clear `min_margin_pct`.
    """
    groups: dict[str, list[Listing]] = defaultdict(list)
    for listing in listings:
        if listing.price_ton <= 0 or not listing.collection:
            continue
        groups[gift_key(listing)].append(listing)

    offers: list[Offer] = []
    for key, group in groups.items():
        markets = _cheapest_per_market(group, fees_for)
        if len(markets) < 2 or _models_conflict(group):
            continue

        buy = min(markets.values(), key=lambda x: buy_cost(x.price_ton, fees_for(x.market)))
        others = [x for name, x in markets.items() if name != buy.market]
        if not others:
            continue

        # "Cheaper than the two other markets": with three markets present both must be
        # more expensive; with only two, one is enough.
        required = 2 if len(markets) >= 3 else 1
        cheaper = [x for x in others if buy.price_ton < x.price_ton * 0.995]
        if len(cheaper) < required:
            continue

        reference = min(others, key=lambda x: x.price_ton)
        est_sale = round(reference.price_ton * (1.0 - max(0.0, resale_discount_pct) / 100.0), 9)

        buy_fees = fees_for(buy.market)
        sell_fees = fees_for(reference.market)
        result = evaluate(buy.price_ton, est_sale, buy_fees, sell_fees)

        if result.profit <= 0 or result.margin_pct < min_margin_pct:
            continue
        if max_buy_cost is not None and result.buy_cost > max_buy_cost:
            continue

        others_sorted = sorted(others, key=lambda x: x.price_ton)
        offers.append(
            Offer(
                gift_key=key,
                collection=buy.collection,
                model=buy.model or reference.model,
                backdrop=buy.backdrop or reference.backdrop,
                symbol=buy.symbol or reference.symbol,
                number=buy.number,
                buy=buy,
                sell_reference=reference,
                buy_cost=result.buy_cost,
                sell_ask=reference.price_ton,
                est_sale=est_sale,
                resale_net=result.resale_net,
                profit=result.profit,
                roi_pct=result.roi_pct,
                margin_pct=result.margin_pct,
                buy_fee_pct=buy_fees.buy_pct,
                sell_fee_pct=sell_fees.sell_pct,
                withdraw_fee_ton=sell_fees.withdraw_ton,
                market_asks={x.market: x.price_ton for x in others_sorted},
                other_listings=others_sorted,
                match_type="number" if buy.number is not None else "attributes",
            )
        )

    offers.sort(key=lambda x: (x.profit, x.margin_pct), reverse=True)
    return offers


def watch_matches(offer: Offer, collection: str, model: str | None) -> bool:
    """Does an offer belong to a user's watched collection/model?"""
    if collection_key(offer.collection) != collection_key(collection):
        return False
    return not model or norm_attr(offer.model) == norm_attr(model)
