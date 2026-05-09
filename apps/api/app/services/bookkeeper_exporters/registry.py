"""Registry of bookkeeper export-format adapters.

Looks up an adapter module by `tenant_features.cpa_export_format` value.
Each adapter exposes a top-level `export(items, taxonomy, tenant_meta)`
function returning `ExportResult`.

Adding a new adapter:
  1. Drop a module in `apps/api/app/services/bookkeeper_exporters/`
  2. Implement `export(...)` matching the shared signature
  3. Add an entry below
  4. Add an option in `apps/web/src/components/CpaExportFormatSelector.js`

The registry deliberately stays in code (not in DB) because each
adapter is a code artifact — adding a row to a config table without
shipping the matching module would silently break exports.
"""

from __future__ import annotations

from types import ModuleType
from typing import Callable, Iterable

from app.services.bookkeeper_exporters import (
    csv as csv_adapter,
    quickbooks_iif as qb_iif_adapter,
    quickbooks_qbo as qbo_adapter,
    sage_intacct_csv as sage_adapter,
    xero_csv as xero_adapter,
    xlsx as xlsx_adapter,
)
from app.services.bookkeeper_exporters.types import (
    AAHATaxonomy,
    CategorizedLineItem,
    ExportResult,
    TenantExportMetadata,
)


# format_key -> adapter module (each module exports `export(...)`)
_ADAPTERS: dict[str, ModuleType] = {
    "xlsx":             xlsx_adapter,
    "csv":              csv_adapter,
    "quickbooks_iif":   qb_iif_adapter,
    "quickbooks_qbo":   qbo_adapter,
    "xero_csv":         xero_adapter,
    "sage_intacct_csv": sage_adapter,
}

# Stable iteration order for UIs / docs / tests. Matches the dropdown
# order in the web Integrations panel.
SUPPORTED_FORMATS: tuple[str, ...] = (
    "xlsx",
    "csv",
    "quickbooks_iif",
    "quickbooks_qbo",
    "xero_csv",
    "sage_intacct_csv",
)


# Adapter callable signature. Useful as a type alias for hint clarity.
ExporterFn = Callable[
    [list[CategorizedLineItem], AAHATaxonomy, TenantExportMetadata],
    ExportResult,
]


def is_supported_format(fmt: str) -> bool:
    return fmt in _ADAPTERS


def get_adapter(fmt: str) -> ExporterFn:
    """Return the `export(...)` function for the given format key.

    Raises `ValueError` for unknown formats — the caller (MCP tool) is
    responsible for falling back to the tenant default or to xlsx.
    """
    if fmt not in _ADAPTERS:
        raise ValueError(
            f"Unsupported CPA export format '{fmt}'. "
            f"Supported: {', '.join(SUPPORTED_FORMATS)}"
        )
    return _ADAPTERS[fmt].export


def all_adapters() -> Iterable[tuple[str, ExporterFn]]:
    """Yield (format_key, exporter_fn) in canonical order — for tests."""
    for fmt in SUPPORTED_FORMATS:
        yield fmt, _ADAPTERS[fmt].export
