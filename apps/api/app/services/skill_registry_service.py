"""Skill registry sync — keeps skill_registry table and embeddings in sync with disk."""
import logging
import re
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.skill_registry import SkillRegistry
from app.schemas.file_skill import FileSkill
from app.services import embedding_service
from app.services.skill_manager import skill_manager

logger = logging.getLogger(__name__)


def sync_skills_to_db(db: Session) -> int:
    """Scan disk skills and sync to skill_registry + embeddings. Returns count synced."""
    skill_manager.scan()
    all_skills = skill_manager._skills
    synced = 0

    existing_slugs = {r.slug: r for r in db.query(SkillRegistry).all()}

    for skill in all_skills:
        tenant_id = None
        if skill.tier == "custom" and "tenant_" in skill.skill_dir:
            m = re.search(r'tenant_([a-f0-9\-]+)', skill.skill_dir)
            if m:
                tenant_id = m.group(1)

        if skill.slug in existing_slugs:
            reg = existing_slugs[skill.slug]
            reg.name = skill.name
            reg.version = skill.version
            reg.tier = skill.tier
            reg.category = skill.category
            reg.tags = skill.tags
            reg.auto_trigger_description = skill.auto_trigger
            reg.chain_to = skill.chain_to
            reg.engine = skill.engine
            reg.source_repo = skill.source_repo
            del existing_slugs[skill.slug]
        else:
            reg = SkillRegistry(
                tenant_id=tenant_id,
                slug=skill.slug,
                name=skill.name,
                version=skill.version,
                tier=skill.tier,
                category=skill.category,
                tags=skill.tags or [],
                auto_trigger_description=skill.auto_trigger,
                chain_to=skill.chain_to or [],
                engine=skill.engine,
                source_repo=skill.source_repo,
            )
            db.add(reg)

        # Embed skill for auto-trigger
        try:
            embed_text = ""
            if skill.auto_trigger:
                embed_text += skill.auto_trigger + " "
            if skill.description:
                embed_text += skill.description
            if embed_text.strip():
                embedding_service.embed_and_store(
                    db, tenant_id, "skill", skill.slug, embed_text.strip()
                )
        except Exception as e:
            logger.warning("Failed to embed skill %s: %s", skill.slug, e)

        synced += 1

    # Remove orphaned registry entries
    for slug, orphan in existing_slugs.items():
        try:
            embedding_service.delete_embedding(db, "skill", slug)
        except Exception:
            pass
        db.delete(orphan)

    db.commit()
    logger.info("Skill registry sync: %d skills synced", synced)
    return synced


def match_skills(db: Session, tenant_id: str, query: str, limit: int = 3) -> List[dict]:
    """Find skills that match a user query via embedding similarity."""
    return embedding_service.search_similar(
        db, str(tenant_id) if tenant_id else None, ["skill"], query, limit=limit
    )
