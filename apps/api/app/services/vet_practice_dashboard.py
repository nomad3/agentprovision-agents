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
from app.services.workflow_templates import NATIVE_TEMPLATES


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


FLOW_OPERATING_DETAILS: dict[str, dict[str, Any]] = {
    "pet_health_concierge": {
        "queue": [
            {
                "id": "ang-001",
                "title": "Milo - limping after dog park",
                "source": "Owner web request",
                "owner": "Maria Lopez",
                "patient": "Milo",
                "location": "Anaheim",
                "priority": "same-day review",
                "status": "Needs packet",
                "next_step": "Confirm patient identity, ask staff to review pain/red-flag notes, then save intake packet.",
                "packet_name": "Vet Intake Packet - Milo - today.md",
            },
            {
                "id": "ang-002",
                "title": "Nala - refill question",
                "source": "Copied voicemail transcript",
                "owner": "Jordan Lee",
                "patient": "Nala",
                "location": "Buena Park",
                "priority": "routine",
                "status": "Needs records",
                "next_step": "Collect medication name and last-visit context before staff reply.",
                "packet_name": "Vet Intake Packet - Nala - today.md",
            },
        ],
        "packet_checklist": [
            "Owner and pet identifiers",
            "Location preference",
            "Reason for request",
            "Urgency and red flags",
            "Missing fields for staff follow-up",
            "Staff next action",
        ],
        "review_gate": {
            "label": "Staff review before owner guidance",
            "reviewer": "Front desk or clinical team",
            "reason": "The concierge can organize context, but staff decide scheduling and medical guidance.",
        },
    },
    "front_desk_scheduling": {
        "queue": [
            {
                "id": "ang-003",
                "title": "New puppy appointment request",
                "source": "Website form",
                "owner": "Priya Shah",
                "patient": "Scout",
                "location": "Mission Viejo",
                "priority": "routine",
                "status": "Ready to draft",
                "next_step": "Capture requested window and missing vaccine records; do not promise a slot.",
                "packet_name": "Vet Intake Packet - Scout - today.md",
            }
        ],
        "packet_checklist": [
            "Owner contact",
            "Pet signalment",
            "Requested location",
            "Requested time window",
            "Reason for visit",
            "Scheduling status marked staff-confirmed",
        ],
        "review_gate": {
            "label": "Staff confirms schedule",
            "reviewer": "Front desk",
            "reason": "Until live calendar/PMS access is approved, agents prepare the request but do not reserve appointments.",
        },
    },
    "clinical_triage": {
        "queue": [
            {
                "id": "ang-004",
                "title": "Bella - vomiting overnight",
                "source": "Owner text pasted into packet",
                "owner": "Chris Martin",
                "patient": "Bella",
                "location": "Anaheim",
                "priority": "same-day review",
                "status": "Review red flags",
                "next_step": "Build one-screen handoff with symptoms, duration, meds, allergies, and missing context.",
                "packet_name": "Vet Triage Handoff - Bella - today.md",
            }
        ],
        "packet_checklist": [
            "Severity bucket",
            "Emergency red flags",
            "Symptoms and duration",
            "Known medications/allergies",
            "Missing history",
            "Recommended staff routing",
        ],
        "review_gate": {
            "label": "Clinical staff review",
            "reviewer": "Technician or DVM",
            "reason": "The agent classifies urgency and missing context; staff own clinical decisions.",
        },
    },
    "soap_note_sync": {
        "queue": [
            {
                "id": "ang-005",
                "title": "Charlie - wellness visit transcript",
                "source": "Scribe transcript upload",
                "owner": "Ana Rivera",
                "patient": "Charlie",
                "location": "Buena Park",
                "priority": "DVM review",
                "status": "Needs SOAP draft",
                "next_step": "Convert transcript into SOAP sections and flag missing weight, vaccines, and DVM wording.",
                "packet_name": "SOAP Draft - Charlie - today.md",
            }
        ],
        "packet_checklist": [
            "Raw transcript or draft note",
            "Subjective",
            "Objective",
            "Assessment",
            "Plan",
            "Missing-data flags for DVM confirmation",
        ],
        "review_gate": {
            "label": "DVM approval required",
            "reviewer": "Dr. Angelo or attending DVM",
            "reason": "Clinical documentation is drafted by the agent and signed by licensed staff.",
        },
    },
    "billing_reconciliation": {
        "queue": [
            {
                "id": "ang-006",
                "title": "End-of-day billing review",
                "source": "Uploaded charge sheet",
                "owner": "Practice team",
                "patient": "Multiple",
                "location": "All locations",
                "priority": "daily close",
                "status": "Ready to draft",
                "next_step": "Create AAHA-oriented exception packet for refunds, discounts, missing codes, and CPA notes.",
                "packet_name": "Billing Review Packet - today.md",
            }
        ],
        "packet_checklist": [
            "Charge-sheet source",
            "Line-item table",
            "Likely AAHA category",
            "Missing code flags",
            "Refund/write-off/discount flags",
            "Accountant notes",
        ],
        "review_gate": {
            "label": "Human review for ledger changes",
            "reviewer": "Manager or bookkeeper",
            "reason": "Agents prepare billing exceptions, but never post ledger adjustments.",
        },
    },
    "inventory_pharmacy": {
        "queue": [
            {
                "id": "ang-007",
                "title": "Controlled drug count variance",
                "source": "Inventory count sheet",
                "owner": "Pharmacy lead",
                "patient": "N/A",
                "location": "Mission Viejo",
                "priority": "manager review",
                "status": "Exception packet",
                "next_step": "Freeze discrepant SKU in the packet and route to staff before close.",
                "packet_name": "Inventory Audit Packet - today.md",
            }
        ],
        "packet_checklist": [
            "Medication or SKU",
            "On-hand count",
            "Par level if present",
            "Expiration issue",
            "Discrepancy note",
            "Controlled-substance flag",
        ],
        "review_gate": {
            "label": "Manager review for exceptions",
            "reviewer": "Inventory/pharmacy owner",
            "reason": "Controlled-substance discrepancies cannot be closed by assumption.",
        },
    },
    "reputation_growth": {
        "queue": [
            {
                "id": "ang-008",
                "title": "Anaheim review response",
                "source": "Uploaded review screenshot",
                "owner": "Practice manager",
                "patient": "N/A",
                "location": "Anaheim",
                "priority": "approval before public reply",
                "status": "Draft response",
                "next_step": "Draft public reply and private follow-up note; route medical content to Luna Supervisor.",
                "packet_name": "Reputation Response Packet - today.md",
            }
        ],
        "packet_checklist": [
            "Review summary",
            "Risk flags",
            "Suggested public reply",
            "Private follow-up note",
            "Content opportunity",
            "Manager approval",
        ],
        "review_gate": {
            "label": "Manager approval before publish",
            "reviewer": "Practice manager",
            "reason": "The agent drafts responses and content only; publishing stays human-approved.",
        },
    },
    "practice_ops": {
        "queue": [
            {
                "id": "ang-009",
                "title": "Three-location daily brief",
                "source": "Uploaded packets and exports",
                "owner": "Operations",
                "patient": "Multiple",
                "location": "All locations",
                "priority": "daily huddle",
                "status": "Ready to compile",
                "next_step": "Summarize requests, handoffs, billing exceptions, inventory exceptions, and blockers.",
                "packet_name": "Daily Practice Ops Brief - today.md",
            }
        ],
        "packet_checklist": [
            "By-location summary",
            "Appointment/request queue",
            "Triage escalations",
            "Billing exceptions",
            "Inventory exceptions",
            "Blocked workflows and next actions",
        ],
        "review_gate": {
            "label": "Operator review",
            "reviewer": "Owner, COO, or practice manager",
            "reason": "Ops briefs separate file-backed facts from future PMS fields.",
        },
    },
    "pms_desktop_control": {
        "queue": [
            {
                "id": "ang-010",
                "title": "Pulse screen-map packet",
                "source": "Computer-use lane notes",
                "owner": "Implementation team",
                "patient": "N/A",
                "location": "All locations",
                "priority": "staging",
                "status": "Observation only",
                "next_step": "Map safe fields and required approval grants; do not claim any PMS write occurred.",
                "packet_name": "PMS Desktop Readiness Packet - today.md",
            }
        ],
        "packet_checklist": [
            "App and screen name",
            "Safe fields",
            "Unsafe fields",
            "Approval grant needed",
            "Target allowlist notes",
            "Exact proposed operator steps",
        ],
        "review_gate": {
            "label": "Explicit desktop-control approval",
            "reviewer": "Implementation owner",
            "reason": "PMS actuation is future work and must be granted before any desktop command writes data.",
        },
    },
    "cardiac_referral_loop": {
        "queue": [
            {
                "id": "brett-001",
                "title": "Bailey - echo referral package",
                "source": "Referral email and Drive upload",
                "owner": "Maple Veterinary Hospital",
                "patient": "Bailey",
                "location": "Cardiology referral",
                "priority": "specialist review",
                "status": "Needs DACVIM draft",
                "next_step": "Extract echo measurements, draft report, and hold for Dr. Brett approval.",
                "packet_name": "Cardiac Report - Bailey - draft.md",
            }
        ],
        "packet_checklist": [
            "Referral clinic",
            "Patient and owner",
            "Echo measurement table",
            "Source page citations",
            "DACVIM draft",
            "Brett approval before send",
        ],
        "review_gate": {
            "label": "Dr. Brett approval before send-back",
            "reviewer": "Dr. Brett",
            "reason": "The diagnostics agent drafts; the veterinarian signs the interpretation.",
        },
    },
    "referral_sendback": {
        "queue": [
            {
                "id": "brett-002",
                "title": "Referral send-back follow-up",
                "source": "Approved report artifact",
                "owner": "Referring clinic",
                "patient": "Multiple",
                "location": "Cardiology referral",
                "priority": "turnaround watch",
                "status": "Track package",
                "next_step": "Confirm delivery preference and flag packages waiting beyond turnaround target.",
                "packet_name": "Referral Send-back Tracker - today.md",
            }
        ],
        "packet_checklist": [
            "Approved report",
            "Referral clinic preference",
            "Owner-ready summary",
            "Send-back status",
            "Recall timing",
            "Open blockers",
        ],
        "review_gate": {
            "label": "Approved report required",
            "reviewer": "Dr. Brett or referral lead",
            "reason": "No referral package leaves before the clinical report is approved.",
        },
    },
}


