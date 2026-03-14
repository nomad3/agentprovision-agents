"""Email and Google Calendar tools for the personal assistant.

Uses stored OAuth tokens (via credential vault) to call Gmail, Outlook,
and Google Calendar APIs on behalf of the authenticated user.
"""
import base64
import html
import logging
import re
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Optional

import httpx

from config.settings import settings
from tools.knowledge_tools import _resolve_tenant_id

logger = logging.getLogger(__name__)

_api_client: Optional[httpx.AsyncClient] = None
_provider_client: Optional[httpx.AsyncClient] = None
EMAIL_INTEGRATIONS = ("gmail", "outlook")


def _get_api_client() -> httpx.AsyncClient:
    global _api_client
    if _api_client is None:
        _api_client = httpx.AsyncClient(
            base_url=settings.api_base_url,
            timeout=30.0,
        )
    return _api_client


def _get_provider_client() -> httpx.AsyncClient:
    global _provider_client
    if _provider_client is None:
        _provider_client = httpx.AsyncClient(timeout=30.0)
    return _provider_client


async def _get_oauth_token(
    tenant_id: str, integration_name: str, account_email: Optional[str] = None,
) -> Optional[str]:
    """Retrieve decrypted OAuth access token from the API credential vault."""
    client = _get_api_client()
    try:
        params: dict = {"tenant_id": tenant_id}
        if account_email:
            params["account_email"] = account_email
        resp = await client.get(
            f"/api/v1/oauth/internal/token/{integration_name}",
            headers={"X-Internal-Key": settings.mcp_api_key},
            params=params,
        )
        if resp.status_code == 200:
            return resp.json().get("oauth_token")
        logger.warning("Token retrieval for %s returned %s", integration_name, resp.status_code)
    except Exception:
        logger.exception("Failed to retrieve %s token", integration_name)
    return None


async def _get_connected_accounts_for_integration(
    tenant_id: str, integration_name: str,
) -> list[dict]:
    client = _get_api_client()
    try:
        resp = await client.get(
            f"/api/v1/oauth/internal/connected-accounts/{integration_name}",
            headers={"X-Internal-Key": settings.mcp_api_key},
            params={"tenant_id": tenant_id},
        )
        if resp.status_code != 200:
            logger.warning(
                "Connected accounts lookup for %s returned %s",
                integration_name,
                resp.status_code,
            )
            return []

        accounts = resp.json().get("accounts", [])
        normalized = []
        for account in accounts:
            email = account.get("account_email")
            normalized.append({
                "email": email,
                "account_email": email,
                "integration_name": integration_name,
                "provider": "google" if integration_name == "gmail" else "microsoft",
                "enabled": account.get("enabled", True),
            })
        return normalized
    except Exception:
        logger.exception("Failed to list accounts for %s", integration_name)
        return []


async def _get_all_connected_email_accounts(tenant_id: str) -> list[dict]:
    accounts: list[dict] = []
    for integration_name in EMAIL_INTEGRATIONS:
        accounts.extend(await _get_connected_accounts_for_integration(tenant_id, integration_name))
    return accounts


async def _resolve_email_account(
    tenant_id: str, account_email: str = "",
) -> tuple[Optional[dict], Optional[str]]:
    accounts = await _get_all_connected_email_accounts(tenant_id)
    if not accounts:
        return None, "No email accounts connected. Ask the user to connect Gmail or Outlook in Connected Apps."

    if account_email:
        account = next((a for a in accounts if a.get("email") == account_email), None)
        if not account:
            return None, f"No connected email account found for {account_email}."
        return account, None

    return accounts[0], None


def _escape_odata_string(value: str) -> str:
    return value.replace("'", "''")


