"""Tests for the bookkeeper_export service entry-point.

Exercises the parts that DON'T need a DB: taxonomy loading from the
canonical YAML, and the format resolver when given an explicit format.
The DB-backed paths (load_categorized_items, resolve_format that hits
tenant_features) are integration-tested separately.
"""

from __future__ import annotations

import pytest

from app.services.bookkeeper_export import (
    DEFAULT_TAXONOMY_PATH,
    load_taxonomy,
    resolve_format,
)
from app.services.bookkeeper_exporters import SUPPORTED_FORMATS


def test_taxonomy_yaml_exists_and_is_loadable():
    """The seed YAML must be reachable from this module — the export
    pipeline depends on it. Catches refactors that break the relative
    path."""
    assert DEFAULT_TAXONOMY_PATH.exists(), (
        f"AAHA taxonomy YAML must exist at {DEFAULT_TAXONOMY_PATH}"
    )
    taxonomy = load_taxonomy()
    assert taxonomy.leaves, "Taxonomy must have at least one leaf"


def test_taxonomy_has_88_leaves():
    """Plan-stated invariant: the taxonomy ships 88 leaf categories.
    Catches accidental edits that lose categories without a version
    bump."""
    taxonomy = load_taxonomy()
    assert len(taxonomy.leaves) == 88, (
        f"Expected 88 AAHA leaves, got {len(taxonomy.leaves)}"
    )


def test_taxonomy_lookups_work():
    taxonomy = load_taxonomy()
    # Pick a known leaf from the YAML
    leaf = taxonomy.by_name("Professional services - DVM exam")
    assert leaf is not None
    assert leaf.gl_code == "4100"
    assert leaf.top_level == "REVENUE"

    # by_gl_code round-trip
    leaf2 = taxonomy.by_gl_code("4100")
    assert leaf2 is not None
    assert leaf2.name == "Professional services - DVM exam"


def test_resolve_format_explicit_pass_through():
    """Explicit format wins regardless of DB state — verified without a
    DB session by passing None for the resolver and asserting on the
    explicit path's early-return."""
    # We never hit the DB because the explicit value is recognized and
    # returned before the DB lookup.
    for fmt in SUPPORTED_FORMATS:
        assert resolve_format(db=None, tenant_id=None, explicit=fmt) == fmt


def test_resolve_format_explicit_unknown_raises():
    with pytest.raises(ValueError):
        resolve_format(db=None, tenant_id=None, explicit="not_a_real_format")
