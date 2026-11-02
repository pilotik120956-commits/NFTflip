"""Cross-market matcher tests."""

from __future__ import annotations

import unittest

from core.calculator import Fees
from core.matcher import build_offers, watch_matches
from models import Listing

FEES = {
    "portals": Fees("portals", buy_pct=0.0, sell_pct=2.0, withdraw_ton=0.0),
    "tonnel": Fees("tonnel", buy_pct=0.5, sell_pct=0.5, withdraw_ton=0.0),
    "mrkt": Fees("mrkt", buy_pct=0.0, sell_pct=0.0, withdraw_ton=0.17),
}


def fees_for(market: str) -> Fees:
    return FEES[market]


def listing(
    market: str,
    price: float,
    number: int | None = 42,
    model: str = "Wizard",
    collection: str = "Toy Bear",
    backdrop: str = "Amber",
    symbol: str = "Pear",
) -> Listing:
    return Listing(
        market=market,
        id=f"{market}-{number}-{price}",
        collection=collection,
        model=model,
        backdrop=backdrop,
        symbol=symbol,
        number=number,
        price_ton=price,
    )


class MatcherTests(unittest.TestCase):
    def test_three_markets_produces_offer(self) -> None:
        offers = build_offers(
            [listing("portals", 100), listing("tonnel", 130), listing("mrkt", 135)],
            fees_for,
            min_margin_pct=8,
            resale_discount_pct=0,
        )
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer.buy.market, "portals")
        self.assertEqual(offer.sell_reference.market, "tonnel")
        self.assertAlmostEqual(offer.buy_cost, 100.0)
        self.assertAlmostEqual(offer.resale_net, 129.35)
        self.assertAlmostEqual(offer.profit, 29.35)
        self.assertEqual(offer.match_type, "number")
        self.assertTrue(watch_matches(offer, "Toy Bear", "Wizard"))
        self.assertFalse(watch_matches(offer, "Toy Bear", "Dragon"))

    def test_two_markets_still_work(self) -> None:
        offers = build_offers(
            [listing("portals", 10), listing("tonnel", 20)], fees_for, min_margin_pct=5
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].buy.market, "portals")

    def test_model_mismatch_is_skipped(self) -> None:
        offers = build_offers(
            [listing("portals", 100), listing("tonnel", 130, model="Dragon")],
            fees_for,
            min_margin_pct=0,
        )
        self.assertEqual(offers, [])

    def test_below_threshold_is_skipped(self) -> None:
        offers = build_offers(
            [listing("portals", 100), listing("tonnel", 103)], fees_for, min_margin_pct=8
        )
        self.assertEqual(offers, [])

    def test_budget_filter(self) -> None:
        offers = build_offers(
            [listing("portals", 100), listing("tonnel", 130)],
            fees_for,
            min_margin_pct=0,
            max_buy_cost=50,
        )
        self.assertEqual(offers, [])

    def test_resale_discount_reduces_profit(self) -> None:
        raw = build_offers(
            [listing("portals", 100), listing("tonnel", 140)],
            fees_for,
            min_margin_pct=0,
            resale_discount_pct=0,
        )[0]
        discounted = build_offers(
            [listing("portals", 100), listing("tonnel", 140)],
            fees_for,
            min_margin_pct=0,
            resale_discount_pct=10,
        )[0]
        self.assertLess(discounted.profit, raw.profit)
        self.assertAlmostEqual(discounted.est_sale, 126.0)

    def test_attributes_fallback_when_number_missing(self) -> None:
        offers = build_offers(
            [listing("portals", 50, number=None), listing("tonnel", 80, number=None)],
            fees_for,
            min_margin_pct=0,
        )
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].match_type, "attributes")

    def test_high_buy_fee_can_remove_the_price_advantage(self) -> None:
        fees = {
            "portals": Fees("portals", 0, 2, 0),
            "tonnel": Fees("tonnel", 10, 0, 0),
            "mrkt": Fees("mrkt", 0, 0, 0),
        }
        # Tonnel lists at 99 but costs 108.9 all-in; Portals at 100 is cheaper.
        offers = build_offers(
            [listing("portals", 100), listing("tonnel", 99), listing("mrkt", 200)],
            lambda m: fees[m],
            min_margin_pct=0,
        )
        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()
