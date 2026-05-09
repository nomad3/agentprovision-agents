#!/usr/bin/env python3
"""Idempotent seed for the AAHA Chart of Accounts canonical taxonomy.

Loads docs/data/aha-chart-of-accounts/2026-05-09-canonical-taxonomy.yaml
into the tenant's knowledge graph as `account_category` entities under
the existing `AHA Chart of Accounts` reference entity, embeds each leaf
for semantic search, and creates `belongs_to` relations.

Usage (from repo root, inside the api container):
    docker exec servicetsunami-agents-api-1 \\
        python /app/scripts/seed_aha_chart_of_accounts.py \\
        --tenant 7f632730-1a38-41f1-9f99-508d696dbcf1

Re-running is a no-op (idempotent on entity name within the tenant).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

# Make `app.*` importable when run inside the api container or from apps/api
THIS_FILE = Path(__file__).resolve()
APPS_API = THIS_FILE.parent.parent
if str(APPS_API) not in sys.path:
    sys.path.insert(0, str(APPS_API))

import yaml  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

DEFAULT_TENANT_ID = "7f632730-1a38-41f1-9f99-508d696dbcf1"
DEFAULT_TAXONOMY = (
    THIS_FILE.parent.parent.parent.parent
    / "docs"
    / "data"
    / "aha-chart-of-accounts"
    / "2026-05-09-canonical-taxonomy.yaml"
)
ROOT_REFERENCE_ENTITY_NAME = "AHA Chart of Accounts"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_root_entity(db, tenant_id: str):
    row = db.execute(
        text(
            """
            SELECT id, name FROM knowledge_entities
            WHERE tenant_id = :tid
              AND name = :name
              AND deleted_at IS NULL
            LIMIT 1
            """
        ),
        {"tid": tenant_id, "name": ROOT_REFERENCE_ENTITY_NAME},
    ).fetchone()
    if not row:
        raise RuntimeError(
            f"Root reference entity '{ROOT_REFERENCE_ENTITY_NAME}' not found for "
            f"tenant {tenant_id}. Seed it first (vet vertical session bootstrap)."
        )
    return row[0], row[1]


def _entity_search_text(top_level: str, leaf: dict) -> str:
    """Build a rich text blob for semantic search on this leaf."""
    name = leaf["name"]
    desc = leaf.get("description", "")
    gl = leaf.get("gl_code", "")
    keywords = [str(k) for k in (leaf.get("keyword_anchors") or [])]
    vendors = [str(v) for v in (leaf.get("typical_vendors") or [])]
    parts = [
        f"AAHA chart-of-accounts category: {top_level} > {name}",
        f"GL code: {gl}" if gl else "",
        f"Description: {desc}" if desc else "",
        f"Common keywords / anchors: {', '.join(keywords)}" if keywords else "",
        f"Typical vendors: {', '.join(vendors)}" if vendors else "",
    ]
    return "\n".join(p for p in parts if p)


def _get_or_create_leaf(db, tenant_id: str, top_level: str, leaf: dict) -> tuple[uuid.UUID, bool]:
    """Upsert one leaf account_category entity. Returns (id, created_bool)."""
    name = leaf["name"]
    description = _entity_search_text(top_level, leaf)
    attrs = {
        "top_level": top_level,
        "gl_code": str(leaf.get("gl_code")) if leaf.get("gl_code") is not None else None,
        "keyword_anchors": [str(k) for k in (leaf.get("keyword_anchors") or [])],
        "typical_vendors": [str(v) for v in (leaf.get("typical_vendors") or [])],
        "confidence_floor": leaf.get("confidence_floor", 0.85),
        "source": "AAHA-aligned best-effort taxonomy 2026-05-09",
    }
    row = db.execute(
        text(
            """
            SELECT id FROM knowledge_entities
            WHERE tenant_id = :tid
              AND name = :name
              AND entity_type = 'account_category'
              AND deleted_at IS NULL
            LIMIT 1
            """
        ),
        {"tid": tenant_id, "name": name},
    ).fetchone()
    if row:
        # Refresh description + attributes (idempotent update of metadata)
        db.execute(
            text(
                """
                UPDATE knowledge_entities
                SET description = :desc,
                    attributes  = CAST(:attrs AS json),
                    category    = 'aha_taxonomy',
                    status      = 'verified',
                    updated_at  = now()
                WHERE id = :id
                """
            ),
            {
                "desc": description,
                "attrs": json.dumps(attrs),
                "id": str(row[0]),
            },
        )
        return row[0], False

    eid = uuid.uuid4()
    db.execute(
        text(
            """
            INSERT INTO knowledge_entities (
                id, tenant_id, name, entity_type, category,
                description, attributes, status, confidence,
                created_at, updated_at
            ) VALUES (
                :id, :tid, :name, 'account_category', 'aha_taxonomy',
                :desc, CAST(:attrs AS json), 'verified', 1.0,
                now(), now()
            )
            """
        ),
        {
            "id": str(eid),
            "tid": tenant_id,
            "name": name,
            "desc": description,
            "attrs": json.dumps(attrs),
        },
    )
    return eid, True


def _get_or_create_relation(db, tenant_id: str, child_id, root_id, rel_type: str) -> bool:
    row = db.execute(
        text(
            """
            SELECT id FROM knowledge_relations
            WHERE tenant_id = :tid
              AND from_entity_id = :src
              AND to_entity_id   = :tgt
              AND relation_type  = :rtype
            LIMIT 1
            """
        ),
        {
            "tid": tenant_id,
            "src": str(child_id),
            "tgt": str(root_id),
            "rtype": rel_type,
        },
    ).fetchone()
    if row:
        return False
    db.execute(
        text(
            """
            INSERT INTO knowledge_relations (
                id, tenant_id, from_entity_id, to_entity_id,
                relation_type, strength, confidence_source,
                created_at, updated_at
            ) VALUES (
                :id, :tid, :src, :tgt, :rtype, 1.0, 'manual', now(), now()
            )
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": tenant_id,
            "src": str(child_id),
            "tgt": str(root_id),
            "rtype": rel_type,
        },
    )
    return True


