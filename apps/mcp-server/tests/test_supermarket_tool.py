"""Tests for src.mcp_tools.supermarket.

Single tool ``search_product_prices``. Stubs the Playwright-backed
``search_prices`` so we exercise the formatting / fallback logic
without spinning up a browser.
"""
from __future__ import annotations

import pytest

from src.mcp_tools import supermarket as sm
from src.scrapers import supermarket as scraper


@pytest.mark.asyncio
async def test_search_product_prices_default_sites(monkeypatch, mock_ctx):
    captured = {}

    async def _fake_search(products, sites, max_results_per_product, currency):
        captured["sites"] = sites
        captured["products"] = products
        return {p: [] for p in products}

    monkeypatch.setattr(scraper, "search_prices", _fake_search)

    out = await sm.search_product_prices(
        products=["leche"],
        tenant_id="t",
        ctx=mock_ctx,
    )
    assert captured["sites"] == ["lider", "jumbo"]
    assert "leche" in out["errors"]
    assert "sin resultados" in out["summary"]


@pytest.mark.asyncio
async def test_search_product_prices_summarizes_best(monkeypatch, mock_ctx):
    async def _fake_search(products, sites, **kw):
        return {
            "leche": [
                {"name": "Leche A", "price": 1500, "price_formatted": "$1500", "site": "Jumbo"},
                {"name": "Leche B", "price": 1200, "price_formatted": "$1200", "site": "Lider"},
            ]
        }

    monkeypatch.setattr(scraper, "search_prices", _fake_search)

    out = await sm.search_product_prices(
        products=["leche"],
        sites=["lider", "jumbo"],
        tenant_id="t",
        ctx=mock_ctx,
    )
    assert "$1200" in out["summary"]
    assert "Lider" in out["summary"]
    # also lists alternate sites in parentheses
    assert "Jumbo" in out["summary"]
    assert out["errors"] == []
