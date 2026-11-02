"""Normalisation and gift-identity tests."""

from __future__ import annotations

import unittest

from models import Listing
from utils.normalize import collection_key, gift_key, norm_attr, strip_rarity


def listing(number: int | None, collection: str = "Durov's Cap", model: str = "Wizard") -> Listing:
    return Listing(
        market="portals",
        id=str(number),
        collection=collection,
        model=model,
        number=number,
        price_ton=1.0,
    )


class NormalizeTests(unittest.TestCase):
    def test_strip_rarity(self) -> None:
        self.assertEqual(strip_rarity("Wizard (1.5%)"), "Wizard")
        self.assertEqual(strip_rarity("Wizard"), "Wizard")
        self.assertEqual(strip_rarity(None), "")

    def test_collection_key(self) -> None:
        self.assertEqual(collection_key("Durov's Cap"), "durovscap")
        self.assertEqual(collection_key("DurovsCap"), "durovscap")
        self.assertEqual(collection_key("Durov’s Cap"), "durovscap")

    def test_norm_attr(self) -> None:
        self.assertEqual(norm_attr("  Wizard (1.5%) "), "wizard")
        self.assertEqual(norm_attr("Pear"), norm_attr("pear"))

    def test_gift_key_number(self) -> None:
        a = listing(42)
        b = listing(42, model="Dragon")  # model is validated separately
        self.assertEqual(gift_key(a), gift_key(b))
        self.assertEqual(gift_key(a), "durovscap#42")

    def test_gift_key_attributes(self) -> None:
        a = listing(None)
        b = listing(None)
        self.assertTrue(gift_key(a).startswith("durovscap?"))
        self.assertEqual(gift_key(a), gift_key(b))


if __name__ == "__main__":
    unittest.main()
