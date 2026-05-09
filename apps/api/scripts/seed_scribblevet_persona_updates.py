"""Persona-prompt updates for the Pet Health Concierge + Clinical Triage agents
to surface ScribbleVet-ingested clinical_note observations.

Idempotent. Safe to re-run — the script checks whether the ScribbleVet
guidance block is already present in `persona_prompt` (sentinel string
match) and only appends it once. Re-running is the documented way to
update the guidance block: bump SCRIBBLEVET_PERSONA_BLOCK below, delete
the sentinel from existing personas (or just rerun and let the script
detect the bump), and the next run reapplies.

Tenant: 7f632730-1a38-41f1-9f99-508d696dbcf1 (The Animal Doctor SOC).
Generalizes to every clinic tenant — set ``--all-tenants`` to apply
across every Agent named "Pet Health Concierge" or "Clinical Triage
Agent" in any tenant.

Run inside the api container:

    docker exec servicetsunami-agents-api-1 \
        python /app/scripts/seed_scribblevet_persona_updates.py

Or limit to a single tenant:

    docker exec servicetsunami-agents-api-1 \
        python /app/scripts/seed_scribblevet_persona_updates.py \
        --tenant 7f632730-1a38-41f1-9f99-508d696dbcf1

Outputs (per re-run, all idempotent):
- For each matched agent in scope: if the SCRIBBLEVET_SENTINEL string
  is already in persona_prompt, no change. Otherwise the block is
  appended and persona_prompt is committed back.
"""
from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

# Make the api package importable when running from /app/scripts
_HERE = Path(__file__).resolve().parent
_API_ROOT = _HERE.parent  # /app  (apps/api in repo)
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.agent import Agent

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# Sentinel string — present in persona_prompt iff the ScribbleVet
# guidance has been applied. Bump this when the guidance changes so
# subsequent runs reapply.
SCRIBBLEVET_SENTINEL = "[scribblevet-v1]"


PET_HEALTH_CONCIERGE_BLOCK = f"""
## Prior visits — record-aware lookup {SCRIBBLEVET_SENTINEL}

When a client asks anything record-aware ("has Bella been seen for limp before?",
"what did Dr. Castillo say about her hyperthyroidism?", "is this the same
condition as last time?"), do this *before* responding:

1. Identify the patient. Either via the conversation context or by asking
   the client for the pet's name + your reference to the owner.
2. Call ``find_entities`` with ``entity_type='patient'`` and the pet's name
   to get the entity_id.
3. Call ``search_knowledge`` filtered to ``observation_type='clinical_note'``
   on that patient_id (or with the pet's name in the query) to surface
   prior visits ingested from ScribbleVet.
4. If matches exist, ground the reply in the actual SOAP body — quote the
   diagnosis/plan briefly, never invent details. If no matches, say so
   honestly ("I don't see prior visits for that on file") and offer to
   book an appointment so the DVM can review in person.

VCPR guard: even with rich prior-visit context, never recommend or imply
diagnosis or prescription absent an active VCPR. If the conversation is
record-aware AND there is no VCPR signal, triage and book — do not
clinical-interpret.
"""


CLINICAL_TRIAGE_BLOCK = f"""
## Pre-load prior history before drafting intake summaries {SCRIBBLEVET_SENTINEL}

Every intake summary you draft must include a "PRIOR HISTORY" section
populated from the patient's ScribbleVet notes (ingested as
``clinical_note`` observations on the patient entity).

Workflow per intake:

1. Resolve the patient entity. The intake form has the pet's name; call
   ``find_entities`` with ``entity_type='patient'``.
2. Call ``search_knowledge`` with the patient's entity_id and a query
   that filters to ``observation_type='clinical_note'``. Pull the 3 most
   recent matches.
3. Build the "PRIOR HISTORY" section from those notes:
   - Most recent diagnosis(es)
   - Ongoing medications (prefer the medications list from the latest
     note's plan section)
   - Open concerns flagged in the most recent A (Assessment) section
   - Last visit date + DVM
4. If no clinical_note observations exist for this patient, write
   "No prior visits in record-aware system." — that's an honest signal
   the DVM should treat as a new client.

Never paraphrase or summarize the prior diagnosis in a way that could
be read as a current clinical interpretation. Quote, attribute, link
back to the visit_date the observation came from.
"""


PERSONA_UPDATES = {
    "Pet Health Concierge": PET_HEALTH_CONCIERGE_BLOCK,
    "Clinical Triage Agent": CLINICAL_TRIAGE_BLOCK,
    # Common name variants we've seen in seed scripts / chat references.
    # The match is case-insensitive ilike below.
    "Clinical Triage": CLINICAL_TRIAGE_BLOCK,
}


def _apply_block(agent: Agent, block: str) -> bool:
    """Append the ScribbleVet block to ``agent.persona_prompt`` if absent.

    Returns True if a write happened, False if already up-to-date.
    """
    current = agent.persona_prompt or ""
    if SCRIBBLEVET_SENTINEL in current:
        logger.info(
            "Agent %s (%s) already has ScribbleVet block — no change.",
            agent.id,
            agent.name,
        )
        return False
    new_prompt = (current.rstrip() + "\n\n" + block.strip() + "\n").lstrip("\n")
    agent.persona_prompt = new_prompt
    return True


def update_personas(db: Session, tenant_id: uuid.UUID | None) -> int:
    """Apply persona blocks. Returns count of agents updated."""
    updated = 0
    for canonical_name, block in PERSONA_UPDATES.items():
        q = db.query(Agent).filter(Agent.name.ilike(canonical_name))
        if tenant_id is not None:
            q = q.filter(Agent.tenant_id == tenant_id)
        agents = q.all()
        if not agents:
            logger.info("No agents matched name=%r (tenant=%s).", canonical_name, tenant_id)
            continue
        for a in agents:
            if _apply_block(a, block):
                updated += 1
                logger.info(
                    "Appended ScribbleVet block to agent %s (%s) tenant=%s.",
                    a.id,
                    a.name,
                    a.tenant_id,
                )
    if updated:
        db.commit()
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tenant",
        type=str,
        default=None,
        help="Tenant UUID to scope to. Default = all tenants.",
    )
    parser.add_argument(
        "--all-tenants",
        action="store_true",
        help="Apply across every tenant (overrides --tenant).",
    )
    args = parser.parse_args()

    tenant_id: uuid.UUID | None = None
    if args.tenant and not args.all_tenants:
        try:
            tenant_id = uuid.UUID(args.tenant)
        except ValueError:
            parser.error(f"--tenant must be a UUID; got {args.tenant!r}")

    db = SessionLocal()
    try:
        count = update_personas(db, tenant_id)
        logger.info("Persona updates complete. %d agent(s) updated.", count)
    finally:
        db.close()


if __name__ == "__main__":
    main()
