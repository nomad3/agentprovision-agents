"""Xero bank-statement CSV adapter.

Spec source: Xero Central's "Manually import a bank statement" guide
(https://central.xero.com/s/article/Manually-import-a-bank-statement),
which documents the bank-statement CSV columns Xero accepts. The
canonical column list is:

    *Date, *Amount, Payee, Description, Reference, Cheque Number

Stars (*) mark columns Xero requires; the others are optional but
strongly recommended because they show up in the Xero reconcile UI
the bookkeeper / CPA uses every week.

Date format: per Xero's UK/AU/NZ default, DD/MM/YYYY. Xero auto-detects
US locale tenants and accepts MM/DD/YYYY too — but the safe shipping
default is DD/MM/YYYY, since Xero's "ambiguous date" warning fires for
any row where day ≤ 12 and the locale is unknown. We use ISO-style
YYYY-MM-DD which Xero parses unambiguously regardless of locale (this
was the workaround Xero's own knowledge base recommends for multi-
locale CPA practices).

Amount sign convention:
   positive = money INTO the bank account (deposit / refund)
   negative = money OUT of the bank account (expense)

Our CategorizedLineItem uses the opposite sign (positive = expense),
so we flip on export.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from app.services.bookkeeper_exporters.types import (
    AAHATaxonomy,
    CategorizedLineItem,
    ExportResult,
    TenantExportMetadata,
)


# Note: leading "*" in headers is REQUIRED — Xero matches column names
# literally. Missing the asterisks causes Xero's import wizard to mis-map.
XERO_COLUMNS = (
    "*Date",
    "*Amount",
    "Payee",
    "Description",
    "Reference",
    "Cheque Number",
)


def _xero_date(d: date) -> str:
    """ISO-8601 — unambiguous across all Xero locales."""
    return d.isoformat()


def export(
    items: list[CategorizedLineItem],
    taxonomy: AAHATaxonomy,  # noqa: ARG001
    tenant_metadata: TenantExportMetadata,
) -> ExportResult:
    """Produce a Xero bank-statement CSV."""
    buf = io.StringIO()
    writer = csv.writer(buf, dialect="excel", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(XERO_COLUMNS)

    for item in items:
        # Xero sign convention: positive = bank deposit, negative = expense.
        # Our internal positive = expense, so we negate.
        xero_amount = -item.amount
        description_parts = [item.aaha_category]
        if item.gl_code:
            description_parts.append(f"GL {item.gl_code}")
        if item.memo:
            description_parts.append(item.memo)
        description = " | ".join(p for p in description_parts if p)

        writer.writerow([
            _xero_date(item.txn_date),
            f"{xero_amount:.2f}",
            item.vendor,
            description,
            item.reference,
            "",  # Cheque Number — not tracked in our line items
        ])

    content = buf.getvalue().encode("utf-8")
    filename = (
        f"{tenant_metadata.safe_practice_slug()}_AAHA_"
        f"{tenant_metadata.period_slug()}_xero.csv"
    )
    return ExportResult(
        content=content,
        filename=filename,
        mime_type="text/csv",
        line_item_count=len(items),
        format="xero_csv",
    )
