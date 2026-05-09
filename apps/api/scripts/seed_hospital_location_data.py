"""Seed hospital location data + nearest 24/7 ER for The Animal Doctor SOC.

Idempotent. Safe to re-run — observations are deduped by (entity_id,
observation_text) and relations by (from_entity_id, to_entity_id,
relation_type). ER entities are upserted by (tenant_id, name).

Source of truth: docs/data/animal-doctor-soc/locations.yaml.
Tenant: 7f632730-1a38-41f1-9f99-508d696dbcf1 (The Animal Doctor SOC).

Run inside the api container so embedding_service + SQLAlchemy models
are wired:

    docker exec servicetsunami-agents-api-1 \
        python /app/scripts/seed_hospital_location_data.py

Outputs (per re-run, all idempotent):
- Observations on each existing hospital entity covering: address,
  phone, hours (per day), after-hours policy, accepting-new-clients,
  languages, parking, services. Each observation has a non-null
  embedding (768-dim, nomic-embed-text-v1.5).
- 2 emergency-hospital entities (CASE Anaheim, BrightCare Mission Viejo),
  each with their own observations (address, phone, 24/7 status, services).
- 3 `nearest_er` relations: anaheim -> CASE, buena-park -> CASE,
  mission-viejo -> BrightCare.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# Make the api package importable when running from /app/scripts
_HERE = Path(__file__).resolve().parent
_API_ROOT = _HERE.parent  # /app  (apps/api in repo)
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

import yaml  # type: ignore

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.knowledge_entity import KnowledgeEntity
from app.models.knowledge_observation import KnowledgeObservation
from app.models.knowledge_relation import KnowledgeRelation
from app.services.embedding_service import embed_text

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("seed_hospital_location_data")

TENANT_ID = uuid.UUID("7f632730-1a38-41f1-9f99-508d696dbcf1")

def _find_yaml() -> Path:
    """Locate the YAML — env override first, then repo + container paths."""
    env_path = os.environ.get("HOSPITAL_DATA_YAML")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    candidates: list[Path] = [
        Path("/tmp/animal-doctor-soc-data/locations.yaml"),
        Path("/app/data/animal-doctor-soc/locations.yaml"),
    ]
    here = Path(__file__).resolve()
    # Walk up the parents looking for docs/data/animal-doctor-soc/locations.yaml.
    # Works whether running from a repo checkout or an arbitrary container path.
    for parent in here.parents:
        candidates.append(
            parent / "docs" / "data" / "animal-doctor-soc" / "locations.yaml"
        )

    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not locate locations.yaml. Set HOSPITAL_DATA_YAML or "
        "ensure docs/data/animal-doctor-soc/locations.yaml exists."
    )


# ── observation helpers ──────────────────────────────────────────────


def _format_hours(hours_block: dict[str, Any]) -> str:
    """Render a Mon-Sun hours dict as a single human/agent-readable line."""
    days = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    parts = []
    for d in days:
        v = hours_block.get(d, "n/a")
        parts.append(f"{d.title()}: {v}")
    return "; ".join(parts)


def _upsert_observation(
    db: Session,
    *,
    entity_id: uuid.UUID,
    observation_text: str,
    observation_type: str = "fact",
    source_ref: str | None = None,
    confidence: float = 1.0,
) -> tuple[KnowledgeObservation, bool]:
    """Idempotent observation insert keyed by (entity_id, observation_text).

    Returns (obs, created). If an observation with the same text already
    exists for this entity, we re-embed it (so a re-run repairs any null
    embedding) but don't duplicate the row.
    """
    existing = (
        db.query(KnowledgeObservation)
        .filter(
            KnowledgeObservation.tenant_id == TENANT_ID,
            KnowledgeObservation.entity_id == entity_id,
            KnowledgeObservation.observation_text == observation_text,
        )
        .first()
    )
    if existing is not None:
        if existing.embedding is None:
            vec = embed_text(observation_text)
            if vec is not None:
                existing.embedding = vec
                db.add(existing)
        return existing, False

    vec = embed_text(observation_text)
    if vec is None:
        # Fail loud — DoD requires non-null embeddings on every obs.
        raise RuntimeError(
            f"embed_text() returned None for observation: {observation_text[:80]!r}. "
            "Embedding service must be reachable for this seed to run."
        )

    obs = KnowledgeObservation(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        entity_id=entity_id,
        observation_text=observation_text,
        observation_type=observation_type,
        source_type="manual_seed",
        source_platform="seed_script",
        source_agent="seed_hospital_location_data.py",
        source_channel="system",
        source_ref=source_ref,
        confidence=confidence,
        embedding=vec,
    )
    db.add(obs)
    return obs, True


def _upsert_relation(
    db: Session,
    *,
    from_entity_id: uuid.UUID,
    to_entity_id: uuid.UUID,
    relation_type: str,
    evidence: dict[str, Any] | None = None,
    strength: float = 1.0,
) -> tuple[KnowledgeRelation, bool]:
    existing = (
        db.query(KnowledgeRelation)
        .filter(
            KnowledgeRelation.tenant_id == TENANT_ID,
            KnowledgeRelation.from_entity_id == from_entity_id,
            KnowledgeRelation.to_entity_id == to_entity_id,
            KnowledgeRelation.relation_type == relation_type,
        )
        .first()
    )
    if existing is not None:
        # refresh evidence + strength so re-runs propagate edits
        if evidence is not None:
            existing.evidence = evidence
        existing.strength = strength
        db.add(existing)
        return existing, False

    rel = KnowledgeRelation(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        from_entity_id=from_entity_id,
        to_entity_id=to_entity_id,
        relation_type=relation_type,
        strength=strength,
        evidence=evidence or {},
        confidence_source="manual",
    )
    db.add(rel)
    return rel, True


def _delete_relations_by_type(
    db: Session,
    *,
    from_entity_id: uuid.UUID,
    relation_type: str,
) -> int:
    """Delete every relation of `relation_type` originating from `from_entity_id`.

    Used by the YAML-driven seeder to converge the DB to match the YAML state.
    If the YAML lists `nearest_er` for a hospital as null (no verified 24/7
    walk-in ER known), any pre-existing relation for that hospital must be
    removed so the Pet Health Concierge persona doesn't keep routing clients
    to a building that may be closed.
    """
    deleted = (
        db.query(KnowledgeRelation)
        .filter(
            KnowledgeRelation.tenant_id == TENANT_ID,
            KnowledgeRelation.from_entity_id == from_entity_id,
            KnowledgeRelation.relation_type == relation_type,
        )
        .delete(synchronize_session=False)
    )
    return int(deleted or 0)


def _upsert_er_entity(db: Session, er: dict[str, Any]) -> KnowledgeEntity:
    """Upsert an emergency-hospital entity by (tenant_id, name)."""
    name = er["name"]
    existing = (
        db.query(KnowledgeEntity)
        .filter(
            KnowledgeEntity.tenant_id == TENANT_ID,
            KnowledgeEntity.name == name,
        )
        .first()
    )

    description = (
        f"24/7 emergency veterinary hospital. "
        f"{er['address']['street']}, {er['address']['city']}, "
        f"{er['address']['state']} {er['address']['zip']}. "
        f"Phone: {er['phone']}."
    )

    attributes = {
        "address": er["address"],
        "phone": er["phone"],
        "is_24_7": er["is_24_7"],
        "is_24_7_source": er["is_24_7_source"],
        "services": er["services"],
        "notes": er.get("notes"),
        "sources": er.get("sources", []),
    }

    if existing is not None:
        existing.description = description
        existing.category = er.get("category", "emergency_hospital")
        existing.entity_type = er.get("entity_type", "organization")
        existing.attributes = attributes
        # Refresh embedding from the description so semantic search keeps working.
        vec = embed_text(f"{name}. {description}")
        if vec is not None:
            existing.embedding = vec
        db.add(existing)
        log.info("ER entity already exists: %s (%s)", name, existing.id)
        return existing

    vec = embed_text(f"{name}. {description}")
    if vec is None:
        raise RuntimeError(f"embed_text() returned None for ER entity {name!r}")

    ent = KnowledgeEntity(
        id=uuid.uuid4(),
        tenant_id=TENANT_ID,
        entity_type=er.get("entity_type", "organization"),
        category=er.get("category", "emergency_hospital"),
        name=name,
        description=description,
        attributes=attributes,
        confidence=1.0,
        status="active",
        visibility="tenant_wide",
        embedding=vec,
    )
    db.add(ent)
    db.flush()
    log.info("Created ER entity: %s (%s)", name, ent.id)
    return ent


# ── per-hospital observation builder ─────────────────────────────────


def _seed_hospital_observations(
    db: Session, hosp: dict[str, Any]
) -> tuple[int, int]:
    """Write the location-fact observations for a single hospital.

    Returns (created_count, already_existed_count).
    """
    entity_id = uuid.UUID(hosp["entity_id"])

    # Sanity: entity must exist; we never re-create the 3 hospital entities.
    ent = (
        db.query(KnowledgeEntity)
        .filter(
            KnowledgeEntity.tenant_id == TENANT_ID,
            KnowledgeEntity.id == entity_id,
        )
        .first()
    )
    if ent is None:
        raise RuntimeError(
            f"Hospital entity {entity_id} ({hosp['name']}) not found for tenant. "
            "Refusing to create — only existing entities are seeded."
        )

    name = hosp["name"]
    addr = hosp["address"]
    address_line = (
        f"{name} address: {addr['street']}, {addr['city']}, "
        f"{addr['state']} {addr['zip']}."
    )

    phone_line = f"{name} main phone: {hosp['phone']}."

    obs_lines: list[tuple[str, str, str]] = []  # (text, type, source_ref)

    obs_lines.append((address_line, "fact", ";".join(addr.get("sources", []))))
    obs_lines.append((phone_line, "fact", ";".join(hosp.get("phone_sources", []))))

    if hosp.get("formerly_known_as"):
        obs_lines.append(
            (
                f"{name} was formerly known as {hosp['formerly_known_as']}.",
                "fact",
                ";".join(addr.get("sources", [])),
            )
        )

    hours = hosp["hours"]
    if "doctor_hours" in hours:
        obs_lines.append(
            (
                f"{name} doctor hours — {_format_hours(hours['doctor_hours'])}.",
                "fact",
                ";".join(hours.get("sources", [])),
            )
        )
    if "client_care_hours" in hours:
        obs_lines.append(
            (
                f"{name} client-care team hours — {_format_hours(hours['client_care_hours'])}.",
                "fact",
                ";".join(hours.get("sources", [])),
            )
        )

    after = hosp["after_hours_policy"]
    after_text = (
        f"{name} after-hours policy: {after['summary']}"
        + (" [unverified — confirm with front desk]" if not after.get("verified") else "")
    )
    obs_lines.append((after_text, "policy", after.get("note") or ""))

    accepting = hosp["accepting_new_clients"]
    accepting_text = (
        f"{name} accepting new clients: {'yes' if accepting['value'] else 'no'}"
        + ("" if accepting.get("verified") else " [unverified — confirm capacity]")
    )
    obs_lines.append((accepting_text, "fact", accepting.get("note") or ""))

    langs = hosp.get("languages", [])
    if langs:
        lang_text = (
            f"{name} languages spoken: {', '.join(langs)}"
            + ("" if hosp.get("languages_verified") else " [unverified — confirm with front desk]")
        )
        obs_lines.append((lang_text, "fact", hosp.get("languages_note") or ""))

    parking = hosp.get("parking") or {}
    if parking.get("summary"):
        parking_text = (
            f"{name} parking: {parking['summary']}"
            + ("" if parking.get("verified") else " [unverified — confirm details]")
        )
        obs_lines.append((parking_text, "fact", parking.get("note") or ""))

    services = hosp.get("services", [])
    if services:
        obs_lines.append(
            (
                f"{name} services offered: {', '.join(services)}.",
                "fact",
                ";".join(hosp.get("services_sources", [])),
            )
        )

    created = 0
    existed = 0
    for text, otype, sref in obs_lines:
        _, was_created = _upsert_observation(
            db,
            entity_id=entity_id,
            observation_text=text,
            observation_type=otype,
            source_ref=sref or None,
        )
        created += int(was_created)
        existed += int(not was_created)

    log.info(
        "Hospital %s — observations: %d new, %d already existed",
        name,
        created,
        existed,
    )
    return created, existed


# ── per-ER observation builder ───────────────────────────────────────


def _seed_er_observations(db: Session, ent: KnowledgeEntity, er: dict[str, Any]) -> None:
    addr = er["address"]
    address_line = (
        f"{er['name']} address: {addr['street']}, {addr['city']}, "
        f"{addr['state']} {addr['zip']}."
    )
    phone_line = f"{er['name']} 24/7 emergency phone: {er['phone']}."
    is_24_7_line = (
        f"{er['name']} is open 24 hours a day, 7 days a week. "
        f"Verified from: {er['is_24_7_source']}"
    )
    services_line = f"{er['name']} services: {', '.join(er['services'])}."

    obs_specs = [
        (address_line, "fact"),
        (phone_line, "fact"),
        (is_24_7_line, "policy"),
        (services_line, "fact"),
    ]
    if er.get("notes"):
        obs_specs.append((f"{er['name']} note: {er['notes']}", "fact"))

    for text, otype in obs_specs:
        _upsert_observation(
            db,
            entity_id=ent.id,
            observation_text=text,
            observation_type=otype,
            source_ref=";".join(er.get("sources", [])) or None,
        )


# ── main ─────────────────────────────────────────────────────────────


def main() -> None:
    yaml_path = _find_yaml()
    log.info("Loading data from %s", yaml_path)
    with yaml_path.open() as f:
        data = yaml.safe_load(f)

    if str(data.get("tenant_id")) != str(TENANT_ID):
        raise RuntimeError(
            f"YAML tenant_id {data.get('tenant_id')} does not match expected {TENANT_ID}"
        )

    db = SessionLocal()
    try:
        # 1. Hospital observations.
        for hosp in data["hospitals"]:
            _seed_hospital_observations(db, hosp)

        # 2. ER entities + their observations.
        er_by_slug: dict[str, KnowledgeEntity] = {}
        for er in data["emergency_hospitals"]:
            ent = _upsert_er_entity(db, er)
            db.flush()
            _seed_er_observations(db, ent, er)
            er_by_slug[er["slug"]] = ent

        # 3. nearest_er relations.
        # IMPORTANT (PR #322 review fix): an entry of `null` means we do NOT
        # have a verified 24/7 walk-in ER for that hospital. Skip relation
        # creation rather than seed wrong data — the Pet Health Concierge
        # persona will fall back to generic emergency guidance instead of
        # routing to a building that's locked at 2am.
        #
        # We also DELETE any pre-existing `nearest_er` relation for hospitals
        # that the YAML now lists as null. This handles the case where an
        # earlier seed run wrote a bogus relation (the BrightCare MV bug
        # that this PR fixes) — the YAML is the single source of truth, so
        # seeding it again must converge the DB to match.
        hosp_by_slug = {h["slug"]: h for h in data["hospitals"]}
        for hosp_slug, er_slug in data["nearest_er"].items():
            if er_slug is None:
                hosp = hosp_by_slug.get(hosp_slug)
                if hosp and hosp.get("entity_id"):
                    from_id = uuid.UUID(hosp["entity_id"])
                    deleted = _delete_relations_by_type(
                        db,
                        from_entity_id=from_id,
                        relation_type="nearest_er",
                    )
                    if deleted:
                        log.warning(
                            "Removed %d stale nearest_er relation(s) for %s "
                            "(YAML now null — verified 24/7 walk-in ER pending).",
                            deleted, hosp_slug,
                        )
                log.warning(
                    "Skipping nearest_er creation for hospital %s — no "
                    "verified 24/7 walk-in ER. Update locations.yaml once an "
                    "alternative is phone-verified.",
                    hosp_slug,
                )
                continue
            # Pull 24/7 verification status from the ER entity itself, not a
            # hardcoded True. If the YAML's `is_24_7_verified` is False the
            # relation is still recorded but evidence is tagged honestly so
            # downstream agents know not to treat it as 24/7.
            er_record = next(
                (e for e in data["emergency_hospitals"] if e["slug"] == er_slug),
                {},
            )
            hosp = hosp_by_slug[hosp_slug]
            er_ent = er_by_slug[er_slug]
            from_id = uuid.UUID(hosp["entity_id"])
            evidence = {
                "selected_by": "geographic_proximity",
                "verified_24_7": bool(er_record.get("is_24_7_verified", False)),
                "is_24_7": bool(er_record.get("is_24_7", False)),
                "captured_at": str(data.get("captured_at")),
                "er_slug": er_slug,
                "er_phone": next(
                    (e["phone"] for e in data["emergency_hospitals"] if e["slug"] == er_slug),
                    None,
                ),
            }
            _, created = _upsert_relation(
                db,
                from_entity_id=from_id,
                to_entity_id=er_ent.id,
                relation_type="nearest_er",
                evidence=evidence,
                strength=1.0,
            )
            log.info(
                "Relation %s nearest_er -> %s (%s)",
                hosp["name"],
                er_ent.name,
                "created" if created else "already-existed",
            )

        db.commit()
        log.info("Seed complete.")
    except Exception:
        db.rollback()
        log.exception("Seed failed; rolled back.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
