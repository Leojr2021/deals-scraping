from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, List

from filelock import FileLock

_log = logging.getLogger(__name__)

DEFAULT_SEEN_DEALS_FILE = "seen_falabella_deals.json"


def filter_unseen_deals(
    deals: Iterable[dict],
    *,
    seen_file: str | Path = DEFAULT_SEEN_DEALS_FILE,
) -> List[dict]:
    seen_urls = load_seen_urls(seen_file)
    return [deal for deal in deals if deal.get("url") and deal["url"] not in seen_urls]


def remember_deals(
    deals: Iterable[dict],
    *,
    seen_file: str | Path = DEFAULT_SEEN_DEALS_FILE,
) -> None:
    path = Path(seen_file)
    lock = FileLock(str(path) + ".lock")
    with lock:
        seen_urls = load_seen_urls(path)
        added = 0
        for deal in deals:
            product_url = deal.get("url")
            if product_url and product_url not in seen_urls:
                seen_urls.add(product_url)
                added += 1
        save_seen_urls(path, seen_urls)
    _log.debug("Persisted %d new URLs to %s (total: %d)", added, path, len(seen_urls))


def load_seen_urls(seen_file: str | Path = DEFAULT_SEEN_DEALS_FILE) -> set[str]:
    path = Path(seen_file)
    if not path.exists():
        return set()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _log.warning("Could not load seen URLs from %s: %s", path, exc)
        return set()

    if isinstance(raw, list):
        return {str(item) for item in raw if item}
    if isinstance(raw, dict):
        return {str(item) for item in raw.get("urls", []) if item}
    return set()


def save_seen_urls(seen_file: str | Path, seen_urls: set[str]) -> None:
    path = Path(seen_file)
    path.write_text(
        json.dumps({"urls": sorted(seen_urls)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
