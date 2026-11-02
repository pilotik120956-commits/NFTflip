"""All Telegram commands, buttons and the interactive calculator."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, User

from bot.context import AppContext
from bot.formatting import (
    calc_text,
    esc,
    fees_text,
    help_text,
    offer_text,
    report_text,
    settings_text,
    signal_row_text,
    status_text,
    watch_text,
)
from bot.keyboards import (
    BTN_BUDGET,
    BTN_CALC,
    BTN_HELP,
    BTN_SETTINGS,
    BTN_STATUS,
    BTN_WATCH,
    back_kb,
    budget_kb,
    calc_cancel_kb,
    main_inline_kb,
    main_menu_kb,
    settings_kb,
    threshold_kb,
    watch_kb,
)
from core.calculator import fmt_ton
from models import market_name

log = logging.getLogger(__name__)
router = Router(name="nftflip")
MARKETS = ("portals", "tonnel", "mrkt")


class CalcFlow(StatesGroup):
    buy = State()
    sell = State()


# --- helpers ------------------------------------------------------------------


async def _ensure_user(ctx: AppContext, tg: User | None) -> dict:
    if tg is None:
        return {}
    return await ctx.db.add_user(
        tg.id,
        tg.username,
        tg.first_name,
        budget_ton=ctx.settings.default_budget_ton,
        daily_budget_ton=ctx.settings.default_daily_budget_ton,
        min_margin_pct=ctx.settings.default_min_margin_pct,
    )


def _uid(message: Message) -> int:
    return message.from_user.id if message.from_user else 0


def _parse_positive(text: str) -> float | None:
    try:
        value = float(text.strip().replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _split_watch(raw: str) -> tuple[str, str | None]:
    raw = raw.strip().strip('"').strip()
    if "|" in raw:
        collection, model = raw.split("|", 1)
    else:
        collection, model = raw, ""
    return " ".join(collection.split()), (" ".join(model.split()) or None)


async def _respond(cb: CallbackQuery, text: str, kb=None, *, edit: bool = True) -> None:
    if edit and isinstance(cb.message, Message):
        try:
            await cb.message.edit_text(text, reply_markup=kb)
            return
        except Exception:  # noqa: BLE001 - message may be too old or identical
            pass
    await cb.bot.send_message(cb.from_user.id, text, reply_markup=kb)


async def _send_status(target: Message | CallbackQuery, ctx: AppContext, *, edit: bool = False) -> None:
    counts = await ctx.db.counts()
    health = await ctx.db.get_health()
    text = status_text(ctx.scanner.last_report, health, counts, ctx.settings)
    if isinstance(target, CallbackQuery):
        await _respond(target, text, back_kb(), edit=edit)
    else:
        await target.answer(text, reply_markup=back_kb())


async def _send_watch(target: Message | CallbackQuery, ctx: AppContext, tg_id: int, *, edit: bool = False) -> None:
    rows = await ctx.db.list_watch(tg_id)
    text = watch_text(rows)
    kb = watch_kb(rows)
    if isinstance(target, CallbackQuery):
        await _respond(target, text, kb, edit=edit)
    else:
        await target.answer(text, reply_markup=kb)


async def _send_settings(target: Message | CallbackQuery, ctx: AppContext, tg: User | None, *, edit: bool = False) -> None:
    user = await _ensure_user(ctx, tg)
    text = settings_text(user, ctx.settings)
    kb = settings_kb(user)
    if isinstance(target, CallbackQuery):
        await _respond(target, text, kb, edit=edit)
    else:
        await target.answer(text, reply_markup=kb)


async def _send_budget(target: Message | CallbackQuery, ctx: AppContext, tg: User | None, *, edit: bool = False) -> None:
    user = await _ensure_user(ctx, tg)
    current = float(user.get("budget_ton") or 0)
    text = (
        "💰 <b>Бюджет на одну угоду</b>\n\n"
        f"Зараз: <b>{fmt_ton(current)} TON</b>\n\n"
        "Бот надсилає лише ті сигнали, де повна вартість покупки (з комісією) "
        "не перевищує цей бюджет.\n\n"
        "Точне значення: <code>/budget 12.5</code>"
    )
    if isinstance(target, CallbackQuery):
        await _respond(target, text, budget_kb(current), edit=edit)
    else:
        await target.answer(text, reply_markup=budget_kb(current))


async def _send_threshold(target: Message | CallbackQuery, ctx: AppContext, tg: User | None, *, edit: bool = False) -> None:
    user = await _ensure_user(ctx, tg)
    current = float(user.get("min_margin_pct") or 0)
    text = (
        "🎯 <b>Мінімальна маржа</b>\n\n"
        f"Зараз: <b>{current:g}%</b>\n\n"
        "Сигнал надсилається, якщо чистий прибуток після комісій становить "
        "хоча б цей відсоток від суми продажу.\n\n"
        "Точне значення: <code>/threshold 7.5</code>"
    )
    if isinstance(target, CallbackQuery):
        await _respond(target, text, threshold_kb(current), edit=edit)
    else:
        await target.answer(text, reply_markup=threshold_kb(current))


async def _send_deals(target: Message | CallbackQuery, ctx: AppContext, tg: User | None, *, edit: bool = False) -> None:
    user = await _ensure_user(ctx, tg)
    tg_id = tg.id if tg else 0
    rows = await ctx.db.recent_signals(tg_id, 10)
    if not rows:
        text = (
            "📈 <b>Останні сигнали</b>\n\n"
            "Поки що порожньо. Додайте підписку: <code>/add Durov's Cap</code> — "
            "і бот почне порівнювати ціни."
        )
    else:
        rate = await ctx.rates.get()
        display = user.get("display_currency") or "both"
        text = "📈 <b>Останні сигнали</b>\n\n" + "\n\n".join(
            signal_row_text(row, rate, display) for row in rows
        )
    if isinstance(target, CallbackQuery):
        await _respond(target, text, back_kb(), edit=edit)
    else:
        await target.answer(text, reply_markup=back_kb())


# --- commands -----------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    name = esc(message.from_user.first_name) if message.from_user and message.from_user.first_name else ""
    greeting = f"👋 <b>Вітаю, {name}!</b>\n\n" if name else "👋 <b>Вітаю!</b>\n\n"
    await message.answer(
        greeting
        + "Я слідкую за <b>Portals</b>, <b>Tonnel</b> і <b>MRKT</b>, порівнюю ціни на "
        "однакові Telegram-подарунки та надсилаю сигнали, коли на одному майданчику "
        "дешевше, ніж на інших.\n\n"
        "<b>З чого почати:</b>\n"
        "1️⃣ <code>/add Durov's Cap</code> — додайте колекцію\n"
        "2️⃣ <code>/budget 15</code> — вкажіть бюджет на угоду\n"
        "3️⃣ <code>/threshold 8</code> — мінімальна маржа\n\n"
        "Кнопки нижче дублюють основні дії.",
        reply_markup=main_menu_kb(),
    )
    await message.answer("Головне меню:", reply_markup=main_inline_kb())


@router.message(Command("help"))
async def cmd_help(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await message.answer(help_text(), reply_markup=main_menu_kb())


@router.message(Command("menu"))
async def cmd_menu(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await message.answer("Головне меню:", reply_markup=main_inline_kb())


@router.message(Command("add"))
async def cmd_add(message: Message, command: CommandObject, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(
            "➕ <b>Додати підписку</b>\n\n"
            "Колекція:\n<code>/add Durov's Cap</code>\n\n"
            "Колекція + модель:\n<code>/add Toy Bear | Wizard</code>\n\n"
            "Назву колекції беріть такою, як вона показана на майданчику. "
            "Регістр не важливий, суфікс редкості на кшталт <code>(1.5%)</code> можна не писати.",
            reply_markup=back_kb(),
        )
        return
    collection, model = _split_watch(raw)
    if not collection or len(collection) > 80 or (model and len(model) > 80):
        await message.answer("⚠️ Назва колекції або моделі порожня/задовга (максимум 80 символів).")
        return

    added, _watch_id = await ctx.db.add_watch(_uid(message), collection, model)
    known_on_portals: bool | None = None
    portals = ctx.scanner.adapters.get("portals")
    if portals is not None:
        try:
            known_on_portals = await portals.has_collection(collection)
        except Exception:  # noqa: BLE001 - network hiccup must not block adding
            known_on_portals = None

    label = f"<b>{esc(collection)}</b>"
    if model:
        label += f" — модель <b>{esc(model)}</b>"
    else:
        label += " — всі моделі"

    if added:
        text = f"✅ Додано підписку: {label}\n\nБот перевірить її в наступному циклі."
    else:
        text = f"ℹ️ Така підписка вже є: {label}"
    if known_on_portals is False:
        text += (
            "\n\n⚠️ На Portals колекцію з такою назвою не знайдено. "
            "Якщо це нормально для вашого випадку — залиште; інакше перевірте написання."
        )
    await message.answer(text, reply_markup=back_kb())


@router.message(Command("watch"))
async def cmd_watch(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await _send_watch(message, ctx, _uid(message))


@router.message(Command("del", "remove"))
async def cmd_del(message: Message, command: CommandObject, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    raw = (command.args or "").strip()
    if not raw:
        await message.answer("Вкажіть номер підписки з /watch або назву: <code>/del 3</code>")
        return
    uid = _uid(message)
    removed = 0
    if raw.isdigit():
        removed = int(await ctx.db.remove_watch(uid, int(raw)))
        if removed == 0:
            await message.answer("⚠️ Підписку з таким номером не знайдено. Відкрийте /watch.")
            return
    else:
        collection, model = _split_watch(raw)
        removed = await ctx.db.remove_watch_by_name(uid, collection, model)
    if removed:
        await message.answer(f"🗑 Видалено підписок: <b>{removed}</b>.", reply_markup=back_kb())
        await _send_watch(message, ctx, uid)
    else:
        await message.answer("⚠️ Нічого не видалено — перевірте назву або номер у /watch.")


@router.message(Command("budget"))
async def cmd_budget(message: Message, command: CommandObject, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    raw = (command.args or "").strip()
    if not raw:
        await _send_budget(message, ctx, message.from_user)
        return
    value = _parse_positive(raw)
    if value is None:
        await message.answer("⚠️ Вкажіть додатне число, наприклад <code>/budget 12.5</code>")
        return
    await ctx.db.update_user(_uid(message), budget_ton=value)
    await message.answer(
        f"✅ Бюджет на одну угоду: <b>{fmt_ton(value)} TON</b>", reply_markup=back_kb()
    )


@router.message(Command("daily"))
async def cmd_daily(message: Message, command: CommandObject, ctx: AppContext) -> None:
    user = await _ensure_user(ctx, message.from_user)
    raw = (command.args or "").strip()
    if not raw:
        await message.answer(
            "📅 <b>Денний ліміт</b>\n\n"
            f"Зараз: <b>{fmt_ton(float(user.get('daily_budget_ton') or 0))} TON</b>\n\n"
            "Це сумарна вартість сигналів, які бот надішле вам за UTC-добу. "
            "Змінити: <code>/daily 100</code>",
            reply_markup=back_kb(),
        )
        return
    value = _parse_positive(raw)
    if value is None:
        await message.answer("⚠️ Вкажіть додатне число, наприклад <code>/daily 100</code>")
        return
    await ctx.db.update_user(_uid(message), daily_budget_ton=value)
    await message.answer(
        f"✅ Денний ліміт: <b>{fmt_ton(value)} TON</b>", reply_markup=back_kb()
    )


@router.message(Command("threshold", "margin"))
async def cmd_threshold(message: Message, command: CommandObject, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    raw = (command.args or "").strip()
    if not raw:
        await _send_threshold(message, ctx, message.from_user)
        return
    value = _parse_positive(raw)
    if value is None or value > 100:
        await message.answer("⚠️ Вкажіть відсоток від 0.1 до 100, наприклад <code>/threshold 8</code>")
        return
    await ctx.db.update_user(_uid(message), min_margin_pct=value)
    await message.answer(
        f"✅ Мінімальна маржа: <b>{value:g}%</b>", reply_markup=back_kb()
    )


@router.message(Command("calc"))
async def cmd_calc(
    message: Message, command: CommandObject, state: FSMContext, ctx: AppContext
) -> None:
    await _ensure_user(ctx, message.from_user)
    raw = (command.args or "").strip()
    if not raw:
        await state.set_state(CalcFlow.buy)
        await message.answer(
            "🧮 <b>Калькулятор</b>\n\n"
            "Крок 1/2. Введіть ціну купівлі в TON (наприклад <code>5.5</code>).\n"
            "Команда <code>/cancel</code> — скасувати.",
            reply_markup=calc_cancel_kb(),
        )
        return

    parts = raw.replace(",", ".").split()
    if len(parts) < 2:
        await message.answer(
            "Формат: <code>/calc &lt;купівля&gt; &lt;продаж&gt; [portals|tonnel|mrkt]</code>\n"
            "Наприклад: <code>/calc 5 7</code>"
        )
        return
    buy = _parse_positive(parts[0])
    sell = _parse_positive(parts[1])
    if buy is None or sell is None:
        await message.answer("⚠️ Обидві ціни мають бути додатними числами.")
        return
    buy_market = parts[2].lower() if len(parts) > 2 else "portals"
    if buy_market not in MARKETS:
        buy_market = "portals"
    user = await ctx.db.get_user(_uid(message)) or {}
    rate = await ctx.rates.get()
    await message.answer(
        calc_text(
            buy,
            sell,
            ctx.settings,
            display=user.get("display_currency") or "both",
            rate=rate,
            buy_market=buy_market,
        ),
        reply_markup=back_kb(),
    )


@router.message(CalcFlow.buy, F.text, ~F.text.startswith("/"))
async def calc_buy(message: Message, state: FSMContext, ctx: AppContext) -> None:
    value = _parse_positive(message.text or "")
    if value is None:
        await message.answer("⚠️ Введіть додатне число, наприклад <code>5.5</code>.")
        return
    await state.update_data(buy=value)
    await state.set_state(CalcFlow.sell)
    await message.answer(
        "🧮 Крок 2/2. Введіть очікувану ціну продажу в TON:",
        reply_markup=calc_cancel_kb(),
    )


@router.message(CalcFlow.sell, F.text, ~F.text.startswith("/"))
async def calc_sell(message: Message, state: FSMContext, ctx: AppContext) -> None:
    value = _parse_positive(message.text or "")
    if value is None:
        await message.answer("⚠️ Введіть додатне число, наприклад <code>7</code>.")
        return
    data = await state.get_data()
    buy = float(data.get("buy") or 0)
    await state.clear()
    user = await ctx.db.get_user(_uid(message)) or {}
    rate = await ctx.rates.get()
    await message.answer(
        calc_text(
            buy,
            value,
            ctx.settings,
            display=user.get("display_currency") or "both",
            rate=rate,
        ),
        reply_markup=back_kb(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Скасовано.", reply_markup=main_menu_kb())


@router.message(Command("settings"))
async def cmd_settings(message: Message, ctx: AppContext) -> None:
    await _send_settings(message, ctx, message.from_user)


@router.message(Command("fees"))
async def cmd_fees(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await message.answer(fees_text(ctx.settings), reply_markup=back_kb())


@router.message(Command("status"))
async def cmd_status(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await _send_status(message, ctx)


@router.message(Command("deals"))
async def cmd_deals(message: Message, ctx: AppContext) -> None:
    await _send_deals(message, ctx, message.from_user)


@router.message(Command("pause"))
async def cmd_pause(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await ctx.db.update_user(_uid(message), alerts_enabled=0)
    await message.answer("🔕 Сигнали вимкнено. Увімкнути: /resume", reply_markup=back_kb())


@router.message(Command("resume"))
async def cmd_resume(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await ctx.db.update_user(_uid(message), alerts_enabled=1)
    await message.answer("🔔 Сигнали увімкнено.", reply_markup=back_kb())


@router.message(Command("scan"))
async def cmd_scan(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    if ctx.settings.admin_ids and _uid(message) not in ctx.settings.admin_ids:
        await message.answer("⛔️ Ручний скан доступний лише адміністратору.")
        return
    await message.answer("🔍 Сканую просто зараз…")
    report, _offers = await ctx.scanner.scan_once()
    await message.answer(report_text(report), reply_markup=back_kb())


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"Ваш Telegram ID: <code>{_uid(message)}</code>")


# --- reply-keyboard buttons ---------------------------------------------------


@router.message(StateFilter(None), F.text == BTN_STATUS)
async def btn_status(message: Message, ctx: AppContext) -> None:
    await _send_status(message, ctx)


@router.message(StateFilter(None), F.text == BTN_BUDGET)
async def btn_budget(message: Message, ctx: AppContext) -> None:
    await _send_budget(message, ctx, message.from_user)


@router.message(StateFilter(None), F.text == BTN_CALC)
async def btn_calc(message: Message, state: FSMContext, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await state.set_state(CalcFlow.buy)
    await message.answer(
        "🧮 Крок 1/2. Введіть ціну купівлі в TON (наприклад <code>5.5</code>).",
        reply_markup=calc_cancel_kb(),
    )


@router.message(StateFilter(None), F.text == BTN_WATCH)
async def btn_watch(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await _send_watch(message, ctx, _uid(message))


@router.message(StateFilter(None), F.text == BTN_SETTINGS)
async def btn_settings(message: Message, ctx: AppContext) -> None:
    await _send_settings(message, ctx, message.from_user)


@router.message(StateFilter(None), F.text == BTN_HELP)
async def btn_help(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await message.answer(help_text(), reply_markup=main_menu_kb())


# --- inline callbacks ---------------------------------------------------------


@router.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query(F.data == "menu:main")
async def cb_main(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    await _respond(cb, "Головне меню:", main_inline_kb())
    await cb.answer()


@router.callback_query(F.data == "menu:help")
async def cb_help(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    await _respond(cb, help_text(), back_kb())
    await cb.answer()


@router.callback_query(F.data == "menu:status")
async def cb_status(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    await _send_status(cb, ctx, edit=True)
    await cb.answer()


@router.callback_query(F.data == "menu:watch")
async def cb_watch(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    await _send_watch(cb, ctx, cb.from_user.id, edit=True)
    await cb.answer()


@router.callback_query(F.data == "menu:settings")
async def cb_settings(cb: CallbackQuery, ctx: AppContext) -> None:
    await _send_settings(cb, ctx, cb.from_user, edit=True)
    await cb.answer()


@router.callback_query(F.data == "menu:budget")
async def cb_budget(cb: CallbackQuery, ctx: AppContext) -> None:
    await _send_budget(cb, ctx, cb.from_user, edit=True)
    await cb.answer()


@router.callback_query(F.data == "menu:threshold")
async def cb_threshold(cb: CallbackQuery, ctx: AppContext) -> None:
    await _send_threshold(cb, ctx, cb.from_user, edit=True)
    await cb.answer()


@router.callback_query(F.data == "menu:fees")
async def cb_fees(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    await _respond(cb, fees_text(ctx.settings), back_kb())
    await cb.answer()


@router.callback_query(F.data == "menu:deals")
async def cb_deals(cb: CallbackQuery, ctx: AppContext) -> None:
    await _send_deals(cb, ctx, cb.from_user, edit=True)
    await cb.answer()


@router.callback_query(F.data == "menu:calc")
async def cb_calc(cb: CallbackQuery, state: FSMContext, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    await state.set_state(CalcFlow.buy)
    await _respond(
        cb,
        "🧮 Крок 1/2. Введіть ціну купівлі в TON (наприклад <code>5.5</code>).",
        calc_cancel_kb(),
        edit=False,
    )
    await cb.answer()


@router.callback_query(F.data == "watch:add")
async def cb_watch_add(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    await _respond(
        cb,
        "➕ <b>Додати підписку</b>\n\n"
        "Введіть команду:\n"
        "<code>/add Durov's Cap</code> — всі моделі\n"
        "<code>/add Toy Bear | Wizard</code> — лише модель Wizard",
        back_kb(),
        edit=False,
    )
    await cb.answer()


@router.callback_query(F.data.startswith("watch:del:"))
async def cb_watch_del(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    try:
        watch_id = int((cb.data or "").rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await cb.answer("Некоректна підписка", show_alert=True)
        return
    removed = await ctx.db.remove_watch(cb.from_user.id, watch_id)
    rows = await ctx.db.list_watch(cb.from_user.id)
    text = watch_text(rows)
    if not removed:
        text += "\n\n⚠️ Підписку не знайдено — можливо, її вже видалено."
    await _respond(cb, text, watch_kb(rows))
    await cb.answer("Видалено" if removed else "Не знайдено")


@router.callback_query(F.data.startswith("bud:"))
async def cb_set_budget(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    try:
        value = float((cb.data or "").split(":", 1)[1])
    except (ValueError, IndexError):
        await cb.answer("Некоректне значення", show_alert=True)
        return
    await ctx.db.update_user(cb.from_user.id, budget_ton=value)
    await _send_settings(cb, ctx, cb.from_user, edit=True)
    await cb.answer(f"Бюджет: {value:g} TON")


@router.callback_query(F.data.startswith("thr:"))
async def cb_set_threshold(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    try:
        value = float((cb.data or "").split(":", 1)[1])
    except (ValueError, IndexError):
        await cb.answer("Некоректне значення", show_alert=True)
        return
    await ctx.db.update_user(cb.from_user.id, min_margin_pct=value)
    await _send_settings(cb, ctx, cb.from_user, edit=True)
    await cb.answer(f"Мінімальна маржа: {value:g}%")


@router.callback_query(F.data.startswith("cur:"))
async def cb_currency(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    value = (cb.data or "").split(":", 1)[1]
    if value not in ("both", "ton", "usd"):
        await cb.answer("Некоректна валюта", show_alert=True)
        return
    await ctx.db.update_user(cb.from_user.id, display_currency=value)
    await _send_settings(cb, ctx, cb.from_user, edit=True)
    await cb.answer("Збережено")


@router.callback_query(F.data == "alerts:toggle")
async def cb_alerts_toggle(cb: CallbackQuery, ctx: AppContext) -> None:
    user = await _ensure_user(ctx, cb.from_user)
    enabled = 0 if int(user.get("alerts_enabled") or 0) else 1
    await ctx.db.update_user(cb.from_user.id, alerts_enabled=enabled)
    await _send_settings(cb, ctx, cb.from_user, edit=True)
    await cb.answer("Сигнали увімкнено" if enabled else "Сигнали вимкнено")


@router.callback_query(F.data == "calc:cancel")
async def cb_calc_cancel(cb: CallbackQuery, state: FSMContext, ctx: AppContext) -> None:
    await state.clear()
    await _respond(cb, "Скасовано.", main_inline_kb())
    await cb.answer()


@router.callback_query(F.data.startswith("c1:"))
async def cb_recalc(cb: CallbackQuery, ctx: AppContext) -> None:
    await _ensure_user(ctx, cb.from_user)
    try:
        _, buy_raw, sell_raw, code = (cb.data or "").split(":")
        buy = int(buy_raw) / 1000
        sell = int(sell_raw) / 1000
    except (ValueError, IndexError):
        await cb.answer("Не вдалося розрахувати", show_alert=True)
        return
    buy_market = {"p": "portals", "t": "tonnel", "m": "mrkt"}.get(code, "portals")
    user = await ctx.db.get_user(cb.from_user.id) or {}
    rate = await ctx.rates.get()
    await _respond(
        cb,
        calc_text(
            buy,
            sell,
            ctx.settings,
            display=user.get("display_currency") or "both",
            rate=rate,
            buy_market=buy_market,
        ),
        back_kb(),
        edit=False,
    )
    await cb.answer()


# Any other private text: small nudge instead of silence.
@router.message(F.text)
async def fallback_text(message: Message, ctx: AppContext) -> None:
    await _ensure_user(ctx, message.from_user)
    await message.answer(
        "Не зрозумів. Скористайтеся /help або кнопками нижче.",
        reply_markup=main_menu_kb(),
    )
