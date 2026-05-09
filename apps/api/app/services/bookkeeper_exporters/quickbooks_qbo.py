"""QuickBooks Online (QBO) bank-statement CSV adapter.

Spec source: Intuit's "Format CSV files in Excel to get bank
transactions into QuickBooks" support article
(https://quickbooks.intuit.com/learn-support/en-us/help-article/import-export-data/format-csv-file-import-bank-transactions-quickbooks-online/L8WQQEJjC_US_en_US),
specifically the "3-column" QBO bank-statement CSV import schema:

    Date, Description, Amount

QBO supports a 4-column variant (Date, Description, Credit, Debit) and
a 3-column variant (Date, Description, Amount). We use the 3-column
form because it round-trips cleanly to and from any single-column
Amount feed (positive = money out, negative = money in — QBO infers
the direction automatically when uploading to a bank/credit-card
register, then routes splits per the AAHA category we encode in
Description).

Date format: MM/DD/YYYY (US — QBO infers locale from the connected QBO
company file, but US locale is what every VMG-member CPA reads).

Description encodes:  "<vendor> | <AAHA category> [GL <gl>]"
so the CPA can sort/filter the imported register and bulk-categorize.
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


QBO_COLUMNS = ("Date", "Description", "Amount")


def _qbo_date(d: date) -> str:
    """QBO US-locale date format: MM/DD/YYYY (zero-padded)."""
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def _build_description(item: CategorizedLineItem) -> str:
    parts = [item.vendor.strip()]
    if item.aaha_category:
        parts.append(item.aaha_category.strip())
    if item.gl_code:
        parts.append(f"GL {item.gl_code}")
    if item.memo:
        parts.append(item.memo.strip())
    return " | ".join(p for p in parts if p)


def export(
    items: list[CategorizedLineItem],
    taxonomy: AAHATaxonomy,  # noqa: ARG001
    tenant_metadata: TenantExportMetadata,
) -> ExportResult:
    """Produce a QuickBooks Online importable bank-statement CSV (3-col)."""
    buf = io.StringIO()
    writer = csv.writer(buf, dialect="excel", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(QBO_COLUMNS)

    for item in items:
        writer.writerow([
            _qbo_date(item.txn_date),
            _build_description(item),
            f"{item.amount:.2f}",
        ])

    content = buf.getvalue().encode("utf-8")
    filename = (
        f"{tenant_metadata.safe_practice_slug()}_AAHA_"
        f"{tenant_metadata.period_slug()}_qbo.csv"
    )
    return ExportResult(
        content=content,
        filename=filename,
        mime_type="text/csv",
        line_item_count=len(items),
        format="quickbooks_qbo",
    )
