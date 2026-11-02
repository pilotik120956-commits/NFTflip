"""aiogram middlewares: access control and context injection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.context import AppContext


class AccessMiddleware(BaseMiddleware):
    def __init__(self, allowed: frozenset[int]) -> None:
        self.allowed = allowed

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self.allowed:
            user = getattr(event, "from_user", None)
            if user is None or user.id not in self.allowed:
                if isinstance(event, CallbackQuery):
                    await event.answer("⛔️ Немає доступу", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer("⛔️ Немає доступу до цього бота.")
                return None
        return await handler(event, data)


class ContextMiddleware(BaseMiddleware):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["ctx"] = self.ctx
        return await handler(event, data)
