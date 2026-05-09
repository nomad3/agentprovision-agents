"""QuickBooks Desktop IIF (Intuit Interchange Format) adapter.

Spec source: Intuit's published IIF reference
(https://quickbooks.intuit.com/learn-support/en-us/help-article/import-export-data/format-iif-files-import-quickbooks-desktop/L7emnvXSc_US_en_US),
cross-checked against the well-trodden third-party guides for IIF that
veterinary CPAs use when handing files between QuickBooks Desktop and
QuickBooks for Mac.

IIF is a tab-separated text file. Each block has three logical sections,
each opened by a `!`-prefixed header line:

    !TRNS  ...header columns for each transaction...
    !SPL   ...header columns for each transaction split...
    !ENDTRNS

Then for every transaction:

    TRNS  <fields>
    SPL   <fields one or many — one per AAHA category>
    SPL   ...
    ENDTRNS

For our purposes one categorized line item = one TRNS with two SPLs:
   - SPL #1: the AAHA-categorized expense account (debit)
   - SPL #2: the cash/bank clearing account (credit, balancing)

QuickBooks IIF is line-ending-sensitive — newlines must be CRLF on
Desktop import. Files with LF-only line endings get rejected silently.

Reference: AAHA leaf names map 1:1 to QuickBooks "Account:Sub-account"
form via `top_level:leaf_name`. Tenants with a custom QB chart can
later override via a per-tenant GL-code → QB-account mapping table
(out of scope for this PR).
"""

from __future__ import annotations

import io
from datetime import date

from app.services.bookkeeper_exporters.types import (
    AAHATaxonomy,
    CategorizedLineItem,
    ExportResult,
    TenantExportMetadata,
)


CLEARING_ACCOUNT = "Bank Clearing"
LINE_END = "\r\n"  # Intuit IIF expects CRLF


# IIF header rows. Field set is the practical-minimum subset that works
# in modern QuickBooks Desktop / QB for Mac without rejection.
TRNS_HEADER = (
    "!TRNS",
    "TRNSID",
    "TRNSTYPE",
    "DATE",
    "ACCNT",
    "NAME",
    "AMOUNT",
    "DOCNUM",
    "MEMO",
)

SPL_HEADER = (
    "!SPL",
    "SPLID",
    "TRNSTYPE",
    "DATE",
    "ACCNT",
    "NAME",
    "AMOUNT",
    "DOCNUM",
    "MEMO",
)

ENDTRNS_HEADER = ("!ENDTRNS",)


def _iif_date(d: date) -> str:
    """IIF date format: MM/DD/YYYY zero-padded.

    Intuit's published IIF reference (and the QBO CSV adapter we ship)
    use zero-padded dates. The original adapter used unpadded values
    (`5/8/2026`) which some QuickBooks Desktop versions tolerate but
    the canonical importer expects `05/08/2026`. Aligning with QBO +
    Intuit's spec — review feedback PR #331 Critical #3.
    """
    return f"{d.month:02d}/{d.day:02d}/{d.year}"


def _iif_amount(amount: float) -> str:
    """IIF expects 2-decimal numerics, no currency symbol, no thousands separator."""
    return f"{amount:.2f}"


def _iif_safe(value: str) -> str:
    """Tabs and newlines break IIF parsing — strip them."""
    if value is None:
        return ""
    return (
        str(value)
        .replace("\t", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .strip()
    )


def _qb_account_name(item: CategorizedLineItem, taxonomy: AAHATaxonomy) -> str:
    """Resolve the QuickBooks account for an AAHA category.

    QuickBooks account paths use ':' to separate parent from sub. We map
    AAHA top-level (e.g. PERSONNEL) to the QB parent account and the leaf
    name to the QB sub-account.
    """
    leaf = taxonomy.by_name(item.aaha_category)
    if leaf is None:
        # Unmapped — push into a single "Uncategorized" parent the CPA
        # can re-classify rather than silently failing import.
        return "Uncategorized:" + _iif_safe(item.aaha_category)
    return f"{leaf.top_level}:{_iif_safe(leaf.name)}"


def export(
    items: list[CategorizedLineItem],
    taxonomy: AAHATaxonomy,
    tenant_metadata: TenantExportMetadata,
) -> ExportResult:
    """Produce a QuickBooks Desktop IIF file."""
    buf = io.StringIO()
    # Header block — must come first, exactly once.
    buf.write("\t".join(TRNS_HEADER) + LINE_END)
    buf.write("\t".join(SPL_HEADER) + LINE_END)
    buf.write("\t".join(ENDTRNS_HEADER) + LINE_END)

    for idx, item in enumerate(items, start=1):
        trns_id = str(idx)
        spl_id = str(idx) + "01"
        trns_type = "CHECK" if item.amount > 0 else "DEPOSIT"
        date_str = _iif_date(item.txn_date)
        vendor = _iif_safe(item.vendor)
        memo = _iif_safe(item.memo) or _iif_safe(item.aaha_category)
        docnum = _iif_safe(item.reference)
        category_account = _qb_account_name(item, taxonomy)

        # The TRNS row hits the bank/clearing side. IIF convention:
        # TRNS amount is the bank-side movement (negative for an expense
        # leaving the bank), SPL amount is the equal-and-opposite side
        # going to the expense account.
        trns_amount = _iif_amount(-item.amount)
        spl_amount = _iif_amount(item.amount)

        buf.write(
            "\t".join([
                "TRNS",
                trns_id,
                trns_type,
                date_str,
                CLEARING_ACCOUNT,
                vendor,
                trns_amount,
                docnum,
                memo,
            ])
            + LINE_END
        )
        buf.write(
            "\t".join([
                "SPL",
                spl_id,
                trns_type,
                date_str,
                category_account,
                vendor,
                spl_amount,
                docnum,
                memo,
            ])
            + LINE_END
        )
        buf.write("ENDTRNS" + LINE_END)

    content = buf.getvalue().encode("utf-8")
    filename = (
        f"{tenant_metadata.safe_practice_slug()}_AAHA_"
        f"{tenant_metadata.period_slug()}.iif"
    )
    return ExportResult(
        content=content,
        filename=filename,
        mime_type="application/iif",
        line_item_count=len(items),
        format="quickbooks_iif",
    )
