"""Server-side bootstrappers for `alpha quickstart` web wedges (PR-Q4b).

When the web onboarding picks a Gmail or Calendar wedge, the browser
can't reach the user's filesystem the way the CLI wedges can — it has
to ask the server to fetch from the connected OAuth account. These
bootstrappers do that fetch and emit items in the wire format that
the Q4 rule-based extractor (`training_ingestion._persist_item`)
already knows how to walk.

Item kinds emitted:
    gmail_message_summary      — one per recent inbox message
    calendar_event_summary     — one per upcoming event

Why a separate module instead of reusing `workflows/activities/inbox_monitor.py`:
The inbox_monitor helpers are `@activity.defn` Temporal activities
that future maintainers may decorate with `activity.heartbeat`
calls — calling them from a non-Temporal FastAPI request handler
would silently break the day someone adds heartbeat. Same auth
helper (`_get_google_token`) is reused; the HTTP loops are
re-implemented for the quickstart's smaller batch (10 emails / 15
events) and the differently-shaped wedge wire format.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

from app.workflows.activities.inbox_monitor import _get_google_token

logger = logging.getLogger(__name__)

# Bootstrap caps — small enough to stay under the Cloudflare 100s
# request timeout (each gmail message detail fetch is ~200ms; 10
# round-trips ≈ 2s) and large enough to give the rule-extractor
# useful person/project signal on a fresh tenant.
_GMAIL_MAX_MESSAGES = 10
_CALENDAR_MAX_EVENTS = 15


def bootstrap_gmail_items(db, tenant_id: str) -> List[Dict[str, Any]]:
    """Pull recent inbox messages and return wedge items.

    Returns an empty list when the tenant hasn't connected Gmail
    (no OAuth token), the API call errors, or the inbox is empty.
    Callers should NOT treat the empty-list case as failure — the
    web flow falls through to the stub item if we hand back nothing.

    Item shape (kind=gmail_message_summary):
        - subject: str        (the email subject line)
        - from_name: str      (sender display name, parsed from RFC 2822)
        - from_email: str     (sender email address)
        - date_iso: str       (RFC 2822 Date header, raw — the extractor
                               normalises if needed)
        - labels: list[str]   (Gmail label IDs the message has)
    """
    token = _get_google_token(db, tenant_id, "gmail")
    if not token:
        logger.info("bootstrap_gmail_items: no token for tenant=%s", tenant_id[:8])
        return []

    try:
        with httpx.Client(timeout=30.0) as client:
            # List recent message IDs.
            list_resp = client.get(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={"maxResults": _GMAIL_MAX_MESSAGES, "q": "newer_than:7d"},
            )
            if list_resp.status_code != 200:
                logger.warning(
                    "bootstrap_gmail_items: list api %s for tenant=%s",
                    list_resp.status_code,
                    tenant_id[:8],
                )
                return []
            message_ids = [m["id"] for m in list_resp.json().get("messages", [])]
            if not message_ids:
                return []

            # Fetch details — we only need headers + labels, not the body.
            items: List[Dict[str, Any]] = []
            for msg_id in message_ids:
                detail = client.get(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{msg_id}",
                    headers={"Authorization": f"Bearer {token}"},
                    # `metadata` format skips the body bytes entirely —
                    # smaller payload + faster than `full`. The
                    # extractor doesn't need body text for Q4b.
                    params={
                        "format": "metadata",
                        "metadataHeaders": ["Subject", "From", "Date"],
                    },
                )
                if detail.status_code != 200:
                    continue
                md = detail.json()
                headers_list = md.get("payload", {}).get("headers", [])
                hdrs = {h["name"]: h["value"] for h in headers_list}
                from_raw = hdrs.get("From", "")
                from_name, from_email = _parse_rfc2822_address(from_raw)
                items.append({
                    "kind": "gmail_message_summary",
                    "subject": hdrs.get("Subject", "") or "(no subject)",
                    "from_name": from_name,
                    "from_email": from_email,
                    "date_iso": hdrs.get("Date", ""),
                    "labels": md.get("labelIds", []) or [],
                })
            return items
    except Exception as exc:
        # Bootstrap is best-effort — never raise into the API handler.
        # An empty list lets the training run complete cleanly (the
        # extractor sees 0 items, writes a 'no items recognised'
        # outcome) instead of 500'ing the bulk-ingest endpoint.
        logger.exception(
            "bootstrap_gmail_items failed for tenant=%s: %s",
            tenant_id[:8],
            exc,
        )
        return []


def bootstrap_calendar_items(db, tenant_id: str) -> List[Dict[str, Any]]:
    """Pull upcoming calendar events and return wedge items.

    Same best-effort contract as gmail: empty list on missing token
    or API error; never raises.

    Item shape (kind=calendar_event_summary):
        - summary: str             (event title)
        - start_iso: str           (RFC 3339 — dateTime or date)
        - end_iso: str
        - location: str
        - attendee_emails: list[str]  (capped at 10)
        - organizer_email: str
    """
    token = _get_google_token(db, tenant_id, "google_calendar")
    if not token:
        logger.info("bootstrap_calendar_items: no token for tenant=%s", tenant_id[:8])
        return []

    try:
        now = datetime.now(timezone.utc)
        # Wider window than inbox-monitor (which uses 24h) — quickstart
        # wants a sense of the user's week, not just today.
        time_min = now.isoformat()
        time_max = (now + timedelta(days=14)).isoformat()
        with httpx.Client(timeout=30.0) as client:
            resp = client.get(
                "https://www.googleapis.com/calendar/v3/calendars/primary/events",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "maxResults": _CALENDAR_MAX_EVENTS,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "bootstrap_calendar_items: api %s for tenant=%s",
                    resp.status_code,
                    tenant_id[:8],
                )
                return []
            items: List[Dict[str, Any]] = []
            for ev in resp.json().get("items", []):
                start = ev.get("start", {}) or {}
                end = ev.get("end", {}) or {}
                attendees = [
                    a.get("email", "")
                    for a in (ev.get("attendees") or [])
                    if a.get("email")
                ][:10]
                items.append({
                    "kind": "calendar_event_summary",
                    "summary": ev.get("summary", "") or "(no title)",
                    "start_iso": start.get("dateTime") or start.get("date") or "",
                    "end_iso": end.get("dateTime") or end.get("date") or "",
                    "location": ev.get("location", "") or "",
                    "attendee_emails": attendees,
                    "organizer_email": (ev.get("organizer") or {}).get("email", "") or "",
                })
            return items
    except Exception as exc:
        logger.exception(
            "bootstrap_calendar_items failed for tenant=%s: %s",
            tenant_id[:8],
            exc,
        )
        return []


def _parse_rfc2822_address(raw: str) -> tuple[str, str]:
    """Parse `'Alice <a@x.com>'` → `('Alice', 'a@x.com')`.

    Falls back to `(raw, raw)` when the input is just a bare email
    (`a@x.com` → `('', 'a@x.com')`) or unparseable. Uses Python's
    `email.utils.parseaddr` so RFC 2822 corner-cases (quoted display
    names, IDN domains) are handled by the stdlib rather than by us.
    """
    try:
        from email.utils import parseaddr
        name, addr = parseaddr(raw or "")
        return (name or "", addr or "")
    except Exception:
        return ("", raw or "")