PRACTICE_LAUNCH_CONTEXT: dict[str, Any] = {
    "lead_clinicians": [
        {
            "name": "Dr. Angelo Castillo",
            "focus": "The Animal Doctor SOC multi-location GP practice",
        },
        {
            "name": "Dr. Brett",
            "focus": "Cardiology referral and report loop",
        },
    ],
    "locations": ["Anaheim", "Buena Park", "Mission Viejo"],
    "mvp_sources": [
        "Google Drive practice packets",
        "OneDrive practice packets",
        "Uploaded scribe transcripts and chart exports",
        "Uploaded billing, inventory, and review exports",
    ],
    "initial_meetings": [
        {
            "title": "Angelo practice-management kickoff",
            "date": "2026-05-09",
            "summary": (
                "Confirmed file-first MVP, Pulse and scribe readiness as future integration work, "
                "and three-location daily operations support."
            ),
        },
        {
            "title": "Brett cardiology beachhead",
            "date": "2026-03-11",
            "summary": (
                "Defined the referral package loop: study in, measurements extracted, DACVIM "
                "draft prepared, veterinarian approval, then send-back."
            ),
        },
    ],
}


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


def _native_template(name: str | None) -> dict[str, Any] | None:
    if not name:
        return None
    for template in NATIVE_TEMPLATES:
        if template.get("name") == name:
            return template
    return None


