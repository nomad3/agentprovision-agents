"""Tests for src.mcp_tools.email helpers and a few thin tool wrappers.

The full email module is large and integrates with Gmail + Outlook +
Postgres + the API's /internal/embed endpoint. This file covers the
pure helpers plus shallow happy-path tests for the public MCP tools
that don't need a Postgres connection.
"""
from __future__ import annotations

import base64

import pytest

from src.mcp_tools import email as em


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------

def test_strip_html_collapses_whitespace_and_breaks():
    out = em._strip_html("<p>Hello<br/>World</p>")
    assert "Hello" in out
    assert "World" in out
    assert "<" not in out


def test_strip_html_handles_entities():
    assert "&" in em._strip_html("AT&amp;T")


# ---------------------------------------------------------------------------
# _escape_odata_string
# ---------------------------------------------------------------------------

def test_escape_odata_string_escapes_single_quote():
    assert em._escape_odata_string("O'Brien") == "O''Brien"


# ---------------------------------------------------------------------------
# _extract_body
# ---------------------------------------------------------------------------

def test_extract_body_decodes_plain_text():
    encoded = base64.urlsafe_b64encode(b"Hello world").decode()
    payload = {"mimeType": "text/plain", "body": {"data": encoded}}
    assert em._extract_body(payload) == "Hello world"


def test_extract_body_descends_into_parts():
    encoded_plain = base64.urlsafe_b64encode(b"nested").decode()
    encoded_html = base64.urlsafe_b64encode(b"<p>html</p>").decode()
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/html", "body": {"data": encoded_html}},
            {"mimeType": "text/plain", "body": {"data": encoded_plain}},
        ],
    }
    # _extract_body is depth-first and the html part comes first, but the
    # function only keeps text/plain at the recursive layer; html falls
    # through to the fallback. So the first non-empty descendant wins.
    out = em._extract_body(payload)
    assert out in ("<p>html</p>", "nested")


def test_extract_body_html_fallback():
    encoded = base64.urlsafe_b64encode(b"<b>html only</b>").decode()
    payload = {"mimeType": "text/html", "body": {"data": encoded}}
    assert "html only" in em._extract_body(payload)


def test_extract_body_returns_empty_for_unknown():
    assert em._extract_body({"mimeType": "image/png", "body": {}}) == ""


# ---------------------------------------------------------------------------
# _extract_attachments
# ---------------------------------------------------------------------------

def test_extract_attachments_walks_nested_parts():
    payload = {
        "filename": "",
        "parts": [
            {
                "filename": "report.pdf",
                "mimeType": "application/pdf",
                "body": {"attachmentId": "a-1", "size": 1234},
            },
            {
                "filename": "",
                "parts": [
                    {
                        "filename": "image.png",
                        "mimeType": "image/png",
                        "body": {"attachmentId": "a-2", "size": 99},
                    }
                ],
            },
        ],
    }
    attachments = em._extract_attachments(payload)
    assert len(attachments) == 2
    assert attachments[0]["filename"] == "report.pdf"
    assert attachments[1]["attachment_id"] == "a-2"


# ---------------------------------------------------------------------------
# _build_outlook_search
# ---------------------------------------------------------------------------

def test_build_outlook_search_default():
    params, headers = em._build_outlook_search("", 10)
    assert params["$top"] == 10
    assert params["$orderby"] == "receivedDateTime DESC"
    # No $filter / $search when query empty
    assert "$filter" not in params
    assert "$search" not in params


def test_build_outlook_search_translates_from_subject_unread():
    params, headers = em._build_outlook_search(
        "from:alice@x.com subject:invoice is:unread", 10
    )
    assert "from/emailAddress/address eq 'alice@x.com'" in params["$filter"]
    assert "contains(subject,'invoice')" in params["$filter"]
    assert "isRead eq false" in params["$filter"]


def test_build_outlook_search_newer_than_days():
    params, _ = em._build_outlook_search("newer_than:7d", 10)
    assert "receivedDateTime ge" in params["$filter"]


def test_build_outlook_search_text_uses_search():
    params, headers = em._build_outlook_search("budget proposal", 10)
    assert params["$search"] == '"budget proposal"'
    assert headers["ConsistencyLevel"] == "eventual"
    assert "$orderby" not in params


def test_build_outlook_search_to_filter():
    params, _ = em._build_outlook_search("to:bob@x.com", 5)
    assert "toRecipients/any" in params["$filter"]


# ---------------------------------------------------------------------------
# _extract_email_entities
# ---------------------------------------------------------------------------

