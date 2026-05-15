from __future__ import annotations

import re
from typing import Any, Iterable, List


PRICE_RE = re.compile(r"S/\s*([0-9][0-9.,]*)")
DISCOUNT_RE = re.compile(r"-\s*\d{1,3}\s*%")


def extract_prices(text: str | None) -> List[str]:
    if not text:
        return []
    return unique_in_order(normalize_price(match.group(1)) for match in PRICE_RE.finditer(text))


def extract_discount(text: str | None) -> str | None:
    if not text:
        return None
    match = DISCOUNT_RE.search(text)
    if not match:
        return None
    return clean_discount(match.group(0))


def clean_discount(value: Any) -> str | None:
    if value is None:
        return None
    match = DISCOUNT_RE.search(str(value))
    if not match:
        return None
    return re.sub(r"\s+", "", match.group(0))


def normalize_price(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, (int, float)):
        if value <= 0:
            return None
        return f"{float(value):.2f}"

    if isinstance(value, dict):
        for key in (
            "price",
            "amount",
            "value",
            "salePrice",
            "normalPrice",
            "internetPrice",
            "formattedPrice",
        ):
            normalized = normalize_price(value.get(key))
            if normalized:
                return normalized
        return normalize_price(" ".join(str(item) for item in value.values()))

    if isinstance(value, list):
        for item in value:
            normalized = normalize_price(item)
            if normalized:
                return normalized
        return None

    text = str(value).strip()
    if not text:
        return None

    currency_match = PRICE_RE.search(text)
    token = currency_match.group(1) if currency_match else _first_number_token(text)
    if not token:
        return None

    number = parse_price_number(token)
    if number is None or number <= 0:
        return None
    return f"{number:.2f}"


def parse_price_number(token: str) -> float | None:
    cleaned = re.sub(r"[^0-9.,]", "", token)
    if not cleaned:
        return None

    if "." in cleaned and "," in cleaned:
        decimal_separator = "." if cleaned.rfind(".") > cleaned.rfind(",") else ","
        thousand_separator = "," if decimal_separator == "." else "."
        cleaned = cleaned.replace(thousand_separator, "").replace(decimal_separator, ".")
    elif "," in cleaned:
        parts = cleaned.split(",")
        cleaned = "".join(parts) if len(parts[-1]) == 3 else cleaned.replace(",", ".")
    elif "." in cleaned:
        parts = cleaned.split(".")
        if len(parts) > 2:
            cleaned = "".join(parts[:-1]) + "." + parts[-1]
        elif len(parts[-1]) == 3:
            cleaned = "".join(parts)

    try:
        return float(cleaned)
    except ValueError:
        return None


def choose_old_price(current_price: str, candidates: Iterable[str]) -> str | None:
    current = parse_price_number(current_price)
    for candidate in candidates:
        old = parse_price_number(candidate)
        if old and current and old > current:
            return candidate
    return None


def unique_in_order(values: Iterable[str | None]) -> List[str]:
    seen: set[str] = set()
    unique: List[str] = []
    for value in values:
        if not value or value in seen:
            continue
        unique.append(value)
        seen.add(value)
    return unique


def _first_number_token(text: str) -> str | None:
    match = re.search(r"[0-9][0-9.,]*", text)
    return match.group(0) if match else None