def _workflow_definition(
    workflow: DynamicWorkflow | None,
    template_name: str | None,
) -> dict[str, Any] | None:
    if workflow is not None:
        return workflow.definition or {"steps": []}
    native = _native_template(template_name)
    if native is None:
        return None
    return native.get("definition") or {"steps": []}


def _step_destination(step: dict[str, Any]) -> str | None:
    params = step.get("params") or {}
    tool = step.get("tool")
    if tool == "create_drive_file":
        return "Google Drive"
    if tool == "create_onedrive_file":
        return "OneDrive"
    if params.get("folder_id"):
        return "File repository"
    return None


def _workflow_steps(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not definition:
        return []
    rows: list[dict[str, Any]] = []
    for index, step in enumerate(definition.get("steps") or [], start=1):
        rows.append({
            "index": index,
            "id": step.get("id"),
            "type": step.get("type"),
            "name": step.get("name") or step.get("agent") or step.get("tool") or step.get("id"),
            "agent": step.get("agent"),
            "tool": step.get("tool"),
            "output": step.get("output"),
            "approval_timeout_hours": step.get("timeout_hours"),
            "destination": _step_destination(step),
        })
    return rows


def _specialist_lanes(variant: str) -> list[dict[str, Any]]:
    if variant != "gp_full":
        return []
    cardiology = get_manifest("cardiology_v1")
    lanes: list[dict[str, Any]] = []
    for flow in cardiology.dashboard_flows:
        details = FLOW_OPERATING_DETAILS.get(flow["key"], {})
        lanes.append({
            **flow,
            "lead_clinician": "Dr. Brett",
            "manifest_variant": cardiology.variant,
            "status": "available manifest",
            "packet_checklist": details.get("packet_checklist", []),
            "sample_queue": [
                {
                    **item,
                    "assigned_agent": flow.get("primary_agent"),
                    "approval_required": bool(flow.get("approval_required")),
                    "example": True,
                }
                for item in details.get("queue", [])
            ],
            "review_gate": details.get("review_gate"),
        })
    return lanes


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


def _agent_row(
    agent: Agent | None,
    spec: dict[str, Any],
    *,
    agents_by_name: dict[str, Agent],
) -> dict[str, Any]:
    escalation_to = spec.get("escalation_to")
    escalation_agent = agents_by_name.get(escalation_to) if escalation_to else None
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
        "escalation_to": escalation_to,
        "escalation_agent_id": str(escalation_agent.id) if escalation_agent else None,
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
    workflow_models: dict[str, DynamicWorkflow | None] = {}
    for name in manifest.workflow_templates:
        wf = _workflow_row(db, tenant_id, name)
        workflow_models[name] = wf
        workflow_rows[name] = {
            "name": name,
            "id": str(wf.id) if wf else None,
            "installed": wf is not None,
            "status": wf.status if wf else "missing",
            "run_count": wf.run_count if wf else 0,
            "last_run_at": wf.last_run_at.isoformat() if wf and wf.last_run_at else None,
            "latest_run": _latest_run(db, tenant_id, wf.id if wf else None),
            "native_template_present": _native_template(name) is not None,
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
        definition = _workflow_definition(
            workflow_models.get(flow.get("workflow_template")),
            flow.get("workflow_template"),
        )
        details = FLOW_OPERATING_DETAILS.get(flow["key"], {})
        sample_queue = []
        for item in details.get("queue", []):
            sample_queue.append({
                **item,
                "assigned_agent": flow.get("primary_agent"),
                "approval_required": bool(flow.get("approval_required")),
                "example": True,
            })
        steps = _workflow_steps(definition)
        human_approval_steps = [
            step for step in steps if step.get("type") == "human_approval"
        ]
        review_gate = details.get("review_gate") or {
            "label": "Staff review",
            "reviewer": "Practice team",
            "reason": "The agent prepares the packet; staff confirm before any sensitive action.",
        }
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
            "packet_checklist": details.get("packet_checklist", []),
            "sample_queue": sample_queue,
            "workflow_steps": steps,
            "human_approval_steps": human_approval_steps,
            "review_gate": {
                **review_gate,
                "enforced_by_workflow": bool(human_approval_steps),
            },
            "operator_actions": [
                "Open or create the source packet in Drive/OneDrive.",
                "Run or dry-run the workflow template when file storage is connected.",
                "Route the generated packet to the named reviewer before external action.",
            ],
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
        "launch_context": PRACTICE_LAUNCH_CONTEXT,
        "summary": summary,
        "agents": [
            _agent_row(agents_by_name.get(spec["name"]), spec, agents_by_name=agents_by_name)
            for spec in manifest.agents
        ],
        "storage": storage_rows,
        "flows": flow_rows,
        "specialist_lanes": _specialist_lanes(manifest.variant),
        "workflows": list(workflow_rows.values()),
        "future_practice_systems": FUTURE_PRACTICE_SYSTEMS,
    }
