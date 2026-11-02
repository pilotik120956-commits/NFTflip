"""Shared HTTP transport, throttling and errors for the marketplace adapters."""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from config import Settings
from models import Listing


class MarketError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status


class MarketRateLimited(MarketError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(429, message)
        self.retry_after = retry_after


class MarketAuthError(MarketError):
    pass


@dataclass(slots=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    text: str

    def json(self) -> Any:
        try:
            return json.loads(self.text) if self.text else None
        except ValueError as exc:
            raise MarketError(self.status, f"non-JSON response: {self.text[:200]}") from exc


class HttpClient:
    """curl_cffi (Chrome TLS, useful behind Cloudflare) with an httpx fallback."""

    def __init__(self, timeout: float, proxy: str = "") -> None:
        self.timeout = timeout
        self.proxy = proxy or None
        self.kind = "uninitialised"
        self._client: Any = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> None:
        if self._client is not None:
            return
        async with self._lock:
            if self._client is not None:
                return
            try:
                from curl_cffi.requests import AsyncSession

                self._client = AsyncSession(impersonate="chrome", timeout=self.timeout, proxy=self.proxy)
                self.kind = "curl_cffi"
            except ImportError:  # pragma: no cover - depends on the machine
                import httpx

                self._client = httpx.AsyncClient(
                    timeout=self.timeout,
                    proxy=self.proxy,
                    follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                           "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"},
                )
                self.kind = "httpx"

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Any = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
    ) -> HttpResponse:
        await self._ensure()
        try:
            response = await self._client.request(
                method, url, params=params, json=json, headers=headers or {}
            )
        except Exception as exc:  # network/TLS/timeout from either backend
            raise MarketError(0, f"network error: {type(exc).__name__}: {exc}") from exc
        return HttpResponse(
            status=int(response.status_code),
            headers={k.lower(): v for k, v in dict(response.headers).items()},
            text=response.text or "",
        )

    async def close(self) -> None:
        if self._client is None:
            return
        if self.kind == "curl_cffi":
            await self._client.close()
        else:
            await self._client.aclose()
        self._client = None


class BaseAdapter(ABC):
    name = "base"
    display_name = "Base"
    min_interval_sec = 0.0

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = HttpClient(settings.http_timeout, settings.http_proxy)
        self._next_slot = 0.0
        self._throttle = asyncio.Lock()

    async def _wait_slot(self) -> None:
        if self.min_interval_sec <= 0:
            return
        async with self._throttle:
            delay = self._next_slot - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_slot = time.monotonic() + self.min_interval_sec

    @property
    def enabled(self) -> bool:
        """False when the market needs credentials that are not configured yet."""
        return True

    @abstractmethod
    async def search(self, collection: str, model: str | None = None, limit: int = 30) -> list[Listing]:
        raise NotImplementedError

    async def collections(self) -> list[str]:
        return []

    async def close(self) -> None:
        await self.http.close()

    @staticmethod
    def user_agent() -> str:
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        )


def to_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
