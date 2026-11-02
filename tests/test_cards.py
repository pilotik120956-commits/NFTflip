import unittest

from bot.formatting import offer_caption
from models import Listing, Offer


def make_offer(collection: str = "Durov's Cap", number: int = 2504) -> Offer:
    buy = Listing(
        market="portals",
        id="b2ea0459-efdd-461b-a974-162fbce6378c",
        collection=collection,
        model="Creamsicle",
        backdrop="Cyberpunk",
        symbol="Celtic Wolf",
        number=number,
        price_ton=420.999999,
        raw={"photo_url": "https://nft.fragment.com/gift/durovscap-2504.medium.jpg"},
    )
    other = Listing(
        market="tonnel",
        id="10542437",
        collection=collection,
        model="Creamsicle",
        number=number,
        price_ton=500.0,
    )
    return Offer(
        gift_key=f"number:{number}",
        collection=collection,
        model="Creamsicle",
        backdrop="Cyberpunk",
        symbol="Celtic Wolf",
        number=number,
        buy=buy,
        sell_reference=other,
        buy_cost=423.1,
        sell_ask=500.0,
        est_sale=485.0,
        resale_net=475.3,
        profit=52.2,
        roi_pct=12.3,
        margin_pct=10.8,
        buy_fee_pct=0.5,
        sell_fee_pct=0.5,
        withdraw_fee_ton=0.17,
        market_asks={"tonnel": 500.0},
        other_listings=[other],
        match_type="number",
    )


class CardTests(unittest.TestCase):
    def test_market_deep_links(self) -> None:
        portals = make_offer().buy
        self.assertEqual(
            portals.market_url,
            "https://t.me/portals_market_bot/market?startapp=gift_b2ea0459-efdd-461b-a974-162fbce6378c",
        )
        tonnel = Listing(market="tonnel", id="10542437", collection="X")
        self.assertEqual(
            tonnel.market_url,
            "https://t.me/tonnel_network_bot/gift?startapp=10542437",
        )
        mrkt = Listing(market="mrkt", id="abc-123", collection="X")
        self.assertEqual(mrkt.market_url, "https://www.mrkt.land/gift/abc-123")

    def test_image_falls_back_to_fragment(self) -> None:
        listing = Listing(market="tonnel", id="1", collection="Durov's Cap", number=1428)
        self.assertEqual(
            listing.image_url,
            "https://nft.fragment.com/gift/durovscap-1428.medium.jpg",
        )

    def test_caption_stays_under_telegram_limit(self) -> None:
        caption = offer_caption(make_offer(collection="X" * 400), rate=1.2)
        self.assertLessEqual(len(caption), 1024)
        self.assertIn("Portals", caption)


if __name__ == "__main__":
    unittest.main()
