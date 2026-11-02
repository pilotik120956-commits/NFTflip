"""Telegram Mini App initData via Telethon (only needed for automatic MRKT auth).

The session file is created by:  python run.py login
"""

from __future__ import annotations

import logging
import time
from urllib.parse import unquote

from config import Settings

log = logging.getLogger(__name__)


def mask(secret: str | None, keep: int = 8) -> str:
    if not secret:
        return "<empty>"
    if len(secret) <= keep:
        return "***"
    return f"{secret[:keep]}...({len(secret)} chars)"


def extract_tg_web_app_data(url: str) -> str:
    """Pull tgWebAppData out of a Mini App URL and unquote it once."""
    marker = "tgWebAppData="
    index = url.find(marker)
    if index == -1:
        raise RuntimeError("tgWebAppData not found in the web app URL")
    value = url[index + len(marker):]
    value = value.split("&", 1)[0]
    data = unquote(value)
    if "hash=" not in data:
        raise RuntimeError("tgWebAppData does not look like initData (no hash)")
    return data


class TelegramSession:
    """One shared, lazily connected Telethon client."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.settings.tg_api_id and self.settings.tg_api_hash)

    async def client(self):
        if not self.configured:
            raise RuntimeError("TG_API_ID / TG_API_HASH are not set in .env")
        try:
            from telethon import TelegramClient
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("telethon is not installed: pip install -r requirements.txt") from exc

        if self._client is None:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            self._client = TelegramClient(
                str(self.settings.mrkt_session_path),
                self.settings.tg_api_id,
                self.settings.tg_api_hash,
            )
        if not self._client.is_connected():
            await self._client.connect()
        if not await self._client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorised. Run: python run.py login "
                f"(session: {self.settings.mrkt_session_path}.session)"
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None


async def request_init_data(settings: Settings, session: TelegramSession | None = None) -> str:
    """Open the MRKT Mini App with the logged-in account and return initData."""
    from telethon import functions, types, utils

    own = session is None
    session = session or TelegramSession(settings)
    client = await session.client()
    try:
        peer = await client.get_input_entity(settings.mrkt_bot_username)
        try:
            result = await client(
                functions.messages.RequestAppWebViewRequest(
                    peer=peer,
                    app=types.InputBotAppShortName(
                        bot_id=utils.get_input_user(peer),
                        short_name=settings.mrkt_app_short_name,
                    ),
                    platform="android",
                    write_allowed=True,
                )
            )
        except Exception as exc:  # noqa: BLE001 - fall back to the plain web view
            log.warning("RequestAppWebView failed (%s), falling back to RequestWebView", exc)
            result = await client(
                functions.messages.RequestWebViewRequest(
                    peer=peer,
                    bot=utils.get_input_user(peer),
                    platform="android",
                    url=settings.mrkt_webapp_url,
                    from_bot_menu=False,
                )
            )
        init_data = extract_tg_web_app_data(result.url)
        log.info("Got MRKT initData %s", mask(init_data, 16))
        return init_data
    finally:
        if own:
            await session.close()


class InitDataProvider:
    """Cache initData and refresh it after INIT_DATA_TTL or on demand."""

    def __init__(self, settings: Settings, session: TelegramSession | None = None) -> None:
        self.settings = settings
        self.session = session
        self._value: str | None = None
        self._fetched_at = 0.0

    async def get(self, force: bool = False) -> str:
        fresh = self._value is not None and (time.monotonic() - self._fetched_at) < self.settings.init_data_ttl_sec
        if force or not fresh:
            self._value = await request_init_data(self.settings, self.session)
            self._fetched_at = time.monotonic()
        assert self._value is not None
        return self._value


async def interactive_login(settings: Settings) -> None:
    """First-time phone/code/2FA login; stores data/<TG_SESSION_NAME>.session."""
    try:
        from telethon import TelegramClient
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("telethon is not installed: pip install -r requirements.txt") from exc

    if not settings.tg_api_id or not settings.tg_api_hash:
        raise RuntimeError("Set TG_API_ID and TG_API_HASH in .env first (https://my.telegram.org).")

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(
        str(settings.mrkt_session_path), settings.tg_api_id, settings.tg_api_hash
    )
    await client.start()  # prompts for phone, code and password in the terminal
    me = await client.get_me()
    print(f"Logged in as {getattr(me, 'username', None) or me.id}")
    print(f"Session file: {settings.mrkt_session_path}.session")
    await client.disconnect()
