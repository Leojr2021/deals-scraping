from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, List
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from price_utils import (
    choose_old_price,
    clean_discount,
    extract_discount,
    extract_prices,
    normalize_price,
    unique_in_order,
)

try:
    from playwright.async_api import (
        Browser,
        Error as PlaywrightError,
        TimeoutError as PlaywrightTimeoutError,
        async_playwright,
    )
    from playwright.async_api import Page
except ModuleNotFoundError:
    PlaywrightError = Exception  # type: ignore[assignment,misc]
    PlaywrightTimeoutError = TimeoutError  # type: ignore[assignment,misc]
    Page = Any  # type: ignore[assignment,misc]
    async_playwright = None  # type: ignore[assignment]

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    from playwright.sync_api import Error as SyncPlaywrightError
    from playwright.sync_api import TimeoutError as SyncPlaywrightTimeoutError
except ModuleNotFoundError:
    _sync_playwright = None  # type: ignore[assignment]
    SyncPlaywrightError = Exception  # type: ignore[assignment,misc]
    SyncPlaywrightTimeoutError = TimeoutError  # type: ignore[assignment,misc]

_log = logging.getLogger(__name__)

# Max concurrent browser contexts — raise to 6 on powerful machines, lower to 2 on weak ones
_CONCURRENCY = 4

MAX_PRODUCTS = 30
FALABELLA_BASE_URL = "https://www.falabella.com.pe"
DEFAULT_SEEN_DEALS_FILE = "seen_falabella_deals.json"

DEFAULT_FALABELLA_SEED_URLS = (
    "https://www.falabella.com.pe/falabella-pe/category/cat1470548/Zapatillas",
    "https://www.falabella.com.pe/falabella-pe/collection/zapatillas-en-oferta",
    "https://www.falabella.com.pe/falabella-pe/category/CATG36090/Calzado-y-zapatillas",
    "https://www.falabella.com.pe/falabella-pe/category/cat210477/TV-Televisores",
    "https://www.falabella.com.pe/falabella-pe/category/cat760706/Celulares-y-Smartphone",
)

BRAND_SEED_URLS = (
    "https://www.falabella.com.pe/falabella-pe/brand/ALDO",
    "https://www.falabella.com.pe/falabella-pe/brand/adidas",
    "https://www.falabella.com.pe/falabella-pe/brand/DIADORA",
)

PRODUCT_LINK_SELECTOR = "a[href*='/product/'], a[href*='/falabella-pe/product/']"
READY_SELECTOR = (
    "script#__NEXT_DATA__, "
    "[data-testid='product-pod'], "
    "[data-testid='pod'], "
    "[id^='testId-pod'], "
    f"{PRODUCT_LINK_SELECTOR}"
)

CURRENT_PRICE_TYPES = (
    "eventprice",
    "internetprice",
    "saleprice",
    "offerprice",
    "currentprice",
    "cmrprice",
)
OLD_PRICE_TYPES = ("normalprice", "regularprice", "listprice", "originalprice")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scrape_falabella(url: str) -> List[dict]:
    """Scrape one Falabella listing page synchronously (simple one-off use)."""
    _ensure_playwright_installed()
    if _sync_playwright is None:
        raise RuntimeError("sync_playwright not available")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="es-PE",
            timezone_id="America/Lima",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 900},
        )
        context.set_extra_http_headers({"Accept-Language": "es-PE,es;q=0.9,en;q=0.8"})
        try:
            page = context.new_page()
            products = _sync_scrape_page(page, url, limit=MAX_PRODUCTS)
        finally:
            context.close()
            browser.close()

    return products[:MAX_PRODUCTS]


def scan_falabella_products(
    seed_urls: Iterable[str] | None = None,
    *,
    pages_per_seed: int = 3,
    max_products_per_page: int = 48,
    max_products: int | None = None,
    concurrency: int = _CONCURRENCY,
) -> List[dict]:
    """Scan listing/category pages concurrently and return deduplicated products."""
    _ensure_playwright_installed()
    seeds = list(seed_urls or DEFAULT_FALABELLA_SEED_URLS)
    return asyncio.run(
        _async_scan(
            seeds,
            pages_per_seed=pages_per_seed,
            max_products_per_page=max_products_per_page,
            max_products=max_products,
            concurrency=concurrency,
        )
    )


