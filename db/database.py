"""SQLite storage: users, watchlists, signals, per-user settings, market health."""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from models import Offer
from utils.normalize import collection_key, norm_attr

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    tg_id             INTEGER PRIMARY KEY,
    username          TEXT,
    first_name        TEXT,
    budget_ton        REAL NOT NULL DEFAULT 10,
    daily_budget_ton  REAL NOT NULL DEFAULT 50,
    min_margin_pct    REAL NOT NULL DEFAULT 8,
    alerts_enabled    INTEGER NOT NULL DEFAULT 1,
    display_currency  TEXT NOT NULL DEFAULT 'both',
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id          INTEGER NOT NULL REFERENCES users(tg_id) ON DELETE CASCADE,
    collection     TEXT NOT NULL,
    collection_key TEXT NOT NULL,
    model          TEXT NOT NULL DEFAULT '',
    model_key      TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    UNIQUE(tg_id, collection_key, model_key)
);
CREATE INDEX IF NOT EXISTS idx_watch_collection ON watchlist(collection_key, model_key);

CREATE TABLE IF NOT EXISTS signals (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             TEXT NOT NULL,
    offer_key      TEXT NOT NULL,
    gift_key       TEXT NOT NULL,
    collection     TEXT NOT NULL,
    collection_key TEXT NOT NULL,
    model          TEXT,
    model_key      TEXT NOT NULL DEFAULT '',
    number         INTEGER,
    match_type     TEXT NOT NULL,
    buy_market     TEXT NOT NULL,
    buy_price      REAL NOT NULL,
    buy_cost       REAL NOT NULL,
    sell_market    TEXT NOT NULL,
    sell_ask       REAL NOT NULL,
    est_sale       REAL NOT NULL,
    resale_net     REAL NOT NULL,
    profit         REAL NOT NULL,
    roi_pct        REAL NOT NULL,
    margin_pct     REAL NOT NULL,
    url            TEXT,
    payload        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(ts);
CREATE INDEX IF NOT EXISTS idx_signals_collection ON signals(collection_key, model_key);

CREATE TABLE IF NOT EXISTS sent_offers (
    tg_id     INTEGER NOT NULL,
    offer_key TEXT NOT NULL,
    buy_price REAL NOT NULL,
    buy_cost  REAL NOT NULL DEFAULT 0,
    sent_at   TEXT NOT NULL,
    PRIMARY KEY(tg_id, offer_key)
);

CREATE TABLE IF NOT EXISTS market_health (
    market      TEXT PRIMARY KEY,
    ok          INTEGER NOT NULL DEFAULT 0,
    last_ok_at  TEXT,
    last_error  TEXT,
    listings    INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);
"""

USER_EDITABLE = {"budget_ton", "daily_budget_ton", "min_margin_pct", "alerts_enabled", "display_currency"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _listing_snapshot(listing) -> dict[str, Any]:
    data = asdict(listing)
    data.pop("raw", None)
    return data


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.path))
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        await self._db.executescript(SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Cursor:
        assert self._db is not None, "Database.init() was not called"
        async with self._lock:
            cursor = await self._db.execute(sql, params)
            await self._db.commit()
            return cursor

    async def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        assert self._db is not None, "Database.init() was not called"
        cursor = await self._db.execute(sql, params)
        row = await cursor.fetchone()
        await cursor.close()
        return dict(row) if row is not None else None

    async def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        assert self._db is not None, "Database.init() was not called"
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [dict(row) for row in rows]

    # --- users -----------------------------------------------------------------

    async def add_user(
        self,
        tg_id: int,
        username: str | None,
        first_name: str | None,
        *,
        budget_ton: float,
        daily_budget_ton: float,
        min_margin_pct: float,
    ) -> dict[str, Any]:
        now = _utcnow()
        await self._execute(
            """
            INSERT INTO users(tg_id, username, first_name, budget_ton, daily_budget_ton,
                              min_margin_pct, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                updated_at = excluded.updated_at
            """,
            (tg_id, username, first_name, budget_ton, daily_budget_ton, min_margin_pct, now, now),
        )
        user = await self.get_user(tg_id)
        assert user is not None
        return user

    async def get_user(self, tg_id: int) -> dict[str, Any] | None:
        return await self._fetchone("SELECT * FROM users WHERE tg_id = ?", (tg_id,))

    async def update_user(self, tg_id: int, **fields: Any) -> None:
        clean = {k: v for k, v in fields.items() if k in USER_EDITABLE}
        if not clean:
            return
        assignments = ", ".join(f"{key} = ?" for key in clean)
        params = tuple(clean.values()) + (_utcnow(), tg_id)
        await self._execute(f"UPDATE users SET {assignments}, updated_at = ? WHERE tg_id = ?", params)

    async def identify(self, tg_id: int) -> str:
        user = await self.get_user(tg_id)
        if user is None:
            return "—"
        if user.get("username"):
            return f"@{user['username']}"
        return str(tg_id)

    # --- watchlist -------------------------------------------------------------

    async def add_watch(self, tg_id: int, collection: str, model: str | None = None) -> tuple[bool, int | None]:
        collection = " ".join(collection.split())
        model = " ".join((model or "").split())
        ck = collection_key(collection)
        mk = norm_attr(model)
        if not ck:
            return False, None
        cursor = await self._execute(
            """
            INSERT OR IGNORE INTO watchlist(tg_id, collection, collection_key, model, model_key, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (tg_id, collection, ck, model, mk, _utcnow()),
        )
        if cursor.rowcount:
            return True, int(cursor.lastrowid or 0)
        row = await self._fetchone(
            "SELECT id FROM watchlist WHERE tg_id = ? AND collection_key = ? AND model_key = ?",
            (tg_id, ck, mk),
        )
        return False, int(row["id"]) if row else None

    async def remove_watch(self, tg_id: int, watch_id: int) -> bool:
        cursor = await self._execute("DELETE FROM watchlist WHERE tg_id = ? AND id = ?", (tg_id, watch_id))
        return bool(cursor.rowcount)

    async def remove_watch_by_name(self, tg_id: int, collection: str, model: str | None = None) -> int:
        ck = collection_key(collection)
        mk = norm_attr(model)
        if model:
            cursor = await self._execute(
                "DELETE FROM watchlist WHERE tg_id = ? AND collection_key = ? AND model_key = ?",
                (tg_id, ck, mk),
            )
        else:
            cursor = await self._execute(
                "DELETE FROM watchlist WHERE tg_id = ? AND collection_key = ?", (tg_id, ck)
            )
        return int(cursor.rowcount or 0)

    async def list_watch(self, tg_id: int) -> list[dict[str, Any]]:
        return await self._fetchall(
            "SELECT * FROM watchlist WHERE tg_id = ? ORDER BY collection, model", (tg_id,)
        )

    async def all_watch_queries(self, limit: int) -> list[dict[str, Any]]:
        return await self._fetchall(
            """
            SELECT collection, collection_key, model, model_key, COUNT(DISTINCT tg_id) AS users
            FROM watchlist
            GROUP BY collection_key, model_key
            ORDER BY users DESC, collection, model
            LIMIT ?
            """,
            (max(1, limit),),
        )

    async def users_for_offer(self, collection: str, model: str | None) -> list[dict[str, Any]]:
        return await self._fetchall(
            """
            SELECT u.*
            FROM users u
            JOIN watchlist w ON w.tg_id = u.tg_id
            WHERE u.alerts_enabled = 1
              AND w.collection_key = ?
              AND (w.model_key = '' OR w.model_key = ?)
            GROUP BY u.tg_id
            """,
            (collection_key(collection), norm_attr(model)),
        )

    # --- signals and de-duplication --------------------------------------------

    async def save_signal(self, offer: Offer) -> int:
        payload = {
            "buy": _listing_snapshot(offer.buy),
            "sell_reference": _listing_snapshot(offer.sell_reference),
            "market_asks": offer.market_asks,
            "match_type": offer.match_type,
            "gap_pct": offer.gap_pct,
        }
        cursor = await self._execute(
            """
            INSERT INTO signals(ts, offer_key, gift_key, collection, collection_key, model, model_key,
                                number, match_type, buy_market, buy_price, buy_cost, sell_market,
                                sell_ask, est_sale, resale_net, profit, roi_pct, margin_pct, url, payload)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _utcnow(), offer.offer_key, offer.gift_key, offer.collection,
                collection_key(offer.collection), offer.model, norm_attr(offer.model),
                offer.number, offer.match_type, offer.buy.market, offer.buy.price_ton,
                offer.buy_cost, offer.sell_reference.market, offer.sell_ask, offer.est_sale,
                offer.resale_net, offer.profit, offer.roi_pct, offer.margin_pct,
                offer.link, json.dumps(payload, ensure_ascii=False, default=str),
            ),
        )
        return int(cursor.lastrowid or 0)

    async def recent_signals(self, tg_id: int, limit: int = 10) -> list[dict[str, Any]]:
        return await self._fetchall(
            """
            SELECT s.* FROM signals s
            WHERE EXISTS (
                SELECT 1 FROM watchlist w
                WHERE w.tg_id = ?
                  AND w.collection_key = s.collection_key
                  AND (w.model_key = '' OR w.model_key = s.model_key)
            )
            ORDER BY s.id DESC
            LIMIT ?
            """,
            (tg_id, max(1, limit)),
        )

    async def was_sent(self, tg_id: int, offer_key: str, price: float, cooldown_sec: int) -> bool:
        row = await self._fetchone(
            "SELECT buy_price, sent_at FROM sent_offers WHERE tg_id = ? AND offer_key = ?",
            (tg_id, offer_key),
        )
        if row is None:
            return False
        try:
            sent_at = datetime.fromisoformat(str(row["sent_at"]))
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        age = (datetime.now(timezone.utc) - sent_at).total_seconds()
        # A materially cheaper relist is worth a new alert even inside the cooldown.
        if price < float(row["buy_price"]) * 0.995:
            return False
        return age < cooldown_sec

    async def mark_sent(self, tg_id: int, offer_key: str, price: float, buy_cost: float = 0.0) -> None:
        await self._execute(
            """
            INSERT INTO sent_offers(tg_id, offer_key, buy_price, buy_cost, sent_at)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(tg_id, offer_key) DO UPDATE SET
                buy_price = excluded.buy_price,
                buy_cost = excluded.buy_cost,
                sent_at = excluded.sent_at
            """,
            (tg_id, offer_key, price, buy_cost, _utcnow()),
        )

    async def sent_total_today(self, tg_id: int) -> float:
        """All-in cost of every offer already sent to this user since UTC midnight."""
        midnight = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        row = await self._fetchone(
            "SELECT COALESCE(SUM(buy_cost), 0) AS total FROM sent_offers WHERE tg_id = ? AND sent_at >= ?",
            (tg_id, midnight.isoformat(timespec="seconds")),
        )
        return float(row["total"]) if row else 0.0

    # --- market health ---------------------------------------------------------

    async def set_market_health(
        self, market: str, ok: bool, *, error: str | None = None, listings: int | None = None
    ) -> None:
        now = _utcnow()
        if ok:
            await self._execute(
                """
                INSERT INTO market_health(market, ok, last_ok_at, last_error, listings, updated_at)
                VALUES(?, 1, ?, NULL, ?, ?)
                ON CONFLICT(market) DO UPDATE SET
                    ok = 1, last_ok_at = excluded.last_ok_at, last_error = NULL,
                    listings = excluded.listings, updated_at = excluded.updated_at
                """,
                (market, now, int(listings or 0), now),
            )
        else:
            await self._execute(
                """
                INSERT INTO market_health(market, ok, last_ok_at, last_error, listings, updated_at)
                VALUES(?, 0, NULL, ?, ?, ?)
                ON CONFLICT(market) DO UPDATE SET
                    ok = 0, last_error = excluded.last_error,
                    listings = COALESCE(?, market_health.listings), updated_at = excluded.updated_at
                """,
                (market, (error or "unknown error")[:300], int(listings or 0), now, listings),
            )

    async def get_health(self) -> dict[str, dict[str, Any]]:
        rows = await self._fetchall("SELECT * FROM market_health")
        return {row["market"]: row for row in rows}

    # --- housekeeping ----------------------------------------------------------

    async def cleanup(self, days: int = 30) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        await self._execute("DELETE FROM sent_offers WHERE sent_at < ?", (cutoff,))
        await self._execute("DELETE FROM signals WHERE ts < ?", (cutoff,))

    async def counts(self) -> dict[str, int]:
        users = await self._fetchone("SELECT COUNT(*) AS n FROM users")
        watches = await self._fetchone("SELECT COUNT(*) AS n FROM watchlist")
        signals = await self._fetchone("SELECT COUNT(*) AS n FROM signals")
        return {
            "users": int(users["n"]) if users else 0,
            "watches": int(watches["n"]) if watches else 0,
            "signals": int(signals["n"]) if signals else 0,
        }
