"""Delivery of an offer as a photo card with a direct buy button."""

from __future__ import annotations

import logging
import random

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot.formatting import offer_caption, offer_text
from bot.keyboards import offer_kb
from models import Listing, Offer, market_name

log = logging.getLogger(__name__)


async def send_offer_card(
    bot: Bot,
    chat_id: int,
    offer: Offer,
    *,
    display: str = "both",
    rate: float | None = None,
    discount_pct: float = 3.0,
) -> bool:
    """Send the gift photo, its name/number and a buy link for this exact listing.

    Falls back to a text message when the photo cannot be downloaded by Telegram.
    Returns True when at least one message was delivered.
    """
    keyboard = offer_kb(offer)
    caption = offer_caption(offer, display=display, rate=rate, discount_pct=discount_pct)
    image_url = offer.buy.image_url

    if image_url:
        try:
            await bot.send_photo(
                chat_id,
                image_url,
                caption=caption,
                reply_markup=keyboard,
            )
            return True
        except TelegramAPIError as exc:
            log.warning("send_photo failed for %s (%s): %s", offer.offer_key, image_url, exc)
        except Exception as exc:  # noqa: BLE001 - a broken CDN must not lose the alert
            log.warning("send_photo failed for %s: %s", offer.offer_key, exc)

    try:
        await bot.send_message(
            chat_id,
            offer_text(offer, display=display, rate=rate, discount_pct=discount_pct),
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )
        return True
    except Exception as exc:  # noqa: BLE001 - one bad chat must not stop the scan
        log.warning("Could not send offer %s to %s: %s", offer.offer_key, chat_id, exc)
        return False


async def send_listing_card(bot: Bot, chat_id: int, listing: Listing) -> bool:
    """Send one gift listing as a photo card (used as a sample)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    text = (
        f"🎁 <b>Зразок подарунка</b>\n\n"
        f"<b>{listing.collection}</b>"
        + (f" · {listing.model}" if listing.model else "")
        + (f" #{listing.number}" if listing.number is not None else "")
        + f"\nМайданчик: <b>{market_name(listing.market)}</b>\n"
        f"Ціна: <b>{listing.price_ton:g} TON</b>"
    )
    keyboard = None
    if listing.market_url:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text=f"🛒 Купити на {market_name(listing.market)}", url=listing.market_url)]]
        )

    image_url = listing.image_url
    if image_url:
        try:
            await bot.send_photo(chat_id, image_url, caption=text, reply_markup=keyboard)
            return True
        except TelegramAPIError as exc:
            log.warning("send_photo failed for sample %s: %s", image_url, exc)
        except Exception as exc:
            log.warning("send_photo failed for sample: %s", exc)

    try:
        await bot.send_message(chat_id, text, reply_markup=keyboard, disable_web_page_preview=False)
        return True
    except Exception as exc:
        log.warning("Could not send sample listing to %s: %s", chat_id, exc)
        return False