def scan_falabella_deals(
    seed_urls: Iterable[str] | None = None,
    *,
    min_discount_percent: int = 30,
    include_equal: bool = False,
    pages_per_seed: int = 3,
    max_products_per_page: int = 48,
    max_deals: int | None = None,
) -> List[dict]:
    """Compatibility wrapper. Prefer importing this from main.py."""
    from main import scan_falabella_deals as _scan_falabella_deals

    return _scan_falabella_deals(
        seed_urls,
        min_discount_percent=min_discount_percent,
        include_equal=include_equal,
        pages_per_seed=pages_per_seed,
        max_products_per_page=max_products_per_page,
        max_deals=max_deals,
    )


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
    """Compatibility wrapper. Prefer importing this from main.py."""
    from main import scan_and_notify_falabella_deals as _scan_and_notify

    return _scan_and_notify(
        seed_urls,
        min_discount_percent=min_discount_percent,
        include_equal=include_equal,
        pages_per_seed=pages_per_seed,
        max_products_per_page=max_products_per_page,
        max_deals=max_deals,
        seen_file=seen_file,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
    )


# ---------------------------------------------------------------------------
# Async core — concurrent scraping
# ---------------------------------------------------------------------------

async def _async_scan(
    seeds: list[str],
    *,
    pages_per_seed: int,
    max_products_per_page: int,
    max_products: int | None,
    concurrency: int,
) -> List[dict]:
    page_jobs = [
        (seed_url, page_number)
        for seed_url in seeds
        for page_number in range(1, pages_per_seed + 1)
    ]
    _log.info(
        "Starting concurrent scrape: %d seeds × %d pages = %d tasks (concurrency=%d)",
        len(seeds),
        pages_per_seed,
        len(page_jobs),
        concurrency,
    )

    sem = asyncio.Semaphore(concurrency)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            tasks = [
                _async_scrape_url(browser, seed_url, page_num, max_products_per_page, sem)
                for seed_url, page_num in page_jobs
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            await browser.close()

    products: List[dict] = []
    seen: set[str] = set()
    for result in results:
        if isinstance(result, BaseException):
            _log.warning("Scrape task failed: %s", result)
            continue
        for product in result:
            url = product.get("url")
            if url and url not in seen:
                products.append(product)
                seen.add(url)
                if max_products and len(products) >= max_products:
                    return products

    _log.info("Total unique products scraped: %d", len(products))
    return products


async def _async_scrape_url(
    browser: Any,
    seed_url: str,
    page_number: int,
    limit: int,
    sem: asyncio.Semaphore,
) -> List[dict]:
    page_url = _url_with_page(seed_url, page_number)
    async with sem:
        _log.info("Scraping %s", page_url)
        context = await _async_new_falabella_context(browser)
        try:
            page = await context.new_page()
            for attempt in range(3):
                try:
                    products = await _async_scrape_falabella_page(page, page_url, limit)
                    _log.debug("  %s → %d products", page_url, len(products))
                    return products
                except PlaywrightError as exc:
                    if attempt == 2:
                        _log.error("All retries exhausted for %s: %s", page_url, exc)
                        return []
                    delay = 2 ** attempt
                    _log.warning(
                        "Attempt %d failed for %s (%s) — retrying in %ds",
                        attempt + 1, page_url, exc, delay,
                    )
                    await asyncio.sleep(delay)
        finally:
            await context.close()
    return []


async def _async_new_falabella_context(browser: Any) -> Any:
    context = await browser.new_context(
        locale="es-PE",
        timezone_id="America/Lima",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 900},
    )
    await context.set_extra_http_headers({"Accept-Language": "es-PE,es;q=0.9,en;q=0.8"})
    return context


