"""Configuration loaded from environment (.env).

Every tunable lives here; no secrets are ever hardcoded. Market fees are defaults
researched in October 2026 and can be overridden in .env without touching the code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

from core.calculator import Fees

ROOT = Path(__file__).resolve().parent
_ENV_FILE = ROOT / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE)
else:  # pragma: no cover - works when the process is started from another folder
    load_dotenv()


def _str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _int(name: str, default: int, *, low: int | None = None, high: int | None = None) -> int:
    try:
        value = int(float(_str(name, str(default))))
    except (TypeError, ValueError):
        value = default
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def _float(name: str, default: float, *, low: float | None = None) -> float:
    try:
        value = float(_str(name, str(default)).replace(",", "."))
    except (TypeError, ValueError):
        value = default
    if low is not None:
        value = max(low, value)
    return value


def _ids(name: str) -> frozenset[int]:
    raw = _str(name)
    if not raw:
        return frozenset()
    out: set[int] = set()
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk.lstrip("-").isdigit():
            out.add(int(chunk))
    return frozenset(out)


@dataclass(frozen=True, slots=True)
class Settings:
    # --- Telegram bot ---------------------------------------------------------
    bot_token: str
    allowed_user_ids: frozenset[int]
    admin_ids: frozenset[int]

    # --- Storage --------------------------------------------------------------
    data_dir: Path
    db_path: Path

    # --- Scanner --------------------------------------------------------------
    scan_interval_sec: int
    night_interval_sec: int
    night_start_hour: int
    night_end_hour: int
    tz_offset_hours: float
    max_listings_per_query: int
    periodic_scan_pages: int
    manual_search_pages: int
    manual_search_listings: int
    max_watch_queries: int
    signal_cooldown_sec: int

    # --- Defaults for new users ----------------------------------------------
    default_min_margin_pct: float
    default_budget_ton: float
    default_daily_budget_ton: float
    resale_discount_pct: float

    # --- Rates / HTTP ---------------------------------------------------------
    ton_rate_url: str
    ton_rate_ttl_sec: int
    http_timeout: float
    http_proxy: str

    # --- Portals --------------------------------------------------------------
    portals_api_url: str
    portals_webapp_url: str
    portals_buy_fee_pct: float
    portals_sell_fee_pct: float
    portals_withdraw_fee_ton: float

    # --- Tonnel ---------------------------------------------------------------
    tonnel_api_url: str
    tonnel_origin: str
    tonnel_buy_fee_pct: float
    tonnel_sell_fee_pct: float
    tonnel_withdraw_fee_ton: float

    # --- MRKT -----------------------------------------------------------------
    mrkt_api_base: str
    mrkt_token: str
    mrkt_init_data: str
    mrkt_bot_username: str
    mrkt_app_short_name: str
    mrkt_webapp_url: str
    mrkt_buy_fee_pct: float
    mrkt_sell_fee_pct: float
    mrkt_withdraw_fee_ton: float

    # --- Telegram user session (optional, MRKT initData refresh) --------------
    tg_api_id: int
    tg_api_hash: str
    tg_session_name: str
    init_data_ttl_sec: int

    log_level: str

    # --- Derived helpers ------------------------------------------------------

    def fees_for(self, market: str) -> Fees:
        key = market.lower()
        if key == "portals":
            return Fees("portals", self.portals_buy_fee_pct, self.portals_sell_fee_pct,
                        self.portals_withdraw_fee_ton)
        if key == "tonnel":
            return Fees("tonnel", self.tonnel_buy_fee_pct, self.tonnel_sell_fee_pct,
                        self.tonnel_withdraw_fee_ton)
        if key == "mrkt":
            return Fees("mrkt", self.mrkt_buy_fee_pct, self.mrkt_sell_fee_pct,
                        self.mrkt_withdraw_fee_ton)
        return Fees(key, 0.0, 0.0, 0.0)

    @property
    def all_fees(self) -> dict[str, Fees]:
        return {name: self.fees_for(name) for name in ("portals", "tonnel", "mrkt")}

    def local_hour(self) -> int:
        return (datetime.now(timezone.utc) + timedelta(hours=self.tz_offset_hours)).hour

    def is_night(self) -> bool:
        hour = self.local_hour()
        if self.night_start_hour <= self.night_end_hour:
            return self.night_start_hour <= hour < self.night_end_hour
        return hour >= self.night_start_hour or hour < self.night_end_hour

    def current_interval(self) -> int:
        """Never above three minutes, even in the quiet night window."""
        interval = self.night_interval_sec if self.is_night() else self.scan_interval_sec
        return max(30, min(180, interval))

    @property
    def mrkt_session_path(self) -> Path:
        return self.data_dir / self.tg_session_name

    @property
    def mrkt_configured(self) -> bool:
        return bool(self.mrkt_token or self.mrkt_init_data or (self.tg_api_id and self.tg_api_hash))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(_str("DATA_DIR", "data")).expanduser()
    db_path = Path(_str("DB_PATH", str(data_dir / "nftflip.sqlite3"))).expanduser()
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    if not db_path.is_absolute():
        db_path = ROOT / db_path

    return Settings(
        bot_token=_str("BOT_TOKEN"),
        allowed_user_ids=_ids("ALLOWED_USER_IDS"),
        admin_ids=_ids("ADMIN_IDS"),

        data_dir=data_dir,
        db_path=db_path,

        scan_interval_sec=_int("SCAN_INTERVAL_SEC", 120, low=30, high=180),
        night_interval_sec=_int("NIGHT_INTERVAL_SEC", 180, low=30, high=180),
        night_start_hour=_int("NIGHT_START_HOUR", 0, low=0, high=23),
        night_end_hour=_int("NIGHT_END_HOUR", 8, low=0, high=23),
        tz_offset_hours=_float("TZ_OFFSET_HOURS", 2.0),
        max_listings_per_query=_int("MAX_LISTINGS_PER_QUERY", 30, low=5, high=50),
        periodic_scan_pages=_int("PERIODIC_SCAN_PAGES", 2, low=1, high=10),
        manual_search_pages=_int("MANUAL_SEARCH_PAGES", 8, low=1, high=30),
        manual_search_listings=_int("MANUAL_SEARCH_LISTINGS", 50, low=5, high=50),
        max_watch_queries=_int("MAX_WATCH_QUERIES", 40, low=1, high=200),
        signal_cooldown_sec=_int("SIGNAL_COOLDOWN_SEC", 6 * 3600, low=60),

        default_min_margin_pct=_float("DEFAULT_MIN_MARGIN_PCT", 8.0, low=0.5),
        default_budget_ton=_float("DEFAULT_BUDGET_TON", 10.0, low=0.1),
        default_daily_budget_ton=_float("DEFAULT_DAILY_BUDGET_TON", 50.0, low=0.1),
        resale_discount_pct=_float("RESALE_DISCOUNT_PCT", 3.0, low=0.0),

        ton_rate_url=_str("TON_RATE_URL", "https://tonapi.io/v2/rates?tokens=ton&currencies=usd"),
        ton_rate_ttl_sec=_int("TON_RATE_TTL_SEC", 600, low=60),
        http_timeout=_float("HTTP_TIMEOUT", 15.0, low=3.0),
        http_proxy=_str("HTTP_PROXY"),

        portals_api_url=_str("PORTALS_API_URL", "https://portal-market.com/api").rstrip("/"),
        portals_webapp_url=_str("PORTALS_WEBAPP_URL", "https://portal-market.com").rstrip("/"),
        portals_buy_fee_pct=_float("PORTALS_BUY_FEE_PCT", 0.0, low=0.0),
        portals_sell_fee_pct=_float("PORTALS_SELL_FEE_PCT", 2.0, low=0.0),
        portals_withdraw_fee_ton=_float("PORTALS_WITHDRAW_FEE_TON", 0.0, low=0.0),

        tonnel_api_url=_str("TONNEL_API_URL", "https://gifts2.tonnel.network/api").rstrip("/"),
        tonnel_origin=_str("TONNEL_ORIGIN", "https://market.tonnel.network").rstrip("/"),
        tonnel_buy_fee_pct=_float("TONNEL_BUY_FEE_PCT", 0.5, low=0.0),
        tonnel_sell_fee_pct=_float("TONNEL_SELL_FEE_PCT", 0.5, low=0.0),
        tonnel_withdraw_fee_ton=_float("TONNEL_WITHDRAW_FEE_TON", 0.0, low=0.0),

        mrkt_api_base=_str("MRKT_API_BASE", "https://api.tgmrkt.io/api/v1").rstrip("/"),
        mrkt_token=_str("MRKT_TOKEN"),
        mrkt_init_data=_str("MRKT_INIT_DATA"),
        mrkt_bot_username=_str("MRKT_BOT_USERNAME", "mrkt"),
        mrkt_app_short_name=_str("MRKT_APP_SHORT_NAME", "app"),
        mrkt_webapp_url=_str("MRKT_WEBAPP_URL", "https://cdn.tgmrkt.io/"),
        mrkt_buy_fee_pct=_float("MRKT_BUY_FEE_PCT", 0.0, low=0.0),
        mrkt_sell_fee_pct=_float("MRKT_SELL_FEE_PCT", 0.0, low=0.0),
        mrkt_withdraw_fee_ton=_float("MRKT_WITHDRAW_FEE_TON", 0.17, low=0.0),

        tg_api_id=_int("TG_API_ID", 0, low=0),
        tg_api_hash=_str("TG_API_HASH"),
        tg_session_name=_str("TG_SESSION_NAME", "mrkt"),
        init_data_ttl_sec=_int("INIT_DATA_TTL", 1800, low=60),

        log_level=_str("LOG_LEVEL", "INFO").upper(),
    )
