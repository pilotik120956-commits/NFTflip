"""Single entry point.

Usage:
    python run.py                 # start the Telegram bot + scanner
    python run.py scan            # one scan, print offers (no Telegram needed)
    python run.py scan --collection "Durov's Cap" --model Wizard
    python run.py doctor          # check config and marketplace connectivity
    python run.py login           # Telethon login for automatic MRKT initData
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from adapters import MrktAdapter, PortalsAdapter, TonnelAdapter
from bot.formatting import fmt_pct, fmt_ton
from bot.main import build_adapters, configure_logging, run_bot
from config import get_settings
from db.database import Database
from models import market_name
from services.rates import TonRate
from services.scanner import Scanner


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass


def print_offer(offer) -> None:
    number = f" #{offer.number}" if offer.number is not None else ""
    print("-" * 66)
    print(f"🔥 {offer.collection}{number}  [{offer.buy.traits}]")
    print(
        f"   BUY  {market_name(offer.buy.market):8} "
        f"{fmt_ton(offer.buy.price_ton)} TON  (all-in {fmt_ton(offer.buy_cost)})"
    )
    print(
        f"   SELL {market_name(offer.sell_reference.market):8} "
        f"ask {fmt_ton(offer.sell_ask)} -> est {fmt_ton(offer.est_sale)} "
        f"-> net {fmt_ton(offer.resale_net)}"
    )
    print(
        f"   profit {fmt_ton(offer.profit)} TON | ROI {fmt_pct(offer.roi_pct)} | "
        f"margin {fmt_pct(offer.margin_pct)} | gap {fmt_pct(offer.gap_pct)}"
    )
    print(f"   {offer.link or '(no link)'}")


async def doctor() -> None:
    settings = get_settings()
    configure_logging(settings)
    print("NFTflip doctor")
    print(f"  BOT_TOKEN:      {'set' if settings.bot_token else 'MISSING'}")
    print(f"  ALLOWED_USERS:  {len(settings.allowed_user_ids)}")
    print(f"  DB:             {settings.db_path}")
    print(f"  Interval:       {settings.scan_interval_sec}s day / {settings.night_interval_sec}s night")
    print(f"  Min margin:     {settings.default_min_margin_pct:g}%")
    print(f"  MRKT auth:      {'configured' if settings.mrkt_configured else 'NOT configured'}")
    for market in ("portals", "tonnel", "mrkt"):
        fees = settings.fees_for(market)
        print(
            f"  {market_name(market):8} fees: buy {fees.buy_pct:g}% / "
            f"sell {fees.sell_pct:g}% / withdraw {fees.withdraw_ton:g} TON"
        )

    db = Database(settings.db_path)
    await db.init()
    counts = await db.counts()
    print(f"  Users: {counts['users']} | watches: {counts['watches']} | signals: {counts['signals']}")

    adapters = build_adapters(settings)
    try:
        for name, adapter in adapters.items():
            if not adapter.enabled:
                print(f"  {market_name(name):8} API: SKIPPED — not configured")
                continue
            try:
                collections = await adapter.collections()
                print(f"  {market_name(name):8} API: OK ({len(collections)} collections)")
            except Exception as exc:  # noqa: BLE001
                print(f"  {market_name(name):8} API: FAIL — {exc}")

        watches = await db.all_watch_queries(1)
        if watches:
            query = watches[0]
            print(f"  Sample search: {query['collection']} / {query['model'] or 'all models'}")
            for name, adapter in adapters.items():
                if not adapter.enabled:
                    continue
                try:
                    listings = await adapter.search(query["collection"], query["model"] or None, 5)
                    print(f"    {market_name(name):8} {len(listings)} listing(s)")
                except Exception as exc:  # noqa: BLE001
                    print(f"    {market_name(name):8} FAIL — {exc}")
        else:
            print("  Sample search: skipped (no watches; use /add in the bot)")
    finally:
        await asyncio.gather(*(a.close() for a in adapters.values()), return_exceptions=True)
        await db.close()

    rate = await TonRate(settings).get()
    print(f"  TON/USD:        {rate if rate is not None else 'unavailable'}")


async def scan_once(collection: str | None, model: str | None) -> None:
    settings = get_settings()
    configure_logging(settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    db = Database(settings.db_path)
    await db.init()
    adapters = build_adapters(settings)
    scanner = Scanner(settings, db, adapters)
    try:
        if collection:
            report, offers = await scanner.scan_adhoc(collection, model)
        else:
            report, offers = await scanner.scan_once()

        print(
            f"Scan: {report.queries} quer{'y' if report.queries == 1 else 'ies'}, "
            f"{report.listings} listings, {report.offers} offers, {report.duration_sec:.1f}s"
        )
        if report.errors and any(report.errors.values()):
            print("Errors:", {k: v for k, v in report.errors.items() if v})
        if not offers:
            print("No profitable cross-market offers this time.")
        for offer in offers:
            print_offer(offer)
        if not collection and report.queries == 0:
            print("No watches yet. Add one with /add in the bot, or pass --collection.")
    finally:
        await asyncio.gather(*(a.close() for a in adapters.values()), return_exceptions=True)
        await db.close()


async def login() -> None:
    from utils.tg_auth import interactive_login

    settings = get_settings()
    configure_logging(settings)
    await interactive_login(settings)


def main() -> None:
    _utf8_console()
    parser = argparse.ArgumentParser(prog="nftflip", description="Telegram gift arbitrage bot")
    parser.add_argument(
        "mode",
        nargs="?",
        default="bot",
        choices=["bot", "scan", "doctor", "login"],
        help="bot (default), scan, doctor or login",
    )
    parser.add_argument("--collection", help="collection for `scan`")
    parser.add_argument("--model", help="model for `scan`")
    args = parser.parse_args()

    if args.mode == "bot":
        asyncio.run(run_bot())
    elif args.mode == "scan":
        asyncio.run(scan_once(args.collection, args.model))
    elif args.mode == "doctor":
        asyncio.run(doctor())
    elif args.mode == "login":
        asyncio.run(login())


if __name__ == "__main__":
    main()