async def _async_scrape_falabella_page(page: Any, url: str, limit: int) -> List[dict]:
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await _async_dismiss_common_overlays(page)
    await _async_wait_for_products_or_json(page)
    await _async_scroll_listing(page, target_count=limit)

    products = await _async_extract_products_from_dom(page, url, limit=limit)

    if len(products) < 5:
        products = _merge_products(
            products,
            await _async_extract_products_from_json(page, url, limit=limit),
            limit=limit,
        )

    return products[:limit]


async def _async_wait_for_products_or_json(page: Any) -> None:
    await page.wait_for_selector(READY_SELECTOR, state="attached", timeout=45_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass


async def _async_dismiss_common_overlays(page: Any) -> None:
    for selector in (
        "button:has-text('Aceptar')",
        "button:has-text('Entendido')",
        "button:has-text('Cerrar')",
        "button[aria-label*='cerrar' i]",
        "button[aria-label*='close' i]",
    ):
        try:
            button = page.locator(selector).first
            if await button.is_visible(timeout=1_000):
                await button.click(timeout=1_000)
        except PlaywrightError:
            continue


async def _async_scroll_listing(page: Any, target_count: int) -> None:
    previous_count = await _async_product_link_count(page)
    previous_height = await _async_document_height(page)

    for _ in range(8):
        if previous_count >= target_count:
            break

        await page.evaluate(
            """
            () => window.scrollBy({
                top: Math.max(window.innerHeight * 0.9, 700),
                behavior: 'instant'
            })
            """
        )

        try:
            await page.wait_for_function(
                """
                ([oldCount, oldHeight, target]) => {
                    const count = document.querySelectorAll(
                        "a[href*='/product/'], a[href*='/falabella-pe/product/']"
                    ).length;
                    const height = Math.max(
                        document.body.scrollHeight,
                        document.documentElement.scrollHeight
                    );
                    return count >= target || count > oldCount || height > oldHeight;
                }
                """,
                [previous_count, previous_height, target_count],
                timeout=2_000,
            )
        except PlaywrightTimeoutError:
            break

        current_count = await _async_product_link_count(page)
        current_height = await _async_document_height(page)
        if current_count == previous_count and current_height == previous_height:
            break

        previous_count = current_count
        previous_height = current_height


async def _async_product_link_count(page: Any) -> int:
    try:
        return await page.locator(PRODUCT_LINK_SELECTOR).count()
    except PlaywrightError:
        return 0


async def _async_document_height(page: Any) -> int:
    return int(
        await page.evaluate(
            "() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
        )
    )


async def _async_safe_inner_text(locator: Any) -> str:
    try:
        return await locator.inner_text(timeout=2_000)
    except PlaywrightError:
        return ""


async def _async_extract_products_from_dom(
    page: Any, base_url: str, limit: int
) -> List[dict]:
    products: List[dict] = []
    seen_urls: set[str] = set()
    links = page.locator(PRODUCT_LINK_SELECTOR)

    try:
        total_links = min(await links.count(), limit * 4)
    except PlaywrightError:
        return products

    for index in range(total_links):
        if len(products) >= limit:
            break

        try:
            link = links.nth(index)
            href = await link.get_attribute("href", timeout=2_000)
            product_url = _absolute_url(href, base_url)
            if not product_url or product_url in seen_urls:
                continue

            card = link.locator(
                "xpath=ancestor::*["
                "self::article or self::li or "
                "@data-testid='product-pod' or @data-testid='pod' or "
                "contains(@data-testid, 'pod') or starts-with(@id, 'testId-pod')"
                "][1]"
            )
            container = card.first if await card.count() else link

            text = await _async_safe_inner_text(container)
            prices = extract_prices(text)
            if not prices:
                prices = await _async_extract_prices_from_price_nodes(container)

            title = await _async_extract_title(container, link)
            image_url = await _async_extract_image(container, base_url)
            discount = extract_discount(text)
            brand = await _async_extract_brand(container)

            if not title or not prices or not product_url:
                continue

            current_price = prices[0]
            old_price = choose_old_price(current_price, prices[1:])

            products.append(
                {
                    "title": title,
                    "brand": brand,
                    "price": current_price,
                    "old_price": old_price,
                    "discount": discount,
                    "url": product_url,
                    "image": image_url,
                }
            )
            seen_urls.add(product_url)
        except PlaywrightError:
            continue
        except Exception:
            continue

    return products


async def _async_extract_brand(container: Any) -> str | None:
    for selector in (
        "[data-testid='pod-subTitle']",
        "[data-testid*='brand']",
        "[class*='brand' i]",
    ):
        try:
            node = container.locator(selector).first
            if await node.count():
                text = (await node.inner_text(timeout=1_000)).strip()
                if text and not re.search(r"^por\s", text, re.IGNORECASE):
                    return text
        except PlaywrightError:
            continue
    return None


async def _async_extract_title(container: Any, link: Any) -> str | None:
    for selector in (
        "[data-testid='pod-displayName']",
        "[data-testid*='displayName']",
        "[data-testid*='product-title']",
        "[data-testid*='title']",
        "h2",
        "h3",
    ):
        try:
            node = container.locator(selector).first
            if await node.count():
                title = _clean_title(await node.inner_text(timeout=1_000))
                if title:
                    return title
        except PlaywrightError:
            continue

    for attr in ("title", "aria-label"):
        try:
            value = await link.get_attribute(attr, timeout=1_000)
            title = _clean_title(value)
            if title:
                return title
        except PlaywrightError:
            continue

    try:
        image = container.locator("img[alt]").first
        if await image.count():
            title = _clean_title(await image.get_attribute("alt", timeout=1_000))
            if title:
                return title
    except PlaywrightError:
        pass

    return None


async def _async_extract_prices_from_price_nodes(container: Any) -> List[str]:
    prices: List[str] = []
    for selector in (
        "[data-testid*='price']",
        "[data-price]",
        "[class*='price' i]",
    ):
        try:
            nodes = container.locator(selector)
            for index in range(min(await nodes.count(), 12)):
                node = nodes.nth(index)
                prices.extend(extract_prices(await node.inner_text(timeout=1_000)))
                data_price = await node.get_attribute("data-price", timeout=1_000)
                normalized = normalize_price(data_price)
                if normalized:
                    prices.append(normalized)
        except PlaywrightError:
            continue
    return unique_in_order(prices)


async def _async_extract_image(container: Any, base_url: str) -> str | None:
    try:
        image = container.locator("img").first
        if not await image.count():
            return None

        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            value = await image.get_attribute(attr, timeout=1_000)
            image_url = _clean_image_url(value, base_url)
            if image_url:
                return image_url

        srcset = await image.get_attribute("srcset", timeout=1_000)
        return _first_srcset_url(srcset, base_url)
    except PlaywrightError:
        return None


async def _async_json_payloads(page: Any):  # async generator
    for selector in ("script#__NEXT_DATA__", "script[type='application/ld+json']"):
        try:
            scripts = page.locator(selector)
            for index in range(await scripts.count()):
                raw = await scripts.nth(index).text_content(timeout=1_000)
                if not raw:
                    continue
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    continue
        except PlaywrightError:
            continue


async def _async_extract_products_from_json(
    page: Any, base_url: str, limit: int
) -> List[dict]:
    products: List[dict] = []
    async for payload in _async_json_payloads(page):
        for item in _walk_json(payload):
            if len(products) >= limit:
                return products
            if not isinstance(item, dict):
                continue
            try:
                product = _product_from_json_dict(item, base_url)
                if product:
                    products = _merge_products(products, [product], limit=limit)
            except Exception:
                continue
    return products[:limit]


# ---------------------------------------------------------------------------
# Sync single-page scrape (used only by scrape_falabella)
# ---------------------------------------------------------------------------

def _sync_scrape_page(page: Any, url: str, limit: int) -> List[dict]:
    from playwright.sync_api import (
        Error as _PE,
        TimeoutError as _PTE,
    )

    page.goto(url, wait_until="domcontentloaded", timeout=60_000)

    # dismiss overlays
    for selector in (
        "button:has-text('Aceptar')",
        "button:has-text('Entendido')",
        "button:has-text('Cerrar')",
        "button[aria-label*='cerrar' i]",
        "button[aria-label*='close' i]",
    ):
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1_000):
                btn.click(timeout=1_000)
        except _PE:
            continue

    page.wait_for_selector(READY_SELECTOR, state="attached", timeout=45_000)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except _PTE:
        pass

    # basic DOM extraction (good enough for single-page use)
    products: List[dict] = []
    seen_urls: set[str] = set()
    links = page.locator(PRODUCT_LINK_SELECTOR)
    try:
        total = min(links.count(), limit * 4)
    except _PE:
        return products

    for i in range(total):
        if len(products) >= limit:
            break
        try:
            link = links.nth(i)
            href = link.get_attribute("href", timeout=2_000)
            product_url = _absolute_url(href, url)
            if not product_url or product_url in seen_urls:
                continue
            text = link.inner_text(timeout=2_000)
            prices = extract_prices(text)
            if not prices:
                continue
            products.append({"url": product_url, "price": prices[0], "old_price": choose_old_price(prices[0], prices[1:])})
            seen_urls.add(product_url)
        except (_PE, Exception):
            continue

    return products


