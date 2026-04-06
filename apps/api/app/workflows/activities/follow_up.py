"""Activities for follow-up workflow."""
import logging
import uuid

from temporalio import activity

logger = logging.getLogger(__name__)


@activity.defn
async def execute_followup_action(input) -> dict:
    """Execute a scheduled follow-up action.

    Supported actions:
    - send_whatsapp: Send a WhatsApp message to the entity's contact
    - update_stage: Update the entity's pipeline stage
    - remind: Log a reminder observation
    """
    from app.db.session import SessionLocal
    from app.models.knowledge_entity import KnowledgeEntity

    action = input.action
    entity_id = input.entity_id
    tenant_id = input.tenant_id
    message = input.message

    logger.info(f"Executing follow-up: {action} for entity {entity_id}")

    db = SessionLocal()
    try:
        entity = db.query(KnowledgeEntity).filter(
            KnowledgeEntity.id == entity_id,
        ).first()

        if not entity:
            return {"status": "error", "error": f"Entity {entity_id} not found"}

        if action == "send_whatsapp":
            phone = (entity.properties or {}).get("phone")
            if not phone:
                return {"status": "error", "error": "No phone number on entity"}

            from app.services.whatsapp_service import whatsapp_service
            result = await whatsapp_service.send_message(
                tenant_id=tenant_id,
                to=phone,
                message=message or f"Following up regarding {entity.name}",
            )
            return {"status": "sent", "action": action, **result}

        elif action == "update_stage":
            props = entity.properties or {}
            old_stage = props.get("pipeline_stage", "none")
            props["pipeline_stage"] = message
            entity.properties = props
            db.commit()
            return {
                "status": "updated",
                "action": action,
                "previous_stage": old_stage,
                "new_stage": message,
            }

        elif action == "remind":
            from app.models.knowledge_observation import KnowledgeObservation
            obs = KnowledgeObservation(
                id=uuid.uuid4(),
                tenant_id=uuid.UUID(tenant_id),
                entity_id=entity.id,  # Bug fix: was missing, observation was unlinked
                observation_text=f"Follow-up reminder: {message or entity.name}",
                observation_type="follow_up_reminder",
                source_type="temporal_workflow",
            )
            db.add(obs)
            db.commit()
            return {"status": "reminded", "action": action, "entity_name": entity.name}

        elif action == "send_email":
            # Email is sent via MCP layer — create a high-priority notification
            # so Luna picks it up on next active session and sends it.
            email = (entity.properties or {}).get("email")
            from app.models.notification import Notification
            notif = Notification(
                tenant_id=uuid.UUID(tenant_id),
                title=f"Send follow-up email to {entity.name}",
                body=message or f"Time to follow up with {entity.name}" + (f" at {email}" if email else ""),
                source="workflow",
                priority="high",
                event_metadata={
                    "action": "send_email",
                    "entity_id": str(entity.id),
                    "entity_name": entity.name,
                    "email": email,
                },
            )
            db.add(notif)
            db.commit()
            return {"status": "queued", "action": action, "notification_id": str(notif.id), "entity_name": entity.name}

        else:
            return {"status": "error", "error": f"Unknown action: {action}"}

    except Exception as e:
        logger.exception(f"Follow-up action failed: {e}")
        db.rollback()
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
