"""Generic flat CSV adapter — importable into anything.

This is the lowest-common-denominator format. Every accounting tool can
ingest a flat CSV; it's also the format CPAs commonly hand-edit before
re-importing. Column order is stable (round-trip tests depend on it).

Columns (per the 2026-05-09 plan):
    date, vendor, amount, gl_code, aaha_category, location, confidence,
    source_email_id

Plus two convenience columns the plan didn't enumerate but are useful
for downstream auditing without breaking the canonical importer
contract: `flagged_for_review` and `memo`.
"""

from __future__ import annotations

import csv
import io

from app.services.bookkeeper_exporters.types import (
    AAHATaxonomy,
    CategorizedLineItem,
    ExportResult,
    TenantExportMetadata,
)


CSV_COLUMNS = (
    "date",
    "vendor",
    "amount",
    "gl_code",
    "aaha_category",
    "location",
    "confidence",
    "source_email_id",
    "flagged_for_review",
    "memo",
)


def export(
    items: list[CategorizedLineItem],
    taxonomy: AAHATaxonomy,  # noqa: ARG001 — kept for adapter signature symmetry
    tenant_metadata: TenantExportMetadata,
) -> ExportResult:
    """Produce a flat CSV. Deterministic for a given input."""
    buf = io.StringIO()
    writer = csv.writer(buf, dialect="excel", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(CSV_COLUMNS)

    for item in items:
        writer.writerow([
            item.txn_date.isoformat(),
            item.vendor,
            f"{item.amount:.2f}",
            item.gl_code,
            item.aaha_category,
            item.location,
            f"{item.confidence:.4f}",
            item.source_email_id,
            "true" if item.flagged_for_review else "false",
            item.memo,
        ])

    content = buf.getvalue().encode("utf-8")
    filename = (
        f"{tenant_metadata.safe_practice_slug()}_AAHA_{tenant_metadata.period_slug()}.csv"
    )
    return ExportResult(content=content, filename=filename, mime_type="text/csv")
