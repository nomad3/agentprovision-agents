"""Tests for the tenant-health admin endpoint (Op-2).

Pinned invariants:
  - The curated row never exposes per-message detail (no message IDs,
    no raw chain) — same boundary as PRs #256, #263, #265, #267,
    #268, #269.
  - The endpoint is gated on superuser (cross-tenant exposure must
    not leak via a regular tenant-admin token).
  - Fields the cross-tenant table reads are stable; renaming any of
    them silently would break the operator UI.
"""
from app.api.v1.admin_tenant_health import (
    TenantHealthResponse,
    TenantHealthRow,
    list_tenant_health,
)


# ── Schema invariants ─────────────────────────────────────────────────


def test_row_no_message_id_leak():
    """The curated row is for triage. Per-message detail (IDs,
    contexts, raw chain) belongs in the tenant's own pages, not in
    this superuser cross-tenant view."""
    forbidden = {
        "messages",
        "message_ids",
        "raw",
        "raw_chain",
        "cli_chain_attempted",
        "context",
        "agent_ids",
    }
    assert forbidden.isdisjoint(TenantHealthRow.model_fields.keys())


def test_row_has_required_triage_fields():
    """The cross-tenant table reads these specific fields. Pinning the
    set so nobody silently renames a column out from under the UI."""
    keys = set(TenantHealthRow.model_fields.keys())
    expected = {
        "tenant_id",
        "tenant_name",
        "user_count",
        "active_agent_count",
        "turn_count_24h",
        "fallback_rate_24h",
        "chain_exhausted_24h",
        "last_activity_at",
        "primary_cli",
    }
    assert expected == keys


def test_response_minimal_shape():
    """Response is just (window_hours, rows). No pagination total, no
    cursor — tenant counts are operator-bounded so a single page is
    fine."""
    assert set(TenantHealthResponse.model_fields.keys()) == {
        "window_hours",
        "rows",
    }


def test_endpoint_is_superuser_gated():
    """Inspect the FastAPI dependency tree to confirm require_superuser
    is wired on the cross-tenant endpoint. A regression here would
    leak every tenant's chat volume + CLI usage to a regular tenant
    admin token."""
    sig = list_tenant_health.__annotations__
    # current_user dep type comes from a runtime Depends() default —
    # easier to assert against the wrapped function directly.
    import inspect
    src = inspect.getsource(list_tenant_health)
    assert "deps.require_superuser" in src, (
        "list_tenant_health must depend on deps.require_superuser; "
        "removing this gate exposes every tenant's CLI usage to "
        "non-superuser tokens."
    )


# ── Sanity ────────────────────────────────────────────────────────────


def test_fallback_rate_is_zero_to_one():
    """The schema description pins fallback_rate_24h to [0, 1]. Make
    sure the field is a float (not int) so downstream JSON consumers
    don't truncate 0.12 to 0."""
    field = TenantHealthRow.model_fields["fallback_rate_24h"]
    assert field.annotation is float


def test_last_activity_at_is_optional():
    """Stalled tenants — those with zero traffic in the window — must
    still get a row, with last_activity_at=None. The dashboard's whole
    point is to surface them."""
    field = TenantHealthRow.model_fields["last_activity_at"]
    # Optional[datetime] — annotation reduces to a Union type
    import typing
    args = typing.get_args(field.annotation)
    assert type(None) in args


def test_primary_cli_is_optional():
    """If a tenant had zero turns in the window, primary_cli is None
    rather than a misleading default like 'claude_code'."""
    field = TenantHealthRow.model_fields["primary_cli"]
    import typing
    args = typing.get_args(field.annotation)
    assert type(None) in args