# ---------------------------------------------------------------------------
# Pure-Python helpers (no Playwright dependency)
# ---------------------------------------------------------------------------

def _ensure_playwright_installed() -> None:
    if async_playwright is None:
        raise RuntimeError(
            "Playwright is required. Install dependencies with "
            "`pip install -r requirements.txt` and then run "
            "`playwright install chromium`."
        )


def _product_from_json_dict(data: dict, base_url: str) -> dict | None:
    title = _clean_title(_first_value(data, "title", "name", "displayName", "productName"))
    url = _absolute_url(
        _first_value(data, "url", "link", "href", "productUrl", "productURL", "pdpUrl"),
        base_url,
    )
    image = _json_image(data, base_url)

    prices = _json_prices(data)
    discount = clean_discount(
        _first_value(
            data,
            "discount",
            "discountLabel",
            "discountBadge",
            "discountPercentage",
            "discountPercent",
        )
    )

    if not discount:
        discount = _json_discount_from_badges(data)

    raw_brand = _first_value(data, "brand", "brandName", "manufacturer")
    if isinstance(raw_brand, dict):
        brand = str(raw_brand.get("name") or "").strip() or None
    else:
        brand = str(raw_brand).strip() if raw_brand else None

    if not title or not url or not prices:
        return None

    current_price = prices[0]
    old_price = _json_old_price(data) or choose_old_price(current_price, prices[1:])

    return {
        "title": title,
        "brand": brand,
        "price": current_price,
        "old_price": old_price,
        "discount": discount,
        "url": url,
        "image": image,
    }


