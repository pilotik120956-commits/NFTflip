"""Fee-aware profit calculator. No network, no storage: pure arithmetic."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Fees:
    market: str
    buy_pct: float = 0.0
    sell_pct: float = 0.0
    withdraw_ton: float = 0.0


@dataclass(frozen=True, slots=True)
class CalcResult:
    buy_price: float
    buy_cost: float
    sell_price: float
    sell_fee: float
    withdraw_fee: float
    resale_net: float
    profit: float
    roi_pct: float
    margin_pct: float
    breakeven_sell: float
    buy_fees: Fees
    sell_fees: Fees


def buy_cost(price: float, fees: Fees) -> float:
    """What the buyer pays: the ask plus the marketplace's buyer fee."""
    return round(price * (1.0 + fees.buy_pct / 100.0), 9)


def resale_net(price: float, fees: Fees) -> float:
    """What reaches your wallet: the sale price minus seller fee and withdrawal."""
    net = price * (1.0 - fees.sell_pct / 100.0) - fees.withdraw_ton
    return round(max(0.0, net), 9)


def breakeven_sell(buy_price: float, buy_fees: Fees, sell_fees: Fees) -> float:
    """Lowest sale price that returns exactly the all-in purchase cost."""
    cost = buy_cost(buy_price, buy_fees)
    divisor = 1.0 - sell_fees.sell_pct / 100.0
    if divisor <= 0:
        return float("inf")
    return round((cost + sell_fees.withdraw_ton) / divisor, 9)


def evaluate(buy_price: float, sell_price: float, buy_fees: Fees, sell_fees: Fees) -> CalcResult:
    cost = buy_cost(buy_price, buy_fees)
    gross = max(0.0, sell_price)
    sell_fee = round(gross * sell_fees.sell_pct / 100.0, 9)
    net = resale_net(gross, sell_fees)
    profit = round(net - cost, 9)
    roi = round(profit / cost * 100.0, 4) if cost > 0 else 0.0
    margin = round(profit / net * 100.0, 4) if net > 0 else 0.0
    return CalcResult(
        buy_price=buy_price,
        buy_cost=cost,
        sell_price=gross,
        sell_fee=sell_fee,
        withdraw_fee=sell_fees.withdraw_ton,
        resale_net=net,
        profit=profit,
        roi_pct=roi,
        margin_pct=margin,
        breakeven_sell=breakeven_sell(buy_price, buy_fees, sell_fees),
        buy_fees=buy_fees,
        sell_fees=sell_fees,
    )


# --- formatting ---------------------------------------------------------------


def fmt_ton(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "—"
    text = f"{value:,.{digits}f}".replace(",", " ")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fmt_pct(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}%"


def fmt_usd(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def ton_to_usd(ton: float | None, rate: float | None) -> float | None:
    if ton is None or rate is None:
        return None
    return ton * rate
