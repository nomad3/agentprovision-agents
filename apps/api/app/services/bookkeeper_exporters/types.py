"""Shared dataclasses for bookkeeper export adapters.

All adapters consume:
  - `list[CategorizedLineItem]`   — the rows the Bookkeeper Agent
                                     emitted after AAHA categorization
  - `AAHATaxonomy`                 — the AAHA-aligned chart of accounts
                                     (top-level → leaf, including GL
                                     codes), already loaded from the
                                     canonical YAML or knowledge graph
  - `TenantExportMetadata`         — tenant-side context (practice name,
                                     period, locations) the adapter
                                     needs to format the output file

All adapters return `ExportResult = (bytes, filename, mime_type)`.

These dataclasses are intentionally kept dependency-free (no SQLAlchemy)
so adapters are pure functions over inputs and trivial to unit-test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class AAHATaxonomyLeaf:
    """One leaf category in the AAHA Chart of Accounts.

    Mirrors the structure in
    `docs/data/aha-chart-of-accounts/2026-05-09-canonical-taxonomy.yaml`.
    """

    name: str
    gl_code: str
    top_level: str
    description: str = ""


@dataclass(frozen=True)
class AAHATaxonomy:
    """Canonical AAHA taxonomy as a flat lookup keyed by leaf name."""

    leaves: tuple[AAHATaxonomyLeaf, ...]

    def by_name(self, name: str) -> Optional[AAHATaxonomyLeaf]:
        for leaf in self.leaves:
            if leaf.name == name:
                return leaf
        return None

    def by_gl_code(self, gl_code: str) -> Optional[AAHATaxonomyLeaf]:
        for leaf in self.leaves:
            if leaf.gl_code == gl_code:
                return leaf
        return None


@dataclass(frozen=True)
class CategorizedLineItem:
    """One categorized financial line item (the Bookkeeper Agent's output).

    The Bookkeeper Agent reads bank/card statements + vendor invoices,
    matches each line against the AAHA leaf set, and emits one of these
    per line. `aaha_category` is the leaf NAME (matches
    `AAHATaxonomyLeaf.name`); `gl_code` is the resolved 4-digit code.
    """

    txn_date: date
    vendor: str
    amount: float                       # positive = expense / debit; negative = refund / credit
    aaha_category: str                  # AAHA leaf name (canonical)
    gl_code: str                        # resolved from AAHA leaf
    location: str = ""                  # practice location label (one or many per tenant)
    confidence: float = 1.0             # categorizer confidence 0-1
    flagged_for_review: bool = False    # below-floor confidence or new-vendor flag
    source_email_id: str = ""           # gmail msg id, statement file id, etc.
    memo: str = ""                      # original memo / description
    reference: str = ""                 # check number, invoice number, etc.


@dataclass(frozen=True)
class TenantExportMetadata:
    """Tenant-side context an adapter needs to format the output file."""

    tenant_id: str
    practice_name: str
    period_start: date
    period_end: date
    locations: tuple[str, ...] = field(default_factory=tuple)
    base_currency: str = "USD"

    def safe_practice_slug(self) -> str:
        return "".join(
            c if c.isalnum() else "_" for c in self.practice_name
        ).strip("_") or "practice"

    def period_slug(self) -> str:
        return f"{self.period_start.isoformat()}_{self.period_end.isoformat()}"


@dataclass(frozen=True)
class ExportResult:
    """The bytes + metadata an adapter returns."""

    content: bytes
    filename: str
    mime_type: str
