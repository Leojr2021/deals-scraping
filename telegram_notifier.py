from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from html import escape
from typing import Iterable


def send_telegram_deals(
    deals: Iterable[dict],
    *,
    bot_token: str | None = None,
    chat_id: str | None = None,
    timeout: int = 15,
) -> None:
    token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    target_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not target_chat_id:
        raise RuntimeError(
            "Missing Telegram config. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID "
            "or pass bot_token/chat_id."
        )

    for deal in deals:
        text = format_telegram_deal(deal)
        image = deal.get("image")
        sent = False
        if image:
            try:
                _send_telegram_photo(
                    bot_token=token,
                    chat_id=target_chat_id,
                    photo_url=image,
                    caption=text,
                    timeout=timeout,
                )
                sent = True
            except (RuntimeError, urllib.error.URLError):
                pass
        if not sent:
            _send_telegram_message(
                bot_token=token,
                chat_id=target_chat_id,
                text=text,
                timeout=timeout,
            )


def format_telegram_deal(deal: dict) -> str:
    title = escape(str(deal.get("title") or "Producto Falabella"))
    brand = escape(str(deal.get("brand") or ""))
    url = escape(str(deal.get("url") or ""), quote=True)
    price = escape(str(deal.get("price") or "N/D"))
    old_price = escape(str(deal.get("old_price") or "N/D"))
    discount = escape(str(deal.get("discount") or ""))

    lines = []
    if brand:
        lines.append(f"🏷 <b>{brand}</b>")
    lines.append(title)
    lines.append(f"💰 S/ {price}")
    if old_price != "N/D":
        lines.append(f"<s>S/ {old_price}</s>")
    if discount:
        lines.append(f"🔥 {discount}")
    if url:
        lines.append(f'<a href="{url}">Ver producto</a>')

    return "\n".join(lines)


def _send_telegram_photo(
    *,
    bot_token: str,
    chat_id: str,
    photo_url: str,
    caption: str,
    timeout: int,
) -> None:
    api_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "photo": photo_url,
            "caption": caption,
            "parse_mode": "HTML",
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                raise RuntimeError(f"Telegram returned HTTP {response.status}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram notification failed: {exc}") from exc


def _send_telegram_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    timeout: int,
) -> None:
    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "false",
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        api_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                raise RuntimeError(f"Telegram returned HTTP {response.status}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Telegram notification failed: {exc}") from exc
