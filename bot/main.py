"""Bot bootstrap: build the stack, start the scanner and poll Telegram."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from adapters import MrktAdapter, PortalsAdapter, TonnelAdapter
from bot.context import AppContext
from bot.delivery import send_offer_card
from bot.handlers import router
from bot.middleware import AccessMiddleware, ContextMiddleware
from config import Settings, get_settings
from db.database import Database
from services.rates import TonRate
from services.scanner import Scanner

log = logging.getLogger(__name__)


def configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)


def build_adapters(settings: Settings) -> dict:
    return {
        "portals": PortalsAdapter(settings),
        "tonnel": TonnelAdapter(settings),
        "mrkt": MrktAdapter(settings),
    }


async def run_bot(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_logging(settings)

    if not settings.bot_token:
        raise SystemExit(
            "BOT_TOKEN is empty. Put the token from @BotFather into .env "
            "(copy .env.example to .env first)."
        )

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_path)
    await db.init()

    adapters = build_adapters(settings)
    scanner = Scanner(settings, db, adapters)
    rates = TonRate(settings)
    ctx = AppContext(settings=settings, db=db, scanner=scanner, rates=rates)

    bot = Bot(settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dispatcher = Dispatcher(storage=MemoryStorage())

    dispatcher.message.middleware(AccessMiddleware(settings.allowed_user_ids))
    dispatcher.callback_query.middleware(AccessMiddleware(settings.allowed_user_ids))
    dispatcher.message.middleware(ContextMiddleware(ctx))
    dispatcher.callback_query.middleware(ContextMiddleware(ctx))
    dispatcher.include_router(router)

    async def on_offer(tg_id: int, offer, user: dict) -> None:
        await send_offer_card(
            bot,
            tg_id,
            offer,
            display=user.get("display_currency") or "both",
            rate=await rates.get(),
            discount_pct=settings.resale_discount_pct,
        )

    scanner.on_offer = on_offer

    commands = [
        BotCommand(command="start", description="Головне меню"),
        BotCommand(command="search", description="Почати пошук вигідних пропозицій"),
        BotCommand(command="add", description="Додати колекцію/модель"),
        BotCommand(command="watch", description="Мої підписки"),
        BotCommand(command="del", description="Видалити підписку"),
        BotCommand(command="budget", description="Бюджет на угоду"),
        BotCommand(command="daily", description="Денний ліміт"),
        BotCommand(command="threshold", description="Мінімальна маржа"),
        BotCommand(command="calc", description="Калькулятор прибутку"),
        BotCommand(command="deals", description="Останні сигнали"),
        BotCommand(command="status", description="Стан сканера"),
        BotCommand(command="settings", description="Налаштування"),
        BotCommand(command="pause", description="Вимкнути сигнали"),
        BotCommand(command="resume", description="Увімкнути сигнали"),
        BotCommand(command="fees", description="Комісії майданчиків"),
        BotCommand(command="scan", description="Ручний скан (адмін)"),
        BotCommand(command="help", description="Допомога"),
    ]

    await scanner.start()
    try:
        me = await bot.get_me()
        log.info("Bot @%s is running", me.username)
        try:
            await bot.set_my_commands(commands)
        except Exception as exc:  # noqa: BLE001 - cosmetic, not fatal
            log.warning("Could not set bot commands: %s", exc)
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
            drop_pending_updates=True,
        )
    finally:
        log.info("Shutting down…")
        await scanner.stop()
        await db.close()
        await bot.session.close()
