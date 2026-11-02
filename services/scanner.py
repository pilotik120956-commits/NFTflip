"""The scan loop: collect listings, match gifts across markets, alert users."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from adapters.base import BaseAdapter
from config import Settings
from core.matcher import build_offers
from db.database import Database
from models import Listing, Offer

log = logging.getLogger(__name__)

OfferHandler = Callable[[int, Offer, dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class ScanReport:
    started_at: datetime
    finished_at: datetime
    duration_sec: float
    queries: int = 0
    listings: int = 0
    offers: int = 0
    sent: int = 0
    errors: dict[str, int] = field(default_factory=dict)
    market_counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return sum(self.errors.values()) == 0


class Scanner:
    def __init__(self, settings: Settings, db: Database, adapters: dict[str, BaseAdapter]) -> None:
        self.settings = settings
        self.db = db
        self.adapters = adapters
        self.on_offer: OfferHandler | None = None
        self.last_report: ScanReport | None = None
        self.next_scan_at: float | None = None

        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._scan_lock = asyncio.Lock()

    # --- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="nftflip-scan-loop")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        await asyncio.gather(*(adapter.close() for adapter in self.adapters.values()), return_exceptions=True)

    async def _loop(self) -> None:
        log.info("Scanner started: interval %ss day / %ss night",
                 self.settings.scan_interval_sec, self.settings.night_interval_sec)
        while not self._stop.is_set():
            try:
                await self.scan_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the loop must survive any adapter bug
                log.exception("Scan cycle failed")
            interval = self.settings.current_interval()
            self.next_scan_at = time.time() + interval
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except (TimeoutError, asyncio.TimeoutError):
                pass

    # --- public scans ----------------------------------------------------------

    async def scan_once(self) -> tuple[ScanReport, list[Offer]]:
        async with self._scan_lock:
            queries = await self.db.all_watch_queries(self.settings.max_watch_queries)
            return await self._run(queries, notify=True)

    async def scan_adhoc(self, collection: str, model: str | None = None) -> tuple[ScanReport, list[Offer]]:
        """One-off scan without a database watch (used by `python run.py scan`)."""
        queries = [{"collection": collection, "model": model or "", "users": 1}]
        return await self._run(queries, notify=False)

    async def scan_for_user(self, tg_id: int, limit: int = 8) -> tuple[ScanReport, list[Offer]]:
        """Manual "start search": scan only this user's watches, filter by their limits.

        Does not save signals or mark them as sent, so manual searches never eat into
        the periodic alert cooldown.
        """
        user = await self.db.get_user(tg_id)
        watches = await self.db.list_watch(tg_id)

        queries: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in watches:
            key = (str(row["collection_key"]), str(row.get("model_key") or ""))
            if key in seen:
                continue
            seen.add(key)
            queries.append(
                {
                    "collection": row["collection"],
                    "model": row.get("model") or "",
                    "users": 1,
                }
            )

        async with self._scan_lock:
            report, offers = await self._run(queries, notify=False)

        if user is None or not offers:
            return report, []

        budget = float(user.get("budget_ton") or 0)
        min_margin = float(user.get("min_margin_pct") or 0)
        filtered = [
            offer
            for offer in offers
            if offer.buy_cost <= budget and offer.margin_pct >= min_margin
        ]
        filtered.sort(key=lambda offer: (offer.profit, offer.margin_pct), reverse=True)
        return report, filtered[: max(1, limit)]

    # --- internals -------------------------------------------------------------

    async def _run(self, queries: list[dict[str, Any]], *, notify: bool) -> tuple[ScanReport, list[Offer]]:
        started_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        active = {name: adapter for name, adapter in self.adapters.items() if adapter.enabled}
        errors = {name: 0 for name in active}
        counts = {name: 0 for name in active}
        listings: list[Listing] = []
        offer_count = 0
        sent = 0

        if queries:
            listings, errors, counts = await self._collect(queries, active)
            offers = build_offers(
                listings,
                self.settings.fees_for,
                min_margin_pct=0.0,
                resale_discount_pct=self.settings.resale_discount_pct,
            )
            offer_count = len(offers)
            if notify:
                sent = await self._dispatch(offers)
        else:
            offers = []

        finished_at = datetime.now(timezone.utc)
        report = ScanReport(
            started_at=started_at,
            finished_at=finished_at,
            duration_sec=round(time.perf_counter() - started, 2),
            queries=len(queries),
            listings=len(listings),
            offers=offer_count,
            sent=sent,
            errors=errors,
            market_counts=counts,
        )
        self.last_report = report
        log.info(
            "Scan: %s queries, %s listings, %s offers, %s alerts, %.2fs, errors=%s",
            report.queries, report.listings, report.offers, report.sent, report.duration_sec,
            {k: v for k, v in report.errors.items() if v},
        )
        return report, offers

    async def _collect(
        self, queries: list[dict[str, Any]], adapters: dict[str, BaseAdapter]
    ) -> tuple[list[Listing], dict[str, int], dict[str, int]]:
        listings: list[Listing] = []
        errors = {name: 0 for name in adapters}
        counts = {name: 0 for name in adapters}

        for query in queries:
            collection = query["collection"]
            model = query.get("model") or None
            tasks = [
                self._fetch(name, adapter, collection, model)
                for name, adapter in adapters.items()
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for (name, _adapter), result in zip(adapters.items(), results):
                if isinstance(result, BaseException):
                    errors[name] += 1
                    log.warning("%s: %s (%s)", name, result, collection)
                    continue
                listings.extend(result)
                counts[name] += len(result)
        return listings, errors, counts

    async def _fetch(
        self, name: str, adapter: BaseAdapter, collection: str, model: str | None
    ) -> list[Listing]:
        timeout = max(20.0, self.settings.http_timeout * 3)
        try:
            result = await asyncio.wait_for(
                adapter.search(collection, model, self.settings.max_listings_per_query),
                timeout=timeout,
            )
        except Exception as exc:
            await self.db.set_market_health(name, False, error=f"{type(exc).__name__}: {exc}")
            raise
        await self.db.set_market_health(name, True, listings=len(result))
        return result

    async def _dispatch(self, offers: list[Offer]) -> int:
        if self.on_offer is None:
            return 0
        sent = 0
        today_cache: dict[int, float] = {}

        for offer in offers:
            users = await self.db.users_for_offer(offer.collection, offer.model)
            eligible: list[dict[str, Any]] = []
            for user in users:
                tg_id = int(user["tg_id"])
                if offer.buy_cost > float(user["budget_ton"]):
                    continue
                if offer.margin_pct < float(user["min_margin_pct"]):
                    continue
                if await self.db.was_sent(tg_id, offer.offer_key, offer.buy.price_ton,
                                          self.settings.signal_cooldown_sec):
                    continue
                if tg_id not in today_cache:
                    today_cache[tg_id] = await self.db.sent_total_today(tg_id)
                if today_cache[tg_id] + offer.buy_cost > float(user["daily_budget_ton"]):
                    continue
                eligible.append(user)
            if not eligible:
                continue

            await self.db.save_signal(offer)
            for user in eligible:
                tg_id = int(user["tg_id"])
                try:
                    await self.on_offer(tg_id, offer, user)
                except Exception as exc:  # noqa: BLE001 - one blocked user must not stop the cycle
                    log.warning("Could not send offer to %s: %s", tg_id, exc)
                    continue
                await self.db.mark_sent(tg_id, offer.offer_key, offer.buy.price_ton, offer.buy_cost)
                today_cache[tg_id] = today_cache.get(tg_id, 0.0) + offer.buy_cost
                sent += 1
        return sent