def _strip_html(content: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", content, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(re.sub(r"\s+\n", "\n", re.sub(r"[ \t]+", " ", text))).strip()


async def _embed_attachment_content(
    tenant_id: str,
    message_id: str,
    attachment_id: str,
    text_content: str,
) -> None:
    """Embed attachment text into the embeddings table for semantic search.

    Uses the ADK's local embedding service and DB connection (via
    KnowledgeGraphService) to INSERT directly into the embeddings table.
    Failures are logged but never raised — embedding is best-effort.
    """
    if not text_content or text_content.startswith("("):
        # Skip placeholder messages like "(Binary file, ... bytes)"
        return

    try:
        from services.knowledge_graph import get_knowledge_service
        from memory.vertex_vector import get_embedding_service

        kg = get_knowledge_service()
        emb_svc = get_embedding_service()

        # Truncate to match the model's effective window
        truncated = text_content[:8000]
        embedding = await emb_svc.get_embedding(truncated, task_type="RETRIEVAL_DOCUMENT")
        if embedding is None:
            logger.debug("Attachment embedding skipped — model returned None")
            return

        content_id = f"{message_id}_{attachment_id}"
        emb_id = str(_uuid.uuid4())

        from sqlalchemy import text as sa_text

        with kg.Session() as session:
            # Upsert: remove previous embedding for same attachment
            session.execute(
                sa_text(
                    "DELETE FROM embeddings WHERE content_type = 'email_attachment' AND content_id = :cid"
                ),
                {"cid": content_id},
            )
            session.execute(
                sa_text("""
                    INSERT INTO embeddings
                    (id, tenant_id, content_type, content_id, embedding, text_content, task_type, model, created_at, updated_at)
                    VALUES (:id, :tenant_id, 'email_attachment', :content_id, :embedding, :text_content,
                            'RETRIEVAL_DOCUMENT', 'nomic-ai/nomic-embed-text-v1.5', NOW(), NOW())
                """),
                {
                    "id": emb_id,
                    "tenant_id": tenant_id,
                    "content_id": content_id,
                    "embedding": embedding,
                    "text_content": truncated,
                },
            )
            session.commit()
        logger.info("Embedded attachment %s for tenant %s", content_id, tenant_id[:8])
    except Exception:
        logger.warning("Attachment embedding failed (best-effort)", exc_info=True)


def _build_outlook_search(query: str, max_results: int) -> tuple[dict, dict]:
    params = {
        "$top": min(max_results, 20),
        "$orderby": "receivedDateTime DESC",
        "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead",
    }
    headers = {"Prefer": 'outlook.body-content-type="text"'}
    if not query:
        return params, headers

    filters = []
    search_terms = []
    tokens = re.findall(r'(?:[^\s"]+|"[^"]*")+', query)

    for token in tokens:
        raw = token.strip()
        cleaned = raw.strip('"')
        lower = cleaned.lower()

        if lower.startswith("from:"):
            email = _escape_odata_string(cleaned[5:])
            filters.append(f"from/emailAddress/address eq '{email}'")
        elif lower.startswith("to:"):
            email = _escape_odata_string(cleaned[3:])
            filters.append(f"toRecipients/any(r:r/emailAddress/address eq '{email}')")
        elif lower.startswith("subject:"):
            subject = _escape_odata_string(cleaned[8:])
            filters.append(f"contains(subject,'{subject}')")
        elif lower.startswith("newer_than:"):
            match = re.fullmatch(r"newer_than:(\d+)([dh])", lower)
            if match:
                amount = int(match.group(1))
                unit = match.group(2)
                delta = timedelta(days=amount) if unit == "d" else timedelta(hours=amount)
                cutoff = (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")
                filters.append(f"receivedDateTime ge {cutoff}")
        elif lower == "is:unread":
            filters.append("isRead eq false")
        elif ":" not in cleaned:
            search_terms.append(cleaned)

    if filters:
        params["$filter"] = " and ".join(filters)
    if search_terms:
        params["$search"] = f"\"{' '.join(search_terms)}\""
        headers["ConsistencyLevel"] = "eventual"
        params.pop("$orderby", None)
    return params, headers


# ---------------------------------------------------------------------------
# Email tools (Gmail + Outlook)
# ---------------------------------------------------------------------------

async def list_connected_email_accounts(
    tenant_id: str = "auto",
) -> dict:
    """List all email accounts connected for this tenant.

    Use this to discover which email accounts are available before searching.
    When the user asks about "work email" or "personal email", use this to find
    the right account_email and pass it to search_emails or read_email.

    Args:
        tenant_id: Tenant context. Use "auto" if unknown.

    Returns:
        Dict with list of connected email accounts.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    try:
        accounts = await _get_all_connected_email_accounts(tenant_id)
        return {"accounts": accounts, "count": len(accounts)}
    except Exception as e:
        logger.exception("list_connected_email_accounts failed")
        return {"error": str(e)}


async def search_emails(
    tenant_id: str = "auto",
    query: str = "",
    max_results: int = 10,
    account_email: str = "",
) -> dict:
    """Search Gmail or Outlook for emails matching a query.

    Args:
        tenant_id: Tenant context. Use "auto" if unknown.
        query: Gmail-style search query (e.g. "from:alice@example.com",
               "subject:invoice", "is:unread", "newer_than:2d"). For Outlook,
               the common filters are translated to Microsoft Graph.
        max_results: Maximum number of emails to return (1-20).
        account_email: Specific email account to search (e.g. "user@company.com").
                       If empty, searches the default (first) connected account.
                       Use list_connected_email_accounts to discover available accounts.

    Returns:
        Dict with list of email summaries (subject, from, date, snippet).
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    account, error = await _resolve_email_account(tenant_id, account_email)
    if error:
        return {"error": error}

    integration_name = account["integration_name"]
    token = await _get_oauth_token(tenant_id, integration_name, account.get("email"))
    if not token:
        return {"error": f"{integration_name.title()} not connected. Ask the user to reconnect it in Connected Apps."}

    provider_client = _get_provider_client()
    auth = {"Authorization": f"Bearer {token}"}

    try:
        if integration_name == "gmail":
            params = {"maxResults": min(max_results, 20)}
            if query:
                params["q"] = query
            resp = await provider_client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers=auth,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            messages = data.get("messages", [])

            if not messages:
                return {"status": "success", "emails": [], "message": "No emails found."}

            emails = []
            for msg in messages:
                detail = await provider_client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg['id']}",
                    headers=auth,
                    params=[
                        ("format", "metadata"),
                        ("metadataHeaders", "Subject"),
                        ("metadataHeaders", "From"),
                        ("metadataHeaders", "Date"),
                    ],
                )
                if detail.status_code != 200:
                    continue
                md = detail.json()
                headers = {h["name"]: h["value"] for h in md.get("payload", {}).get("headers", [])}
                labels = md.get("labelIds", [])
                emails.append({
                    "id": msg["id"],
                    "subject": headers.get("Subject", "(no subject)"),
                    "from": headers.get("From", ""),
                    "date": headers.get("Date", ""),
                    "snippet": md.get("snippet", ""),
                    "is_read": "UNREAD" not in labels,
                    "provider": "google",
                    "account_email": account.get("email"),
                })

            return {"status": "success", "emails": emails, "total": data.get("resultSizeEstimate", len(emails))}

        params, extra_headers = _build_outlook_search(query, max_results)
        resp = await provider_client.get(
            "https://graph.microsoft.com/v1.0/me/messages",
            headers={**auth, **extra_headers},
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        emails = [{
            "id": item.get("id"),
            "subject": item.get("subject") or "(no subject)",
            "from": (item.get("from") or {}).get("emailAddress", {}).get("address", ""),
            "date": item.get("receivedDateTime", ""),
            "snippet": item.get("bodyPreview", ""),
            "is_read": item.get("isRead", False),
            "provider": "microsoft",
            "account_email": account.get("email"),
        } for item in data.get("value", [])]

        if not emails:
            return {"status": "success", "emails": [], "message": "No emails found."}

        return {"status": "success", "emails": emails, "total": len(emails)}

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {"error": f"{integration_name.title()} token expired. Ask user to reconnect it in Connected Apps."}
        return {"error": f"{integration_name.title()} API error: {e.response.status_code}"}
    except Exception as e:
        logger.exception("search_emails failed")
        return {"error": f"Failed to search emails: {str(e)}"}


async def read_email(
    tenant_id: str = "auto",
    message_id: str = "",
    account_email: str = "",
) -> dict:
    """Read the full content of a specific email by its message ID.

    Args:
        tenant_id: Tenant context. Use "auto" if unknown.
        message_id: Message ID from search_emails results.
        account_email: Specific email account to read from. Use the same account
                       that was used in search_emails to find this message.

    Returns:
        Dict with email subject, from, to, date, and body text.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    if not message_id:
        return {"error": "message_id is required. Use search_emails first to get message IDs."}

    account, error = await _resolve_email_account(tenant_id, account_email)
    if error:
        return {"error": error}

    integration_name = account["integration_name"]
    token = await _get_oauth_token(tenant_id, integration_name, account.get("email"))
    if not token:
        return {"error": f"{integration_name.title()} not connected. Ask the user to reconnect it in Connected Apps."}

    provider_client = _get_provider_client()
    auth = {"Authorization": f"Bearer {token}"}

    try:
        if integration_name == "gmail":
            resp = await provider_client.get(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
                headers=auth,
                params={"format": "full"},
            )
            resp.raise_for_status()
            msg = resp.json()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            body = _extract_body(msg.get("payload", {}))

            # Extract attachment metadata
            attachments = _extract_attachments(msg.get("payload", {}))

            return {
                "status": "success",
                "id": message_id,
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "date": headers.get("Date", ""),
                "body": body[:5000],
                "labels": msg.get("labelIds", []),
                "attachments": attachments,
                "provider": "google",
                "account_email": account.get("email"),
            }

        resp = await provider_client.get(
            f"https://graph.microsoft.com/v1.0/me/messages/{message_id}",
            headers={**auth, "Prefer": 'outlook.body-content-type="text"'},
            params={
                "$select": "subject,from,toRecipients,receivedDateTime,body,bodyPreview,internetMessageHeaders",
            },
        )
        resp.raise_for_status()
        msg = resp.json()
        body = (msg.get("body") or {}).get("content") or msg.get("bodyPreview", "")
        if (msg.get("body") or {}).get("contentType", "").lower() == "html":
            body = _strip_html(body)

        return {
            "status": "success",
            "id": message_id,
            "subject": msg.get("subject") or "(no subject)",
            "from": (msg.get("from") or {}).get("emailAddress", {}).get("address", ""),
            "to": ", ".join(
                recipient.get("emailAddress", {}).get("address", "")
                for recipient in msg.get("toRecipients", [])
            ),
            "date": msg.get("receivedDateTime", ""),
            "body": body[:5000],
            "labels": [],
            "provider": "microsoft",
            "account_email": account.get("email"),
        }

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {"error": f"{integration_name.title()} token expired. Ask user to reconnect it."}
        return {"error": f"{integration_name.title()} API error: {e.response.status_code}"}
    except Exception as e:
        logger.exception("read_email failed")
        return {"error": f"Failed to read email: {str(e)}"}


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from Gmail message payload."""
    mime = payload.get("mimeType", "")

    if mime == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    # Fallback: try HTML
    if mime == "text/html" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    return ""


def _extract_attachments(payload: dict) -> list:
    """Extract attachment metadata from Gmail message payload."""
    attachments = []

    def _walk(part):
        filename = part.get("filename", "")
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        if filename and attachment_id:
            attachments.append({
                "attachment_id": attachment_id,
                "filename": filename,
                "mime_type": part.get("mimeType", ""),
                "size": body.get("size", 0),
            })
        for sub in part.get("parts", []):
            _walk(sub)

    _walk(payload)
    return attachments


async def download_attachment(
    tenant_id: str,
    message_id: str,
    attachment_id: str,
    account_email: Optional[str] = None,
) -> dict:
    """Download a Gmail attachment and return its text content.

    Use read_email first to get attachment_id and filename from the attachments list.
    Supports PDF, text, CSV, spreadsheets, and common document formats.
    Returns the extracted text content (not raw binary).

    Args:
        tenant_id: Tenant identifier.
        message_id: Gmail message ID (from search_emails or read_email).
        attachment_id: Attachment ID (from read_email attachments list).
        account_email: Optional email account to use.

    Returns:
        Dict with filename, mime_type, size, and extracted text content.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    if not message_id or not attachment_id:
        return {"error": "message_id and attachment_id are required. Use read_email first."}

    account, error = await _resolve_email_account(tenant_id, account_email)
    if error:
        return {"error": error}

    integration_name = account["integration_name"]
    if integration_name != "gmail":
        return {"error": "Attachment download is only supported for Gmail accounts."}

    token = await _get_oauth_token(tenant_id, integration_name, account.get("email"))
    if not token:
        return {"error": "Gmail not connected. Ask the user to reconnect it in Connected Apps."}

    provider_client = _get_provider_client()
    auth = {"Authorization": f"Bearer {token}"}

    try:
        resp = await provider_client.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}",
            headers=auth,
        )
        resp.raise_for_status()
        data = resp.json()

        raw_bytes = base64.urlsafe_b64decode(data.get("data", ""))
        size = len(raw_bytes)

        # Try to extract text content based on file type
        text_content = None

        # Plain text / CSV / code files
        try:
            text_content = raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            pass

        # PDF extraction
        if text_content and text_content.startswith("%PDF"):
            text_content = None  # Not useful as raw text, try pdfplumber
            try:
                import pdfplumber
                import io
                with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
                    pages = []
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            pages.append(page_text)
                    text_content = "\n\n".join(pages) if pages else "(PDF has no extractable text)"
            except Exception as e:
                text_content = f"(Could not extract PDF text: {e})"

        # Spreadsheet extraction (xlsx, xls, csv)
        if text_content is None:
            try:
                import io
                import pandas as pd
                df = pd.read_excel(io.BytesIO(raw_bytes))
                text_content = df.to_string(max_rows=200)
            except Exception:
                pass

        if text_content is None:
            text_content = f"(Binary file, {size} bytes — cannot extract text)"

        # Embed the extracted text for future semantic search (best-effort)
        await _embed_attachment_content(
            tenant_id=tenant_id,
            message_id=message_id,
            attachment_id=attachment_id,
            text_content=text_content,
        )

        return {
            "status": "success",
            "size": size,
            "content": text_content[:10000],
            "truncated": len(text_content) > 10000 if text_content else False,
            "account_email": account.get("email"),
        }

    except httpx.HTTPStatusError as e:
        return {"error": f"Gmail API error: {e.response.status_code} {e.response.text[:200]}"}
    except Exception as e:
        return {"error": f"Failed to download attachment: {str(e)}"}


async def send_email(
    tenant_id: str = "auto",
    to: str = "",
    subject: str = "",
    body: str = "",
    account_email: str = "",
) -> dict:
    """Send an email via Gmail or Outlook.

    Args:
        tenant_id: Tenant context. Use "auto" if unknown.
        to: Recipient email address.
        subject: Email subject line.
        body: Email body text (plain text).
        account_email: Specific email account to send from. If empty, uses default account.

    Returns:
        Dict with send status and message ID.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    if not to or not subject:
        return {"error": "Both 'to' and 'subject' are required."}

    account, error = await _resolve_email_account(tenant_id, account_email)
    if error:
        return {"error": error}

    integration_name = account["integration_name"]
    token = await _get_oauth_token(tenant_id, integration_name, account.get("email"))
    if not token:
        return {"error": f"{integration_name.title()} not connected. Ask the user to reconnect it in Connected Apps."}

    provider_client = _get_provider_client()
    auth = {"Authorization": f"Bearer {token}"}

    try:
        if integration_name == "gmail":
            message = MIMEText(body)
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

            resp = await provider_client.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers=auth,
                json={"raw": raw},
            )
            resp.raise_for_status()
            result = resp.json()

            return {
                "status": "success",
                "message_id": result.get("id"),
                "message": f"Email sent to {to}.",
                "provider": "google",
                "account_email": account.get("email"),
            }

        resp = await provider_client.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers={**auth, "Content-Type": "application/json"},
            json={
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "Text",
                        "content": body,
                    },
                    "toRecipients": [
                        {"emailAddress": {"address": to}},
                    ],
                },
                "saveToSentItems": True,
            },
        )
        resp.raise_for_status()
        return {
            "status": "success",
            "message_id": None,
            "message": f"Email sent to {to}.",
            "provider": "microsoft",
            "account_email": account.get("email"),
        }

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {"error": f"{integration_name.title()} token expired. Ask user to reconnect it."}
        return {"error": f"{integration_name.title()} send failed: {e.response.status_code}"}
    except Exception as e:
        logger.exception("send_email failed")
        return {"error": f"Failed to send email: {str(e)}"}