def _json_prices(data: dict) -> List[str]:
    candidates: List[str] = []

    for key in (
        "currentPrice",
        "salePrice",
        "offerPrice",
        "internetPrice",
        "cmrPrice",
        "eventPrice",
        "price",
    ):
        normalized = normalize_price(data.get(key))
        if normalized:
            candidates.append(normalized)

    prices = data.get("prices")
    if isinstance(prices, list):
        typed = _prices_by_type(prices)
        before_typed_prices = len(candidates)
        for price_type in CURRENT_PRICE_TYPES:
            candidates.extend(typed.get(price_type, []))

        for price in prices:
            is_only_old_price = _price_type(price) in OLD_PRICE_TYPES
            if len(candidates) == before_typed_prices or not is_only_old_price:
                normalized = normalize_price(price)
                if normalized:
                    candidates.append(normalized)
    elif isinstance(prices, dict):
        for value in prices.values():
            normalized = normalize_price(value)
            if normalized:
                candidates.append(normalized)

    offers = data.get("offers")
    if isinstance(offers, dict):
        normalized = normalize_price(offers.get("price"))
        if normalized:
            candidates.append(normalized)
    elif isinstance(offers, list):
        for offer in offers:
            normalized = normalize_price(offer)
            if normalized:
                candidates.append(normalized)

    return unique_in_order(candidates)


