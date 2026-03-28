"""Supermarket price scraper — Lider, Jumbo, Santa Isabel using Playwright."""
import asyncio
import logging
import re
from typing import Optional

from src.scrapers.base_page import BasePage
from src.services.browser_service import get_browser_service

logger = logging.getLogger(__name__)

# Supported supermarkets config
SUPERMARKETS = {
    "lider": {
        "name": "Lider",
        "search_url": "https://www.lider.cl/supermercado/search?Ntt={query}",
        "product_selector": "[class*='product-card'], [class*='ProductCard'], [data-testid*='product']",
        "name_selector": "[class*='product-title'], [class*='ProductTitle'], h3, h2",
        "price_selector": "[class*='price'], [class*='Price'], [class*='precio']",
        "wait_selector": "[class*='product-card'], [class*='ProductCard']",
    },
    "jumbo": {
        "name": "Jumbo",
        "search_url": "https://www.jumbo.cl/search?q={query}",
        "product_selector": "[class*='product-card'], [class*='ProductCard']",
        "name_selector": "[class*='product-name'], [class*='ProductName'], h3",
        "price_selector": "[class*='price'], [class*='Price']",
        "wait_selector": "[class*='product-card'], [class*='ProductCard']",
    },
    "santaisabel": {
        "name": "Santa Isabel",
        "search_url": "https://www.santaisabel.cl/search?q={query}",
        "product_selector": "[class*='product-card'], [class*='ProductCard']",
        "name_selector": "[class*='product-name'], [class*='ProductName'], h3",
        "price_selector": "[class*='price'], [class*='Price']",
        "wait_selector": "[class*='product-card'], [class*='ProductCard']",
    },
}


def _clean_price(raw: str) -> Optional[int]:
    """Extract integer price from a string like '$1.990' or '1990'."""
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


async def _scrape_one(supermarket_key: str, query: str, max_results: int = 5) -> list[dict]:
    """Scrape search results for a single product on a single supermarket."""
    config = SUPERMARKETS.get(supermarket_key)
    if not config:
        return []

    browser_service = get_browser_service()
    url = config["search_url"].format(query=query.replace(" ", "+"))
    results = []

    try:
        async with browser_service.new_page(timeout=30000) as page:
            base = BasePage(page)

            logger.info("Scraping %s for '%s'", config["name"], query)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Handle queue-it virtual waiting room (Lider uses this)
            if "queue-it" in page.url or "queueit" in page.url:
                logger.info("Queue-it detected for %s — waiting up to 30s", config["name"])
                try:
                    await page.wait_for_url(
                        lambda u: "queue-it" not in u and "queueit" not in u,
                        timeout=30000,
                    )
                except Exception:
                    logger.warning("Queue-it timeout for %s", config["name"])
                    return []

            # Wait for products to load
            try:
                await page.wait_for_selector(config["wait_selector"], timeout=15000)
            except Exception:
                logger.warning("No products found for '%s' on %s", query, config["name"])
                return []

            # Extract product cards
            cards = await page.query_selector_all(config["product_selector"])
            for card in cards[:max_results]:
                try:
                    # Get name
                    name_el = await card.query_selector(config["name_selector"])
                    name = (await name_el.inner_text()).strip() if name_el else ""

                    # Get price
                    price_el = await card.query_selector(config["price_selector"])
                    price_raw = (await price_el.inner_text()).strip() if price_el else ""
                    price = _clean_price(price_raw)

                    if name and price:
                        results.append({
                            "name": name,
                            "price": price,
                            "price_formatted": f"${price:,}".replace(",", "."),
                            "supermarket": config["name"],
                            "url": url,
                        })
                except Exception as e:
                    logger.debug("Error parsing card: %s", e)
                    continue

    except Exception as e:
        logger.warning("Scrape failed for %s '%s': %s", config["name"], query, e)

    return results


async def search_prices(
    products: list[str],
    supermarkets: Optional[list[str]] = None,
    max_results_per_product: int = 3,
) -> dict[str, list[dict]]:
    """Search prices for multiple products across supermarkets.

    Args:
        products: List of product names to search.
        supermarkets: List of supermarket keys to search. Defaults to ["lider"].
        max_results_per_product: Max results to return per product per supermarket.

    Returns:
        Dict mapping product name -> list of results with name, price, supermarket.
    """
    if supermarkets is None:
        supermarkets = ["lider"]

    all_results: dict[str, list[dict]] = {}

    for product in products:
        product_results = []
        tasks = [
            _scrape_one(sm, product, max_results_per_product)
            for sm in supermarkets
            if sm in SUPERMARKETS
        ]
        scraped = await asyncio.gather(*tasks, return_exceptions=True)
        for batch in scraped:
            if isinstance(batch, list):
                product_results.extend(batch)
        all_results[product] = product_results

    return all_results