def _embed_leaf(db, tenant_id: str, entity_id, search_text: str) -> bool:
    """Embed the leaf description + write to embeddings table.
    Returns True if an embedding was successfully (re)written.
    """
    try:
        from app.services.embedding_service import embed_and_store
    except Exception as e:
        print(f"  [WARN]  embedding_service import failed: {e}")
        return False
    try:
        row = embed_and_store(
            db,
            tenant_id=uuid.UUID(tenant_id),
            content_type="knowledge_entity",
            content_id=str(entity_id),
            text_content=search_text,
            task_type="RETRIEVAL_DOCUMENT",
        )
        if row is None:
            return False

        # Mirror the vector onto the entity row itself so existing
        # find_entities semantic search keeps working.
        db.execute(
            text(
                """
                UPDATE knowledge_entities
                SET embedding = (
                    SELECT embedding FROM embeddings
                    WHERE content_type = 'knowledge_entity'
                      AND content_id = :cid
                    ORDER BY created_at DESC LIMIT 1
                )
                WHERE id = :id
                """
            ),
            {"cid": str(entity_id), "id": str(entity_id)},
        )
        return True
    except Exception as e:
        print(f"  [WARN]  embedding failed for {entity_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", default=DEFAULT_TENANT_ID, help="Tenant UUID")
    parser.add_argument(
        "--taxonomy",
        default=str(DEFAULT_TAXONOMY),
        help="Path to canonical-taxonomy.yaml",
    )
    parser.add_argument(
        "--skip-embed",
        action="store_true",
        help="Skip embedding generation (faster dry-run)",
    )
    args = parser.parse_args()

    tenant_id = args.tenant
    taxonomy_path = Path(args.taxonomy)
    if not taxonomy_path.exists():
        # Fallback for in-container path layout where /app == apps/api
        in_container = Path("/app/../docs/data/aha-chart-of-accounts/2026-05-09-canonical-taxonomy.yaml").resolve()
        if in_container.exists():
            taxonomy_path = in_container
        else:
            print(f"ERROR: taxonomy file not found at {args.taxonomy}")
            return 2

    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://postgres:postgres@db:5432/agentprovision",
    )
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    print(f"Tenant         : {tenant_id}")
    print(f"Taxonomy       : {taxonomy_path}")
    print(f"DB             : {db_url.split('@')[-1]}")

    try:
        root_id, root_name = _find_root_entity(db, tenant_id)
        print(f"Root entity    : {root_name} ({root_id})")

        with taxonomy_path.open() as fh:
            doc = yaml.safe_load(fh)

        leaf_count = sum(len(c.get("subcategories", [])) for c in doc.get("categories", []))
        print(f"Leaf categories: {leaf_count} expected\n")

        created = 0
        updated = 0
        related_new = 0
        embedded = 0

        for top_block in doc.get("categories", []):
            top_level = top_block["top_level"]
            subs = top_block.get("subcategories", [])
            print(f"-- {top_level} ({len(subs)} leaves)")
            for leaf in subs:
                eid, was_new = _get_or_create_leaf(db, tenant_id, top_level, leaf)
                tag = "CREATED" if was_new else "UPDATED"
                if was_new:
                    created += 1
                else:
                    updated += 1
                if _get_or_create_relation(db, tenant_id, eid, root_id, "belongs_to"):
                    related_new += 1
                if not args.skip_embed:
                    if _embed_leaf(
                        db,
                        tenant_id,
                        eid,
                        _entity_search_text(top_level, leaf),
                    ):
                        embedded += 1
                print(f"  [{tag:7}] {leaf['name']}  (gl {leaf.get('gl_code', '----')})")

        db.commit()
        print()
        print("=== Summary ===")
        print(f"  created     : {created}")
        print(f"  updated     : {updated}")
        print(f"  relations + : {related_new}")
        print(f"  embedded    : {embedded} / {leaf_count}")
        print(f"seeded {created + updated} categories")
        return 0
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
