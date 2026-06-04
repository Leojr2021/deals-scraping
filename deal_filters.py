from __future__ import annotations

import re
from typing import Iterable, List

from price_utils import parse_price_number

ALLOWED_BRANDS = ("TP LINK","LOGITECH","LENOVO","ASUS","ALDO","CALIMOD","SAMSUNG","ADIDAS TERREX", "ADIDAS ORIGINALS","adidas", "DIADORA","Mango","MAISON 123","LA MARTINA")


def get_discount_percent(product: dict) -> int | None:
    """Return numeric discount from label or from price vs old_price."""

    discount = product.get("discount")
    if discount:
        match = re.search(r"\d{1,3}", str(discount))
        if match:
            return int(match.group(0))

    current = parse_price_number(str(product.get("price") or ""))
    old = parse_price_number(str(product.get("old_price") or ""))
    if not current or not old or old <= current:
        return None

    return int(round((old - current) / old * 100))


def passes_discount_threshold(
    discount_percent: int,
    *,
    min_discount_percent: int,
    include_equal: bool,
) -> bool:
    if include_equal:
        return discount_percent >= min_discount_percent
    return discount_percent > min_discount_percent


def filter_deals_by_brand(
    products: Iterable[dict],
    brands: Iterable[str] = ALLOWED_BRANDS,
) -> List[dict]:
    """Return only products whose title contains one of the allowed brand names."""
    patterns = [re.compile(re.escape(b), re.IGNORECASE) for b in brands]
    return [p for p in products if any(pat.search(p.get("title") or "") for pat in patterns)]


def filter_deals_by_discount(
    products: Iterable[dict],
    *,
    min_discount_percent: int = 30,
    include_equal: bool = False,
    max_deals: int | None = None,
) -> List[dict]:
    """Return products whose discount is above the requested threshold."""

    deals: List[dict] = []
    for product in products:
        discount_percent = get_discount_percent(product)
        if discount_percent is None:
            continue

        if not passes_discount_threshold(
            discount_percent,
            min_discount_percent=min_discount_percent,
            include_equal=include_equal,
        ):
            continue

        deal = dict(product)
        deal["discount_percent"] = discount_percent
        if not deal.get("discount"):
            deal["discount"] = f"-{discount_percent}%"
        deals.append(deal)

        if max_deals and len(deals) >= max_deals:
            break

    return deals
