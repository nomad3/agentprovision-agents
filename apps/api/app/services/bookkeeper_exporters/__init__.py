"""Bookkeeper export-format adapters.

The Veterinary Bookkeeper Agent categorizes line items against the AAHA
Chart of Accounts (the canonical taxonomy that every VMG-member CPA
understands). AAHA is the *source of truth*. These adapters convert the
already-categorized rows into whichever file format the practice's CPA
imports — XLSX, generic CSV, QuickBooks IIF, QuickBooks Online CSV,
Xero CSV, or Sage Intacct CSV.

One format per tenant, configured via `tenant_features.cpa_export_format`.

All adapters share the same signature:

    def export(
        items: list[CategorizedLineItem],
        taxonomy: AAHATaxonomy,
        tenant_metadata: TenantExportMetadata,
    ) -> ExportResult

`ExportResult` is `(bytes, filename, mime_type)`. Adapters MUST be
deterministic for a given input — round-trip tests rely on it.

The adapter registry lives in `registry.py`. Look up by format key:

    from app.services.bookkeeper_exporters import get_adapter
    adapter = get_adapter("quickbooks_iif")
    result = adapter.export(items, taxonomy, tenant_meta)
"""

from app.services.bookkeeper_exporters.types import (
    AAHATaxonomy,
    AAHATaxonomyLeaf,
    CategorizedLineItem,
    ExportResult,
    TenantExportMetadata,
)
from app.services.bookkeeper_exporters.registry import (
    SUPPORTED_FORMATS,
    get_adapter,
    is_supported_format,
)

__all__ = [
    "AAHATaxonomy",
    "AAHATaxonomyLeaf",
    "CategorizedLineItem",
    "ExportResult",
    "TenantExportMetadata",
    "SUPPORTED_FORMATS",
    "get_adapter",
    "is_supported_format",
]
