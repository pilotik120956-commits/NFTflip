"""Human-facing message formatting (HTML parse mode)."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape

from config import Settings
from core.calculator import evaluate, fmt_pct, fmt_ton, fmt_usd, ton_to_usd
from models import Offer, market_name

MARKETS = ("portals", "tonnel", "mrkt")


def esc(value: object) -> str:
    return escape(str(value)) if value is not None else ""


def _mkt(market: str) -> str:
    return market_name(market)


def _usd_suffix(ton: float, rate: float | None, display: str) -> str:
    if rate is None or display == "ton":
        return ""
    return f" (~{fmt_usd(ton_to_usd(ton, rate))})"


def _num(code: str) -> str | None:
    return {"portals": "P", "tonnel": "T", "mrkt": "M"}.get(code)


def offer_text(offer: Offer, display: str = "both", rate: float | None = None,
               discount_pct: float = 3.0) -> str:
    number = f" #{offer.number}" if offer.number is not None else ""
    match = "за номером подарунка" if offer.match_type == "number" else "за візуальними атрибутами"
    lines = [
        "🔥 <b>Арбітражний сигнал</b>",
        "",
        f"🎁 <b>{esc(offer.collection)}{number}</b>",
        f"🧩 {esc(offer.buy.traits)}",
        f"🔎 Збіг: {match}",
        "",
        f"🛒 <b>Купити: {_mkt(offer.buy.market)}</b>",
        f"   {fmt_ton(offer.buy.price_ton)} TON + {fmt_pct(offer.buy_fee_pct)} комісії "
        f"= <b>{fmt_ton(offer.buy_cost)} TON</b>",
        "",
        f"💸 <b>Продати: {_mkt(offer.sell_reference.market)}</b>",
        f"   найнижча чужа пропозиція: {fmt_ton(offer.sell_ask)} TON",
        f"   оцінка продажу (мінус {fmt_pct(discount_pct)}): {fmt_ton(offer.est_sale)} TON",
        f"   після комісії {fmt_pct(offer.sell_fee_pct)} і виведення "
        f"{fmt_ton(offer.withdraw_fee_ton)} TON: <b>{fmt_ton(offer.resale_net)} TON</b>",
        "",
        f"📈 <b>Чистий прибуток: {fmt_ton(offer.profit)} TON"
        f"{_usd_suffix(offer.profit, rate, display)}</b>",
        f"🎯 ROI {fmt_pct(offer.roi_pct)} · маржа {fmt_pct(offer.margin_pct)} · "
        f"ціновий розрив {fmt_pct(offer.gap_pct)}",
        "",
        "<b>Порівняння цін</b>",
    ]
    for other in offer.other_listings:
        diff = (other.price_ton - offer.buy.price_ton) / offer.buy.price_ton * 100 if offer.buy.price_ton else 0
        lines.append(f"• {_mkt(other.market)}: {fmt_ton(other.price_ton)} TON "
                     f"(+{fmt_pct(diff)} до купівлі)")
    lines.append(f"• {_mkt(offer.buy.market)}: {fmt_ton(offer.buy.price_ton)} TON ← купити")
    lines += [
        "",
        f"ℹ️ Оцінка продажу = найнижча чужа пропозиція мінус {fmt_pct(discount_pct)}. "
        "Перевірте ліквідність, комісії та можливість переказу подарунка перед покупкою.",
    ]
    return "\n".join(lines)


def calc_text(buy_price: float, sell_price: float, settings: Settings,
              display: str = "both", rate: float | None = None,
              buy_market: str = "portals") -> str:
    buy_market = buy_market if buy_market in MARKETS else "portals"
    buy_fees = settings.fees_for(buy_market)
    base = evaluate(buy_price, sell_price, buy_fees, buy_fees)
    results = []
    for market in MARKETS:
        result = evaluate(buy_price, sell_price, buy_fees, settings.fees_for(market))
        results.append((market, result))
    results.sort(key=lambda item: item[1].profit, reverse=True)

    lines = [
        "🧮 <b>Калькулятор угоди</b>",
        "",
        f"🛒 Купівля: <b>{fmt_ton(buy_price)} TON</b> на {_mkt(buy_market)}",
        f"   комісія {fmt_pct(buy_fees.buy_pct)} → <b>{fmt_ton(base.buy_cost)} TON</b>",
        "",
        f"💸 Продаж: <b>{fmt_ton(sell_price)} TON</b>",
        "",
        "Варіанти продажу:",
    ]
    for market, result in results:
        fees = settings.fees_for(market)
        lines.append(
            f"• <b>{_mkt(market)}</b> — комісія {fmt_pct(fees.sell_pct)}, "
            f"виведення {fmt_ton(fees.withdraw_ton)} TON"
        )
        lines.append(
            f"   чистими {fmt_ton(result.resale_net)} TON → прибуток "
            f"<b>{fmt_ton(result.profit)} TON</b>{_usd_suffix(result.profit, rate, display)}"
        )
        lines.append(
            f"   ROI {fmt_pct(result.roi_pct)} · маржа {fmt_pct(result.margin_pct)} · "
            f"беззбитковість {fmt_ton(result.breakeven_sell)} TON"
        )
    lines += [
        "",
        "ℹ️ Купівля рахується на обраному майданчику; продаж — на кожному окремо. "
        "Комісії можна змінити в .env.",
    ]
    return "\n".join(lines)


def signal_row_text(row: dict, rate: float | None = None, display: str = "both") -> str:
    number = f" #{row['number']}" if row.get("number") is not None else ""
    profit = float(row["profit"])
    usd = _usd_suffix(profit, rate, display)
    ts = str(row["ts"]).replace("T", " ")[:16]
    link = f" · <a href=\"{esc(row['url'])}\">відкрити</a>" if row.get("url") else ""
    return (
        f"🔥 <b>{esc(row['collection'])}{number}</b>\n"
        f"   {_mkt(row['buy_market'])} → {_mkt(row['sell_market'])} · "
        f"{fmt_ton(float(row['buy_price']))} → {fmt_ton(float(row['sell_ask']))} TON\n"
        f"   прибуток <b>{fmt_ton(profit)} TON</b>{usd} · ROI {fmt_pct(float(row['roi_pct']))}"
        f" · {ts}{link}"
    )


def _ago(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        moment = datetime.fromisoformat(str(iso))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        seconds = int((datetime.now(timezone.utc) - moment).total_seconds())
    except ValueError:
        return "—"
    if seconds < 60:
        return "щойно"
    if seconds < 3600:
        return f"{seconds // 60} хв тому"
    if seconds < 86400:
        return f"{seconds // 3600} год тому"
    return f"{seconds // 86400} дн тому"


def report_text(report) -> str:
    if report is None:
        return "Ще не було жодного циклу сканування."
    errors = {k: v for k, v in report.errors.items() if v}
    lines = [
        "🔍 <b>Ручне сканування завершено</b>",
        "",
        f"⏱ Тривалість: {report.duration_sec:.1f} с",
        f"🔁 Запитів: {report.queries} · лотів: {report.listings} · "
        f"сигналів: {report.offers} · надіслано: {report.sent}",
        f"🕒 {report.finished_at.strftime('%H:%M:%S')} UTC",
    ]
    if errors:
        lines.append("⚠️ Помилки: " + ", ".join(f"{_mkt(k)} ×{v}" for k, v in errors.items()))
    return "\n".join(lines)


def status_text(report, health: dict, counts: dict, settings: Settings) -> str:
    interval = settings.current_interval()
    night = " (нічний режим)" if settings.is_night() else ""
    lines = ["📊 <b>Статус NFTflip</b>", ""]
    lines.append(f"⏱ Інтервал: {interval} с{night}")
    if report is not None:
        lines += [
            f"🕒 Останній цикл: {report.finished_at.strftime('%H:%M:%S')} UTC "
            f"({report.duration_sec:.1f} с)",
            f"🔁 Запитів: {report.queries} · лотів: {report.listings} · "
            f"сигналів: {report.offers} · надіслано: {report.sent}",
        ]
    else:
        lines.append("🕒 Останній цикл: ще не було")
    lines += [
        f"👥 Користувачів: {counts.get('users', 0)} · підписок: {counts.get('watches', 0)} · "
        f"сигналів у базі: {counts.get('signals', 0)}",
        "",
        "<b>Майданчики</b>",
    ]
    for market in MARKETS:
        if market == "mrkt" and not settings.mrkt_configured:
            lines.append("⚪ MRKT — вимкнено (немає авторизації)")
            continue
        row = health.get(market)
        if not row:
            lines.append(f"⚪ {_mkt(market)} — ще не сканувався")
        elif int(row.get("ok") or 0):
            lines.append(
                f"✅ {_mkt(market)} — {int(row.get('listings') or 0)} лотів · "
                f"{_ago(row.get('last_ok_at'))}"
            )
        else:
            error = (row.get("last_error") or "невідома помилка")[:140]
            lines.append(f"❌ {_mkt(market)} — {esc(error)}")
    return "\n".join(lines)


def watch_text(rows: list[dict]) -> str:
    if not rows:
        return (
            "👀 <b>Підписки</b>\n\nПорожньо.\n\n"
            "Додайте колекцію:\n"
            "<code>/add Durov's Cap</code> — всі моделі\n"
            "<code>/add Toy Bear | Wizard</code> — лише модель Wizard"
        )
    lines = ["👀 <b>Підписки</b>", ""]
    for index, row in enumerate(rows, start=1):
        model = f" — модель <b>{esc(row['model'])}</b>" if row.get("model") else " — всі моделі"
        lines.append(f"{index}. <b>{esc(row['collection'])}</b>{model}")
    lines += [
        "",
        "Бот порівнює однакові номери подарунків на Portals, Tonnel і MRKT та "
        "надсилає сигнал, коли на одному майданчику дешевше, ніж на інших.",
    ]
    return "\n".join(lines)


def settings_text(user: dict, settings: Settings) -> str:
    alerts = "увімкнено 🔔" if int(user.get("alerts_enabled") or 0) else "вимкнено 🔕"
    currency = {"both": "TON + USD", "ton": "лише TON", "usd": "лише USD"}.get(
        user.get("display_currency") or "both", "TON + USD"
    )
    return (
        "⚙️ <b>Налаштування</b>\n\n"
        f"💰 Бюджет на одну угоду: <b>{fmt_ton(float(user.get('budget_ton') or 0))} TON</b>\n"
        f"📅 Денний ліміт: <b>{fmt_ton(float(user.get('daily_budget_ton') or 0))} TON</b>\n"
        f"🎯 Мінімальна маржа: <b>{fmt_pct(float(user.get('min_margin_pct') or 0))}</b>\n"
        f"🔔 Сигнали: <b>{alerts}</b>\n"
        f"💵 Валюта: <b>{currency}</b>\n\n"
        f"Інтервал сканера: {settings.current_interval()} с "
        f"(максимум 180 с).\n"
        "Змінити точне значення: <code>/budget 12.5</code>, <code>/daily 100</code>, "
        "<code>/threshold 8</code>."
    )


def fees_text(settings: Settings) -> str:
    lines = ["💸 <b>Комісії майданчиків</b>", ""]
    for market in MARKETS:
        fees = settings.fees_for(market)
        lines.append(
            f"<b>{_mkt(market)}</b>\n"
            f"   купівля: {fmt_pct(fees.buy_pct)} · продаж: {fmt_pct(fees.sell_pct)} · "
            f"виведення: {fmt_ton(fees.withdraw_ton)} TON"
        )
    lines += [
        "",
        "Значення задаються в <code>.env</code> (PORTALS_*_FEE_PCT, TONNEL_*_FEE_PCT, MRKT_*). "
        "Комісії майданчиків змінюються — перевіряйте їх перед реальними угодами.",
    ]
    return "\n".join(lines)


def help_text() -> str:
    return (
        "🤖 <b>NFTflip — арбітраж Telegram-подарунків</b>\n\n"
        "<b>Підписки</b>\n"
        "<code>/add Durov's Cap</code> — слідкувати за колекцією\n"
        "<code>/add Toy Bear | Wizard</code> — лише за моделлю\n"
        "<code>/watch</code> — список підписок\n"
        "<code>/del 3</code> або <code>/del Toy Bear</code> — видалити\n\n"
        "<b>Гроші</b>\n"
        "<code>/budget 15</code> — бюджет на одну угоду, TON\n"
        "<code>/daily 100</code> — денний ліміт, TON\n"
        "<code>/threshold 8</code> — мінімальна маржа, %\n"
        "<code>/calc 5 7</code> — прибуток з урахуванням комісій\n\n"
        "<b>Стан</b>\n"
        "<code>/status</code> — стан сканера\n"
        "<code>/deals</code> — останні сигнали\n"
        "<code>/fees</code> — комісії\n"
        "<code>/pause</code> / <code>/resume</code> — вимкнути/увімкнути сигнали\n"
        "<code>/scan</code> — ручний скан (адмін)\n"
        "<code>/settings</code> — налаштування\n\n"
        "Сигнал означає: однаковий подарунок (колекція + модель + номер) коштує на "
        "одному майданчику помітно дешевше, ніж на інших. Бот <b>не купує автоматично</b> — "
        "рішення завжди за вами."
    )
