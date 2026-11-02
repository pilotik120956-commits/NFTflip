"""Inline and reply keyboards."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from models import Offer, market_name

BTN_SEARCH = "🚀 Почати пошук"
BTN_STATUS = "📊 Статус"
BTN_BUDGET = "💰 Бюджет"
BTN_CALC = "🧮 Калькулятор"
BTN_WATCH = "👀 Підписки"
BTN_SETTINGS = "⚙️ Налаштування"
BTN_HELP = "❓ Допомога"


def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_SEARCH)],
            [KeyboardButton(text=BTN_STATUS), KeyboardButton(text=BTN_BUDGET)],
            [KeyboardButton(text=BTN_CALC), KeyboardButton(text=BTN_WATCH)],
            [KeyboardButton(text=BTN_SETTINGS), KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Оберіть дію або введіть команду",
    )


def main_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Почати пошук", callback_data="menu:search")],
            [
                InlineKeyboardButton(text="📊 Статус", callback_data="menu:status"),
                InlineKeyboardButton(text="👀 Підписки", callback_data="menu:watch"),
            ],
            [
                InlineKeyboardButton(text="🧮 Калькулятор", callback_data="menu:calc"),
                InlineKeyboardButton(text="📈 Останні сигнали", callback_data="menu:deals"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Налаштування", callback_data="menu:settings"),
                InlineKeyboardButton(text="💸 Комісії", callback_data="menu:fees"),
            ],
            [InlineKeyboardButton(text="❓ Допомога", callback_data="menu:help")],
        ]
    )


def _mark(label: str, active: bool) -> str:
    return f"✅ {label}" if active else label


def budget_kb(current: float) -> InlineKeyboardMarkup:
    values = [5, 10, 25, 50, 100]
    row = [
        InlineKeyboardButton(
            text=_mark(f"{value}", abs(current - value) < 0.001),
            callback_data=f"bud:{value}",
        )
        for value in values
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[row, [InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]]
    )


def threshold_kb(current: float) -> InlineKeyboardMarkup:
    values = [5, 8, 10, 15, 20]
    row = [
        InlineKeyboardButton(
            text=_mark(f"{value}%", abs(current - value) < 0.001),
            callback_data=f"thr:{value}",
        )
        for value in values
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[row, [InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]]
    )


def settings_kb(user: dict) -> InlineKeyboardMarkup:
    currency = user.get("display_currency") or "both"
    alerts = bool(int(user.get("alerts_enabled") or 0))
    budget = float(user.get("budget_ton") or 0)
    threshold = float(user.get("min_margin_pct") or 0)
    budget_row = [
        InlineKeyboardButton(text=_mark(f"{v}", abs(budget - v) < 0.001), callback_data=f"bud:{v}")
        for v in (5, 10, 25, 50)
    ]
    threshold_row = [
        InlineKeyboardButton(text=_mark(f"{v}%", abs(threshold - v) < 0.001), callback_data=f"thr:{v}")
        for v in (5, 8, 10, 15)
    ]
    currency_row = [
        InlineKeyboardButton(text=_mark("TON+USD", currency == "both"), callback_data="cur:both"),
        InlineKeyboardButton(text=_mark("TON", currency == "ton"), callback_data="cur:ton"),
        InlineKeyboardButton(text=_mark("USD", currency == "usd"), callback_data="cur:usd"),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Бюджет на угоду, TON:", callback_data="noop")],
            budget_row,
            [InlineKeyboardButton(text="Мінімальна маржа:", callback_data="noop")],
            threshold_row,
            currency_row,
            [InlineKeyboardButton(text=f"🔔 Сигнали: {'увімкнено' if alerts else 'вимкнено'}",
                                  callback_data="alerts:toggle")],
            [
                InlineKeyboardButton(text="💸 Комісії", callback_data="menu:fees"),
                InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main"),
            ],
        ]
    )


def watch_kb(rows: list[dict]) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    for row in rows[:20]:
        label = row["collection"] + (f" · {row['model']}" if row.get("model") else " · всі")
        keyboard.append([
            InlineKeyboardButton(text=f"🗑 {label}"[:60], callback_data=f"watch:del:{row['id']}")
        ])
    keyboard.append([
        InlineKeyboardButton(text="➕ Додати підписку", callback_data="watch:add"),
        InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def calc_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="✖️ Скасувати", callback_data="calc:cancel")]]
    )


def offer_kb(offer: Offer) -> InlineKeyboardMarkup:
    keyboard: list[list[InlineKeyboardButton]] = []
    if offer.buy_url:
        keyboard.append([
            InlineKeyboardButton(
                text=f"🛒 Купити на {market_name(offer.buy.market)}",
                url=offer.buy_url,
            )
        ])
    tg_page = offer.buy.tg_url
    if tg_page and tg_page != offer.buy_url:
        keyboard.append([InlineKeyboardButton(text="🎁 Сторінка подарунка", url=tg_page)])
    buy_thousandths = int(round(offer.buy.price_ton * 1000))
    sell_thousandths = int(round(offer.est_sale * 1000))
    code = {"portals": "p", "tonnel": "t", "mrkt": "m"}.get(offer.buy.market, "p")
    keyboard.append([
        InlineKeyboardButton(
            text="🧮 Перерахувати",
            callback_data=f"c1:{buy_thousandths}:{sell_thousandths}:{code}",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Меню", callback_data="menu:main")]]
    )
