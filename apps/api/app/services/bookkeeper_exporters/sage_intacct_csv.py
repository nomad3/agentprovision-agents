"""Sage Intacct GL-import CSV adapter.

Spec source: Sage Intacct's published GL-journal-entry CSV import
template (Sage Intacct Help Center → "Import journal entries"). The
canonical column header set for a GL journal entry import is:

    Batch Title, Batch Date, Journal, GL Account No, Memo, Debit,
    Amount, Department, Location, Currency, Vendor

Sage Intacct's import is an LL (line-level) journal: every CSV row is
one journal-entry split. Debits and credits must balance per Batch
Title (the "batch" groups all rows with the same Batch Title into one
journal entry).

Our convention: one CategorizedLineItem → two CSV rows (the two halves
of a balanced journal entry). For an expense:
   - Debit  the AAHA expense account (positive Debit)
   - Credit the bank/clearing account (positive credit)

Sage Intacct's CSV is more verbose than QBO/Xero because Sage is the
mid-market option — accountants who pick Sage want the full DR/CR
audit trail, not the bank-feed shortcut.

Notes:
- Currency defaults to the tenant's `base_currency` (USD for VMG-US).
- "Department" is unused in our row shape (single-clinic tenants); we
  leave it blank and let the CPA's Sage import map it from Location.
- Sage rejects journal entries where Debit total != Credit total per
  Batch Title; round-trip test asserts balance.
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


SAGE_COLUMNS = (
    "Batch Title",
    "Batch Date",
    "Journal",
    "GL Account No",
    "Memo",
    "Debit",
    "Credit",
    "Department",
    "Location",
    "Currency",
    "Vendor",
)

# A reasonable default GL account number for the bank-clearing side of
# every journal entry. Sage Intacct tenants typically have an "Operating
# bank" cash account near 1010; if a CPA uses a different code they can
# bulk-edit the CSV before import.
DEFAULT_BANK_GL_ACCOUNT = "1010"
DEFAULT_JOURNAL_CODE = "GJ"  # General Journal


def _sage_date(d: date) -> str:
    """Sage Intacct accepts ISO-8601 unambiguously across locales."""
    return d.isoformat()


def _amount(v: float) -> str:
    return f"{abs(v):.2f}"


def export(
    items: list[CategorizedLineItem],
    taxonomy: AAHATaxonomy,  # noqa: ARG001
    tenant_metadata: TenantExportMetadata,
) -> ExportResult:
    """Produce a Sage Intacct GL-import CSV.

    Each CategorizedLineItem becomes one balanced journal entry (one
    batch title) with two rows — the AAHA expense leg and the cash leg.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, dialect="excel", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(SAGE_COLUMNS)

    currency = tenant_metadata.base_currency

    for idx, item in enumerate(items, start=1):
        batch_title = f"AAHA-{tenant_metadata.period_slug()}-{idx:04d}"
        batch_date = _sage_date(item.txn_date)
        memo_parts = [item.aaha_category]
        if item.memo:
            memo_parts.append(item.memo)
        memo = " | ".join(p for p in memo_parts if p)

        # Convention used here:
        #   amount > 0 → expense → DEBIT the GL account, CREDIT the bank
        #   amount < 0 → refund   → CREDIT the GL account, DEBIT the bank
        if item.amount >= 0:
            gl_debit = _amount(item.amount)
            gl_credit = ""
            bank_debit = ""
            bank_credit = _amount(item.amount)
        else:
            gl_debit = ""
            gl_credit = _amount(item.amount)
            bank_debit = _amount(item.amount)
            bank_credit = ""

        # Row 1 — GL/AAHA expense leg
        writer.writerow([
            batch_title,
            batch_date,
            DEFAULT_JOURNAL_CODE,
            item.gl_code,
            memo,
            gl_debit,
            gl_credit,
            "",                # Department
            item.location,     # Location
            currency,
            item.vendor,
        ])
        # Row 2 — bank/cash leg
        writer.writerow([
            batch_title,
            batch_date,
            DEFAULT_JOURNAL_CODE,
            DEFAULT_BANK_GL_ACCOUNT,
            memo,
            bank_debit,
            bank_credit,
            "",
            item.location,
            currency,
            item.vendor,
        ])

    content = buf.getvalue().encode("utf-8")
    filename = (
        f"{tenant_metadata.safe_practice_slug()}_AAHA_"
        f"{tenant_metadata.period_slug()}_sage.csv"
    )
    return ExportResult(
        content=content,
        filename=filename,
        mime_type="text/csv",
        line_item_count=len(items),
        format="sage_intacct_csv",
    )
