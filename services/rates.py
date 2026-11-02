"""Keyless TON -> USD rate with caching. Failures never block a scan."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from config import Settings

log = logging.getLogger(__name__)


def parse_tonapi_rate(data: Any, currency: str = "USD") -> float | None:
    """{"rates":{"TON":{"prices":{"USD":1.246}}}} -> 1.246."""
    try:
        value = float(data["rates"]["TON"]["prices"][currency.upper()])
    except (KeyError, TypeError, ValueError):
        return None
    return value if value > 0 else None


class TonRate:
    def __init__(self, settings: Settings) -> None:
        self.url = settings.ton_rate_url
        self.ttl = settings.ton_rate_ttl_sec
        self.proxy = settings.http_proxy or None
        self._value: float | None = None
        self._fetched_at = 0.0
        self._lock = asyncio.Lock()
        self.last_error: str | None = None

    async def get(self) -> float | None:
        if self._value is not None and time.monotonic() - self._fetched_at < self.ttl:
            return self._value
        async with self._lock:
            if self._value is not None and time.monotonic() - self._fetched_at < self.ttl:
                return self._value
            try:
                async with httpx.AsyncClient(timeout=10.0, proxy=self.proxy) as client:
                    response = await client.get(self.url)
                    response.raise_for_status()
                    value = parse_tonapi_rate(response.json())
                if value is not None:
                    self._value = value
                    self._fetched_at = time.monotonic()
                    self.last_error = None
            except Exception as exc:  # noqa: BLE001 - a stale rate is better than no bot
                self.last_error = f"{type(exc).__name__}: {exc}"
                log.debug("TON rate refresh failed: %s", self.last_error)
            return self._value
