"""Tenant-scoped veterinary practice dashboard rollup.

This is a read model over the manifest-driven provisioner. It deliberately
keeps the MVP file-first: Drive / OneDrive are readiness checks, while PMS
and vendor systems are listed as future integration notes rather than
blocking core flows.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, Optional

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.dynamic_workflow import DynamicWorkflow, WorkflowRun
from app.models.integration_config import IntegrationConfig
from app.models.integration_credential import IntegrationCredential
from app.models.tenant import Tenant
from app.services.integration_status import INTEGRATION_DISPLAY
from app.services.provisioning.vet_manifest import (
    VetPracticeManifest,
    get_manifest,
)


FUTURE_PRACTICE_SYSTEMS: list[dict[str, str]] = [
    {
        "key": "covetrus_pulse",
        "name": "Practice management system",
        "status": "future",
        "note": "PMS reads/writes move here after computer-use and partner integration work.",
    },
    {
        "key": "clinical_scribe",
        "name": "Clinical scribe",
        "status": "future",
        "note": "Scribe exports are handled as uploaded file packets during the MVP.",
    },
    {
        "key": "phone_sms",
        "name": "Phone and messaging",
        "status": "future",
        "note": "Owner communications can be copied into packets until live channel routing is approved.",
    },
    {
        "key": "payments_inventory",
        "name": "Payments and inventory systems",
        "status": "future",
        "note": "Daily exports/count sheets are the source of truth for the MVP.",
    },
]


def _display_for_integration(name: str) -> dict[str, str]:
    display = INTEGRATION_DISPLAY.get(name, {})
    return {
        "integration_name": name,
        "display_name": display.get("name", name.replace("_", " ").title()),
        "icon": display.get("icon", "FaPlug"),
    }


def _connected_config_ids(
    db: Session,
    tenant_id: uuid.UUID,
    configs: Iterable[IntegrationConfig],
) -> set[uuid.UUID]:
    config_ids = [c.id for c in configs]
    if not config_ids:
        return set()
    rows = (
        db.query(IntegrationCredential.integration_config_id)
        .filter(
            IntegrationCredential.integration_config_id.in_(config_ids),
            IntegrationCredential.tenant_id == tenant_id,
            IntegrationCredential.status == "active",
        )
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def _is_connected(config: Optional[IntegrationConfig], connected_ids: set[uuid.UUID]) -> bool:
    if config is None or not config.enabled:
        return False
    return bool(config.account_email) or config.id in connected_ids


def _workflow_row(
    db: Session,
    tenant_id: uuid.UUID,
    template_name: Optional[str],
) -> Optional[DynamicWorkflow]:
    if not template_name:
        return None
    return (
        db.query(DynamicWorkflow)
        .filter(
            DynamicWorkflow.tenant_id == tenant_id,
            DynamicWorkflow.name == template_name,
            DynamicWorkflow.tier == "custom",
        )
        .order_by(DynamicWorkflow.updated_at.desc())
        .first()
    )


def _latest_run(db: Session, tenant_id: uuid.UUID, workflow_id: uuid.UUID | None) -> dict[str, Any] | None:
    if workflow_id is None:
        return None
    run = (
        db.query(WorkflowRun)
        .filter(
            WorkflowRun.tenant_id == tenant_id,
            WorkflowRun.workflow_id == workflow_id,
        )
        .order_by(WorkflowRun.started_at.desc())
        .first()
    )
    if run is None:
        return None
    return {
        "id": str(run.id),
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "current_step": run.current_step,
        "error": run.error,
    }


def _agent_row(agent: Agent | None, spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": spec["name"],
        "id": str(agent.id) if agent else None,
        "present": agent is not None,
        "role": agent.role if agent else spec.get("role"),
        "status": agent.status if agent else "missing",
        "description": agent.description if agent else spec.get("description"),
        "capabilities": agent.capabilities if agent else spec.get("capabilities", []),
        "tool_groups": agent.tool_groups if agent else spec.get("tool_groups", []),
        "human_approval_gate": bool(spec.get("human_approval_gate", False)),
    }


def build_vet_practice_dashboard(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    variant: str = "gp_full",
) -> Dict[str, Any]:
    """Build the file-first veterinary MVP dashboard for one tenant."""
    manifest: VetPracticeManifest = get_manifest(variant)
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()

    agents = (
        db.query(Agent)
        .filter(
            Agent.tenant_id == tenant_id,
            Agent.name.in_([a["name"] for a in manifest.agents]),
        )
        .all()
    )
    agents_by_name = {a.name: a for a in agents}

    integration_names = sorted({
        slot["integration_name"]
        for slot in manifest.connector_slots
    } | {
        name
        for flow in manifest.dashboard_flows
        for name in flow.get("required_integrations", [])
    })
    configs = (
        db.query(IntegrationConfig)
        .filter(
            IntegrationConfig.tenant_id == tenant_id,
            IntegrationConfig.integration_name.in_(integration_names),
        )
        .all()
        if integration_names
        else []
    )
    configs_by_name: dict[str, IntegrationConfig] = {}
    for cfg in configs:
        if cfg.integration_name not in configs_by_name:
            configs_by_name[cfg.integration_name] = cfg
        elif cfg.enabled and not configs_by_name[cfg.integration_name].enabled:
            configs_by_name[cfg.integration_name] = cfg

    connected_ids = _connected_config_ids(db, tenant_id, configs)

    storage_rows = []
    for name in integration_names:
        display = _display_for_integration(name)
        cfg = configs_by_name.get(name)
        storage_rows.append({
            **display,
            "configured": cfg is not None,
            "enabled": bool(cfg.enabled) if cfg else False,
            "connected": _is_connected(cfg, connected_ids),
            "requires_approval": bool(cfg.requires_approval) if cfg else False,
            "account_email": cfg.account_email if cfg else None,
        })

    workflow_rows: dict[str, dict[str, Any]] = {}
    for name in manifest.workflow_templates:
        wf = _workflow_row(db, tenant_id, name)
        workflow_rows[name] = {
            "name": name,
            "id": str(wf.id) if wf else None,
            "installed": wf is not None,
            "status": wf.status if wf else "missing",
            "run_count": wf.run_count if wf else 0,
            "last_run_at": wf.last_run_at.isoformat() if wf and wf.last_run_at else None,
            "latest_run": _latest_run(db, tenant_id, wf.id if wf else None),
        }

    flow_rows = []
    for flow in manifest.dashboard_flows:
        required = flow.get("required_integrations", [])
        readiness = []
        for name in required:
            cfg = configs_by_name.get(name)
            readiness.append({
                **_display_for_integration(name),
                "connected": _is_connected(cfg, connected_ids),
                "configured": cfg is not None,
            })
        workflow = workflow_rows.get(flow.get("workflow_template"))
        agent = agents_by_name.get(flow.get("primary_agent"))
        connected_count = sum(1 for r in readiness if r["connected"])
        required_count = len(readiness)
        flow_rows.append({
            **flow,
            "primary_agent_id": str(agent.id) if agent else None,
            "agent_present": agent is not None,
            "workflow": workflow,
            "readiness": readiness,
            "ready": (
                agent is not None
                and (workflow is None or workflow.get("installed"))
                and connected_count == required_count
            ),
            "connected_integrations": connected_count,
            "required_integrations_count": required_count,
        })

    summary = {
        "agents_present": len(agents),
        "agents_expected": len(manifest.agents),
        "workflows_installed": sum(1 for w in workflow_rows.values() if w["installed"]),
        "workflows_expected": len(manifest.workflow_templates),
        "storage_connected": sum(1 for r in storage_rows if r["connected"]),
        "storage_expected": len(storage_rows),
        "flows_ready": sum(1 for f in flow_rows if f["ready"]),
        "flows_expected": len(flow_rows),
    }

    return {
        "variant": manifest.variant,
        "tenant_id": str(tenant_id),
        "practice_name": tenant.name if tenant else "Veterinary Practice",
        "mode": "file_first",
        "summary": summary,
        "agents": [
            _agent_row(agents_by_name.get(spec["name"]), spec)
            for spec in manifest.agents
        ],
        "storage": storage_rows,
        "flows": flow_rows,
        "workflows": list(workflow_rows.values()),
        "future_practice_systems": FUTURE_PRACTICE_SYSTEMS,
    }
