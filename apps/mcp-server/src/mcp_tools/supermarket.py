"""Supermarket price search MCP tool.

Uses Playwright to search live prices at Chilean supermarkets (Lider, Jumbo, Santa Isabel).
Handles anti-bot measures including queue-it virtual waiting rooms.
"""
import logging
from typing import Optional

from mcp.server.fastmcp import Context

from src.mcp_app import mcp
from src.mcp_auth import resolve_tenant_id

logger = logging.getLogger(__name__)


@mcp.tool()
async def search_supermarket_prices(
    products: list[str],
    supermarkets: Optional[list[str]] = None,
    max_results_per_product: int = 3,
    tenant_id: Optional[str] = None,
    ctx: Context = None,
) -> dict:
    """Search live prices for grocery products at Chilean supermarkets.

    Uses a real browser (Playwright) to bypass anti-bot protections and return
    current prices. Supports Lider, Jumbo, and Santa Isabel.

    Args:
        products: List of product names to search (e.g. ["huevo", "leche sin lactosa"]).
        supermarkets: Which supermarkets to search. Options: "lider", "jumbo", "santaisabel".
                      Defaults to ["lider", "jumbo"].
        max_results_per_product: Max results to return per product per supermarket (default 3).
        tenant_id: Tenant identifier (resolved automatically).

    Returns:
        Dict with:
          - results: mapping of product → list of {name, price, price_formatted, supermarket, url}
          - summary: human-readable price comparison text
          - errors: list of any products that returned no results
    """
    resolved_tenant_id = resolve_tenant_id(tenant_id, ctx)
    logger.info("search_supermarket_prices: tenant=%s products=%s supermarkets=%s",
                str(resolved_tenant_id)[:8], products, supermarkets)

    if supermarkets is None:
        supermarkets = ["lider", "jumbo"]

    from src.scrapers.supermarket import search_prices, SUPERMARKETS

    # Validate supermarket keys
    valid = [s for s in supermarkets if s in SUPERMARKETS]
    if not valid:
        return {
            "results": {},
            "summary": f"Supermarkets not supported. Valid options: {list(SUPERMARKETS.keys())}",
            "errors": products,
        }

    raw = await search_prices(
        products=products,
        supermarkets=valid,
        max_results_per_product=max_results_per_product,
    )

    # Build human-readable summary
    lines = []
    errors = []
    for product, items in raw.items():
        if not items:
            errors.append(product)
            lines.append(f"• {product}: sin resultados")
            continue
        # Sort by price
        items_sorted = sorted(items, key=lambda x: x["price"])
        best = items_sorted[0]
        line = f"• {product}: mejor precio {best['price_formatted']} en {best['supermarket']}"
        if len(items_sorted) > 1:
            others = ", ".join(
                f"{i['supermarket']} {i['price_formatted']}" for i in items_sorted[1:]
            )
            line += f" (también: {others})"
        lines.append(line)

    summary = "\n".join(lines) if lines else "No se encontraron resultados."

    return {
        "results": raw,
        "summary": summary,
        "errors": errors,
    }