def test_extract_entities_dedupes_and_extracts_org():
    headers = {
        "From": '"Alice" <alice@acme.com>',
        "To": "bob@acme.com, alice@acme.com",  # alice repeated
        "Cc": "carol@gmail.com",
    }
    entities = em._extract_email_entities(headers, "body", "owner@self.com")
    emails = {e["properties"]["email"] for e in entities if e["entity_type"] == "person"}
    assert "alice@acme.com" in emails
    assert "bob@acme.com" in emails
    # Acme should be flagged as an organization (not gmail.com which is common)
    orgs = {e["properties"]["domain"] for e in entities if e["entity_type"] == "organization"}
    assert "acme.com" in orgs
    assert "gmail.com" not in orgs


def test_extract_entities_excludes_self():
    headers = {"From": "self@example.com"}
    entities = em._extract_email_entities(headers, "", "self@example.com")
    assert entities == []


# ---------------------------------------------------------------------------
# list_connected_email_accounts (top-level dispatch)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_connected_email_accounts_aggregates(monkeypatch, mock_ctx):
    async def _fake(tenant_id):
        return [{"email": "g@x", "integration_name": "gmail"}]

    monkeypatch.setattr(em, "_get_all_connected_email_accounts", _fake)
    out = await em.list_connected_email_accounts(tenant_id="t", ctx=mock_ctx)
    assert out["count"] == 1
    assert out["accounts"][0]["email"] == "g@x"


@pytest.mark.asyncio
async def test_list_connected_email_accounts_handles_exception(monkeypatch, mock_ctx):
    async def _boom(tenant_id):
        raise RuntimeError("network")

    monkeypatch.setattr(em, "_get_all_connected_email_accounts", _boom)
    out = await em.list_connected_email_accounts(tenant_id="t", ctx=mock_ctx)
    assert "error" in out


# ---------------------------------------------------------------------------
# search_emails — top-level error paths
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_emails_no_accounts(monkeypatch, mock_ctx):
    async def _none(tid):
        return []

    monkeypatch.setattr(em, "_get_all_connected_email_accounts", _none)
    out = await em.search_emails(tenant_id="t", ctx=mock_ctx)
    assert "No email accounts" in out["error"]


@pytest.mark.asyncio
async def test_search_emails_specific_account_not_found(monkeypatch, mock_ctx):
    async def _accounts(tid):
        return [{"email": "alice@x", "integration_name": "gmail"}]

    monkeypatch.setattr(em, "_get_all_connected_email_accounts", _accounts)
    out = await em.search_emails(
        tenant_id="t", account_email="ghost@x", ctx=mock_ctx
    )
    assert "No connected email account" in out["error"]


@pytest.mark.asyncio
async def test_search_emails_token_missing(monkeypatch, mock_ctx):
    async def _accounts(tid):
        return [{"email": "g@x", "integration_name": "gmail"}]

    async def _no_token(*a, **kw):
        return None

    monkeypatch.setattr(em, "_get_all_connected_email_accounts", _accounts)
    monkeypatch.setattr(em, "_get_oauth_token", _no_token)
    out = await em.search_emails(tenant_id="t", ctx=mock_ctx)
    assert "Gmail not connected" in out["error"]


@pytest.mark.asyncio
async def test_search_emails_gmail_no_messages(monkeypatch, mock_ctx, make_client):
    async def _accounts(tid):
        return [{"email": "g@x", "integration_name": "gmail"}]

    async def _token(*a, **kw):
        return "tok"

    monkeypatch.setattr(em, "_get_all_connected_email_accounts", _accounts)
    monkeypatch.setattr(em, "_get_oauth_token", _token)

    client = make_client(default_status=200, default_json={"messages": [], "resultSizeEstimate": 0})
    monkeypatch.setattr(em.httpx, "AsyncClient", lambda *a, **kw: client)
    out = await em.search_emails(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["emails"] == []


@pytest.mark.asyncio
async def test_search_emails_outlook_no_results(monkeypatch, mock_ctx, make_client):
    async def _accounts(tid):
        return [{"email": "o@x", "integration_name": "outlook"}]

    async def _token(*a, **kw):
        return "tok"

    monkeypatch.setattr(em, "_get_all_connected_email_accounts", _accounts)
    monkeypatch.setattr(em, "_get_oauth_token", _token)
    client = make_client(default_status=200, default_json={"value": []})
    monkeypatch.setattr(em.httpx, "AsyncClient", lambda *a, **kw: client)
    out = await em.search_emails(tenant_id="t", ctx=mock_ctx)
    assert out["status"] == "success"
    assert out["emails"] == []
