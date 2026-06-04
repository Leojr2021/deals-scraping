from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterable, List

from dotenv import load_dotenv

try:
    load_dotenv()
except Exception:
    pass 

from deal_filters import filter_deals_by_discount
from falabella_scraper import BRAND_SEED_URLS, scan_falabella_products
from storage import DEFAULT_SEEN_DEALS_FILE, filter_unseen_deals, remember_deals
from telegram_notifier import send_telegram_deals

_log = logging.getLogger(__name__)


def scan_falabella_deals(
    seed_urls: Iterable[str] | None = None,
    *,
    min_discount_percent: int = 30,
    include_equal: bool = False,
    pages_per_seed: int = 3,
    max_products_per_page: int = 48,
    max_deals: int | None = None,
) -> List[dict]:
    products = scan_falabella_products(
        seed_urls if seed_urls is not None else BRAND_SEED_URLS,
        pages_per_seed=pages_per_seed,
        max_products_per_page=max_products_per_page,
    )
    _log.info("Productos raspados: %d", len(products))
    deals = filter_deals_by_discount(
        products,
        min_discount_percent=min_discount_percent,
        include_equal=include_equal,
        max_deals=max_deals,
    )
    _log.info("Ofertas con >%d%% descuento: %d", min_discount_percent, len(deals))
    return deals


def scan_and_notify_falabella_deals(
    seed_urls: Iterable[str] | None = None,
    *,
    min_discount_percent: int = 30,
    include_equal: bool = False,
    pages_per_seed: int = 3,
    max_products_per_page: int = 48,
    max_deals: int | None = None,
    seen_file: str | Path = DEFAULT_SEEN_DEALS_FILE,
    telegram_bot_token: str | None = None,
    telegram_chat_id: str | None = None,
) -> List[dict]:
    deals = scan_falabella_deals(
        seed_urls,
        min_discount_percent=min_discount_percent,
        include_equal=include_equal,
        pages_per_seed=pages_per_seed,
        max_products_per_page=max_products_per_page,
        max_deals=max_deals,
    )
    new_deals = filter_unseen_deals(deals, seen_file=seen_file)
    _log.info("Ofertas nuevas (no vistas antes): %d", len(new_deals))

    if new_deals:
        send_telegram_deals(
            new_deals,
            bot_token=telegram_bot_token,
            chat_id=telegram_chat_id,
        )
        remember_deals(new_deals, seen_file=seen_file)

    return new_deals


if __name__ == "__main__":
    import pprint

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )

    new_deals = scan_and_notify_falabella_deals(
        min_discount_percent=55,
        include_equal=False,
        pages_per_seed=2,
        max_deals=20,
    )
    _log.info("%d ofertas nuevas enviadas por Telegram.", len(new_deals))
    pprint.pp(new_deals)