# ---------------------------------------------------------------------------
# Google Calendar tools
# ---------------------------------------------------------------------------

async def list_calendar_events(
    tenant_id: str = "auto",
    days_ahead: int = 7,
    max_results: int = 20,
    account_email: str = "",
) -> dict:
    """List upcoming Google Calendar events.

    Args:
        tenant_id: Tenant context. Use "auto" if unknown.
        days_ahead: Number of days to look ahead (1-30).
        max_results: Maximum events to return (1-50).
        account_email: Specific Google account for calendar. If empty, uses default.

    Returns:
        Dict with list of calendar events (summary, start, end, location).
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    token = await _get_oauth_token(tenant_id, "google_calendar", account_email or None)
    if not token:
        return {"error": "Google Calendar not connected. Ask user to connect Google in Connected Apps."}

    google = _get_provider_client()
    auth = {"Authorization": f"Bearer {token}"}

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=min(days_ahead, 30))).isoformat()

    try:
        resp = await google.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers=auth,
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": min(max_results, 50),
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        events = []
        for item in data.get("items", []):
            start = item.get("start", {})
            end = item.get("end", {})
            events.append({
                "id": item.get("id"),
                "summary": item.get("summary", "(no title)"),
                "start": start.get("dateTime", start.get("date", "")),
                "end": end.get("dateTime", end.get("date", "")),
                "location": item.get("location", ""),
                "description": (item.get("description", "") or "")[:200],
                "attendees": [a.get("email", "") for a in item.get("attendees", [])][:10],
            })

        return {"status": "success", "events": events, "count": len(events)}

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {"error": "Calendar token expired. Ask user to reconnect Google in Connected Apps."}
        return {"error": f"Calendar API error: {e.response.status_code}"}
    except Exception as e:
        logger.exception("list_calendar_events failed")
        return {"error": f"Failed to list events: {str(e)}"}


async def create_calendar_event(
    tenant_id: str = "auto",
    summary: str = "",
    start_time: str = "",
    end_time: str = "",
    description: str = "",
    attendees: str = "",
    account_email: str = "",
) -> dict:
    """Create a new Google Calendar event.

    Args:
        tenant_id: Tenant context. Use "auto" if unknown.
        summary: Event title/name.
        start_time: Start time in ISO 8601 format (e.g. "2026-03-15T10:00:00-05:00").
        end_time: End time in ISO 8601 format (e.g. "2026-03-15T11:00:00-05:00").
        description: Optional event description.
        attendees: Optional comma-separated list of attendee emails.
        account_email: Specific Google account for calendar. If empty, uses default.

    Returns:
        Dict with created event details.
    """
    tenant_id = _resolve_tenant_id(tenant_id)
    if not summary or not start_time or not end_time:
        return {"error": "summary, start_time, and end_time are required."}

    token = await _get_oauth_token(tenant_id, "google_calendar", account_email or None)
    if not token:
        return {"error": "Google Calendar not connected. Ask user to connect Google in Connected Apps."}

    google = _get_provider_client()
    auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    event_body = {
        "summary": summary,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time},
    }
    if description:
        event_body["description"] = description
    if attendees:
        event_body["attendees"] = [{"email": e.strip()} for e in attendees.split(",") if e.strip()]

    try:
        resp = await google.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers=auth,
            json=event_body,
        )
        resp.raise_for_status()
        created = resp.json()

        return {
            "status": "success",
            "event_id": created.get("id"),
            "summary": created.get("summary"),
            "start": created.get("start", {}).get("dateTime", ""),
            "end": created.get("end", {}).get("dateTime", ""),
            "link": created.get("htmlLink", ""),
            "message": f"Event '{summary}' created.",
        }

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            return {"error": "Calendar token expired. Ask user to reconnect Google."}
        return {"error": f"Calendar create failed: {e.response.status_code}"}
    except Exception as e:
        logger.exception("create_calendar_event failed")
        return {"error": f"Failed to create event: {str(e)}"}
