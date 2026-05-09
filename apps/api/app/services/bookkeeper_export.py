"""Service entry point for the AAHA-categorized bookkeeper export.

The Veterinary Bookkeeper Agent writes categorized line items as
knowledge `observations` tagged with the AAHA leaf entity. This service
loads those observations for a period, joins them against the canonical
AAHA taxonomy, resolves the tenant's preferred CPA export format, and
dispatches to the matching adapter in
`app.services.bookkeeper_exporters`.

The taxonomy itself is loaded directly from
`docs/data/aha-chart-of-accounts/2026-05-09-canonical-taxonomy.yaml` so
the export pipeline doesn't depend on the knowledge-graph seed having
run. (The seed is a *propagation* of the YAML into the knowledge graph
for the Bookkeeper Agent's recall path; the file is the source of
truth.)
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.bookkeeper_exporters import (
    AAHATaxonomy,
    AAHATaxonomyLeaf,
    CategorizedLineItem,
    ExportResult,
    SUPPORTED_FORMATS,
    TenantExportMetadata,
    get_adapter,
    is_supported_format,
)
from app.services.features import get_or_create_features

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Taxonomy loading
# ---------------------------------------------------------------------------

# Repo-relative path to the canonical YAML. The repo layout is stable
# enough that resolving against the apps/api root works in dev,
# Kubernetes (the API container has the repo mounted at /app), and
# tests (the source tree).
_THIS = Path(__file__).resolve()
_REPO_ROOT_FROM_API = _THIS.parent.parent.parent.parent.parent  # apps/api/app/services -> repo root
DEFAULT_TAXONOMY_PATH = (
    _REPO_ROOT_FROM_API
    / "docs"
    / "data"
    / "aha-chart-of-accounts"
    / "2026-05-09-canonical-taxonomy.yaml"
)


def load_taxonomy(path: Optional[Path] = None) -> AAHATaxonomy:
    """Load the AAHA canonical taxonomy from YAML.

    Cached by argument identity at the call-site is fine — adapters
    are pure, the file is small, and re-loading per export is cheap
    relative to the I/O the rest of the pipeline does.
    """
    import yaml  # local import: pyyaml is already a transitive dep

    path = path or DEFAULT_TAXONOMY_PATH
    if not Path(path).exists():
        # Fallback for the in-container layout where /app == apps/api
        in_container = Path(
            "/app/../docs/data/aha-chart-of-accounts/2026-05-09-canonical-taxonomy.yaml"
        ).resolve()
        if in_container.exists():
            path = in_container
        else:
            raise FileNotFoundError(f"AAHA taxonomy YAML not found at {path}")

    with open(path) as fh:
        doc = yaml.safe_load(fh)

    leaves: list[AAHATaxonomyLeaf] = []
    for top_block in doc.get("categories", []):
        top_level = top_block.get("top_level", "")
        for leaf in top_block.get("subcategories", []):
            leaves.append(
                AAHATaxonomyLeaf(
                    name=leaf["name"],
                    gl_code=str(leaf.get("gl_code", "")),
                    top_level=top_level,
                    description=leaf.get("description", ""),
                )
            )
    return AAHATaxonomy(leaves=tuple(leaves))


# ---------------------------------------------------------------------------
# Observations → CategorizedLineItem
# ---------------------------------------------------------------------------

def load_categorized_items(
    db: Session,
    tenant_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> list[CategorizedLineItem]:
    """Pull bookkeeper-tagged observations from the knowledge graph for a period.

    The Bookkeeper Agent records each categorized line item as one
    `knowledge_observations` row whose `attributes` JSON carries the
    line-item shape:

        {
          "kind": "bookkeeper_line_item",
          "txn_date": "2026-05-08",
          "vendor": "Patterson Veterinary",
          "amount": 142.55,
          "aaha_category": "Drugs and medical supplies",
          "gl_code": "5210",
          "location": "Northgate",
          "confidence": 0.92,
          "flagged_for_review": false,
          "source_email_id": "<gmail msg id>",
          "memo": "...",
          "reference": "INV 12345"
        }

    Returns an empty list when no observations exist — the export
    adapter still produces a valid (empty) file.
    """
    rows = db.execute(
        text(
            """
            SELECT attributes
              FROM knowledge_observations
             WHERE tenant_id = :tid
               AND deleted_at IS NULL
               AND attributes->>'kind' = 'bookkeeper_line_item'
               AND (attributes->>'txn_date')::date BETWEEN :ps AND :pe
             ORDER BY (attributes->>'txn_date')::date ASC,
                      (attributes->>'vendor') ASC
            """
        ),
        {"tid": str(tenant_id), "ps": period_start, "pe": period_end},
    ).fetchall()

    items: list[CategorizedLineItem] = []
    for (attrs,) in rows:
        if not attrs:
            continue
        try:
            items.append(
                CategorizedLineItem(
                    txn_date=datetime.fromisoformat(attrs["txn_date"]).date()
                    if isinstance(attrs["txn_date"], str)
                    else attrs["txn_date"],
                    vendor=attrs.get("vendor", ""),
                    amount=float(attrs.get("amount", 0.0)),
                    aaha_category=attrs.get("aaha_category", ""),
                    gl_code=str(attrs.get("gl_code", "")),
                    location=attrs.get("location", ""),
                    confidence=float(attrs.get("confidence", 1.0)),
                    flagged_for_review=bool(attrs.get("flagged_for_review", False)),
                    source_email_id=attrs.get("source_email_id", ""),
                    memo=attrs.get("memo", ""),
                    reference=attrs.get("reference", ""),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Skipping malformed bookkeeper observation for tenant %s: %s",
                tenant_id,
                exc,
            )
            continue
    return items


# ---------------------------------------------------------------------------
# Format resolution
# ---------------------------------------------------------------------------

def resolve_format(
    db: Session,
    tenant_id: uuid.UUID,
    explicit: Optional[str] = None,
) -> str:
    """Pick the export format.

    Priority:
      1. `explicit` arg if it's a recognized format
      2. `tenant_features.cpa_export_format` for the tenant
      3. Default to "xlsx"

    Unknown explicit values raise ValueError so the caller surfaces a
    clear error to the user instead of silently exporting the wrong
    format.
    """
    if explicit:
        if not is_supported_format(explicit):
            raise ValueError(
                f"Unsupported CPA export format '{explicit}'. "
                f"Supported: {', '.join(SUPPORTED_FORMATS)}"
            )
        return explicit

    features = get_or_create_features(db, tenant_id)
    fmt = getattr(features, "cpa_export_format", None) or "xlsx"
    if not is_supported_format(fmt):
        logger.warning(
            "Tenant %s has unrecognized cpa_export_format=%r; falling back to xlsx",
            tenant_id,
            fmt,
        )
        return "xlsx"
    return fmt


# ---------------------------------------------------------------------------
# Top-level export
# ---------------------------------------------------------------------------

def export_aaha(
    db: Session,
    tenant_id: uuid.UUID,
    period_start: date,
    period_end: date,
    practice_name: str = "Practice",
    locations: Optional[tuple[str, ...]] = None,
    format: Optional[str] = None,            # noqa: A002 — domain-specific name
    items: Optional[list[CategorizedLineItem]] = None,
    taxonomy: Optional[AAHATaxonomy] = None,
) -> ExportResult:
    """Export AAHA-categorized bookkeeper rows for a period.

    Loads the taxonomy + line items if the caller didn't supply them
    (the test harness supplies fixtures directly to skip the DB).
    """
    fmt = resolve_format(db, tenant_id, explicit=format)
    if taxonomy is None:
        taxonomy = load_taxonomy()
    if items is None:
        items = load_categorized_items(db, tenant_id, period_start, period_end)

    # Auto-derive locations when the caller didn't pass an explicit
    # tuple — useful for multi-location practices that haven't yet
    # registered their locations in tenant metadata.
    if locations is None:
        seen: list[str] = []
        for it in items:
            if it.location and it.location not in seen:
                seen.append(it.location)
        locations = tuple(seen)

    tenant_meta = TenantExportMetadata(
        tenant_id=str(tenant_id),
        practice_name=practice_name,
        period_start=period_start,
        period_end=period_end,
        locations=locations,
    )

    adapter = get_adapter(fmt)
    return adapter(items, taxonomy, tenant_meta)