def _json_old_price(data: dict) -> str | None:
    for key in (
        "oldPrice",
        "normalPrice",
        "regularPrice",
        "listPrice",
        "originalPrice",
        "crossedPrice",
        "wasPrice",
    ):
        normalized = normalize_price(data.get(key))
        if normalized:
            return normalized

    prices = data.get("prices")
    if isinstance(prices, list):
        typed = _prices_by_type(prices)
        for price_type in OLD_PRICE_TYPES:
            for value in typed.get(price_type, []):
                return value

    return None


def _prices_by_type(prices: list) -> dict[str, List[str]]:
    typed: dict[str, List[str]] = {}
    for price in prices:
        price_type = _price_type(price)
        normalized = normalize_price(price)
        if not price_type or not normalized:
            continue
        typed.setdefault(price_type, []).append(normalized)
    return typed


def _price_type(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    for key in ("type", "priceType", "label", "name"):
        raw = value.get(key)
        if raw:
            return re.sub(r"[^a-z]", "", str(raw).lower())
    return None


def _json_image(data: dict, base_url: str) -> str | None:
    direct = _first_value(data, "image", "imageUrl", "imageURL", "thumbnail", "thumbnailUrl")
    image_url = _clean_image_url(direct, base_url)
    if image_url:
        return image_url

    images = (
        data.get("images")
        or data.get("imageUrls")
        or data.get("media")
        or data.get("mediaUrls")
    )
    if isinstance(images, list):
        for item in images:
            image_url = _clean_image_url(item, base_url)
            if image_url:
                return image_url
    elif isinstance(images, dict):
        image_url = _clean_image_url(images, base_url)
        if image_url:
            return image_url

    return None


def _json_discount_from_badges(data: dict) -> str | None:
    badges = data.get("badges") or data.get("labels")
    if not isinstance(badges, list):
        return None

    for badge in badges:
        if isinstance(badge, dict):
            value = _first_value(badge, "label", "text", "name", "value")
        else:
            value = badge
        discount = clean_discount(value)
        if discount:
            return discount
    return None


def _first_value(data: dict, *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _clean_title(value: Any) -> str | None:
    if value is None:
        return None

    title = re.sub(r"\s+", " ", str(value)).strip()
    if not title:
        return None

    if " - " in title:
        _, title = title.split(" - ", 1)

    title = re.sub(r"\s*Por\s+.+$", "", title, flags=re.IGNORECASE).strip()
    title = re.sub(r"\s*Agregar al Carro\s*$", "", title, flags=re.IGNORECASE).strip()

    if not title or title.lower() in {"image", "producto"}:
        return None
    return title


def _absolute_url(value: Any, base_url: str) -> str | None:
    if value is None:
        return None

    if isinstance(value, dict):
        value = _first_value(value, "url", "href", "link")
    elif isinstance(value, list):
        value = next((item for item in value if item), None)

    if not isinstance(value, str):
        return None

    url = value.strip()
    if not url:
        return None
    return urljoin(base_url or FALABELLA_BASE_URL, url).split("#", 1)[0]


def _clean_image_url(value: Any, base_url: str) -> str | None:
    if value is None:
        return None

    if isinstance(value, dict):
        value = _first_value(value, "url", "src", "imageUrl", "thumbnailUrl")
    elif isinstance(value, list):
        value = next((item for item in value if item), None)

    if not isinstance(value, str):
        return None

    image_url = value.strip()
    if not image_url or image_url.startswith("data:"):
        return None
    return urljoin(base_url or FALABELLA_BASE_URL, image_url)


def _first_srcset_url(srcset: str | None, base_url: str) -> str | None:
    if not srcset:
        return None
    first = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
    return _clean_image_url(first, base_url)


def _merge_products(existing: List[dict], incoming: List[dict], limit: int) -> List[dict]:
    merged = list(existing)
    seen = {product.get("url") for product in merged if product.get("url")}

    for product in incoming:
        product_url = product.get("url")
        if not product_url or product_url in seen:
            continue
        merged.append(product)
        seen.add(product_url)
        if len(merged) >= limit:
            break

    return merged


def _walk_json(value: Any) -> Iterable[Any]:
    stack = [value]
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _url_with_page(url: str, page_number: int) -> str:
    if page_number <= 1:
        return url

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(page_number)
    return urlunparse(parsed._replace(query=urlencode(query)))
