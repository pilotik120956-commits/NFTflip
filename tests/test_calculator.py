"""Fee calculator tests (pure arithmetic)."""

from __future__ import annotations

import unittest

from core.calculator import (
    Fees,
    breakeven_sell,
    buy_cost,
    evaluate,
    fmt_pct,
    fmt_ton,
    resale_net,
)

PORTALS = Fees("portals", buy_pct=0.0, sell_pct=2.0, withdraw_ton=0.0)
TONNEL = Fees("tonnel", buy_pct=0.5, sell_pct=0.5, withdraw_ton=0.0)
MRKT = Fees("mrkt", buy_pct=0.0, sell_pct=0.0, withdraw_ton=0.17)


class CalculatorTests(unittest.TestCase):
    def test_buy_cost_includes_buyer_fee(self) -> None:
        self.assertAlmostEqual(buy_cost(100, PORTALS), 100.0)
        self.assertAlmostEqual(buy_cost(100, TONNEL), 100.5)

    def test_resale_net_includes_seller_fee_and_withdrawal(self) -> None:
        self.assertAlmostEqual(resale_net(130, PORTALS), 127.4)
        self.assertAlmostEqual(resale_net(130, MRKT), 129.83)
        self.assertAlmostEqual(resale_net(0.1, MRKT), 0.0)

    def test_evaluate_portals_buy_tonnel_sell(self) -> None:
        result = evaluate(100, 130, PORTALS, TONNEL)
        self.assertAlmostEqual(result.buy_cost, 100.0)
        self.assertAlmostEqual(result.resale_net, 129.35)
        self.assertAlmostEqual(result.profit, 29.35)
        self.assertAlmostEqual(result.roi_pct, 29.35)
        self.assertAlmostEqual(result.margin_pct, 22.6904, places=3)

    def test_evaluate_with_withdrawal(self) -> None:
        result = evaluate(5, 7, PORTALS, MRKT)
        self.assertAlmostEqual(result.resale_net, 6.83)
        self.assertAlmostEqual(result.profit, 1.83)
        self.assertGreater(result.roi_pct, 36)

    def test_breakeven(self) -> None:
        # Need 102 at a 2% seller fee to get 100 back.
        self.assertAlmostEqual(breakeven_sell(100, PORTALS, PORTALS), 102.040816, places=5)
        self.assertAlmostEqual(breakeven_sell(100, TONNEL, TONNEL), 101.005025, places=5)

    def test_formatting(self) -> None:
        self.assertEqual(fmt_ton(1.5), "1.5")
        self.assertEqual(fmt_ton(1.0), "1")
        self.assertEqual(fmt_ton(1234.5678), "1 234.5678")
        self.assertEqual(fmt_pct(8.0), "8.0%")
        self.assertEqual(fmt_ton(None), "—")


if __name__ == "__main__":
    unittest.main()
