"""Native workspace pack registry.

Workspaces are tenant-enabled composition layers over the platform's
existing primitives. This module is intentionally code-defined for the MVP:
native packs are typed, versioned in git, and installed per tenant through
``tenant_workspace_installs``.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional, Protocol

from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.models.agent_permission import AgentPermission
from app.models.tenant import Tenant
from app.models.tenant_features import TenantFeatures
from app.models.tenant_workspace import (
    TenantWorkspaceAuditLog,
    TenantWorkspaceInstall,
)
from app.models.user import User
from app.services.provisioning.vet_manifest import get_manifest
from app.services.vet_practice_dashboard import build_vet_practice_dashboard

WidgetState = Literal[
    "ready",
    "setup_required",
    "empty",
    "error",
    "missing_permission",
    "unsupported",
]

FEATURE_FLAG_FIELDS = {
    "native_workspace_packs": "native_workspace_packs",
}


@dataclass(frozen=True)
class WorkspaceWidgetDefinition:
    key: str
    title: str
    widget_type: str
    description: str = ""
    span: int = 1
    config: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "type": self.widget_type,
            "description": self.description,
            "span": self.span,
            "config": self.config,
        }


@dataclass(frozen=True)
class WorkspacePackDefinition:
    slug: str
    label: str
    description: str
    status: str
    icon: str
    version: str
    feature_flag: Optional[str]
    required_capabilities: tuple[str, ...]
    widgets: tuple[WorkspaceWidgetDefinition, ...]
    setup_requirements: tuple[str, ...] = ()
    category: str = "native"

    @property
    def route(self) -> str:
        if self.category == "core":
            return "/dashboard"
        return f"/workspaces/{self.slug}"

    def layout(self) -> list[dict[str, Any]]:
        return [
            {
                "widget_key": widget.key,
                "span": widget.span,
                "order": index,
            }
            for index, widget in enumerate(self.widgets)
        ]

    def descriptor(self) -> Dict[str, Any]:
        return {
            "slug": self.slug,
            "label": self.label,
            "description": self.description,
            "status": self.status,
            "icon": self.icon,
            "version": self.version,
            "feature_flag": self.feature_flag,
            "required_capabilities": list(self.required_capabilities),
            "route": self.route,
            "category": self.category,
            "widgets": [widget.as_dict() for widget in self.widgets],
            "setup_requirements": list(self.setup_requirements),
        }


class WorkspaceProvider(Protocol):
    slug: str

    def summary(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> Dict[str, Any]:
        ...

    def widget(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        widget_key: str,
        user_id: uuid.UUID | None = None,
    ) -> Dict[str, Any]:
        ...


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def widget_payload(
    key: str,
    *,
    state: WidgetState = "ready",
    data: Optional[Dict[str, Any]] = None,
    setup_blockers: Optional[list[str]] = None,
    example: bool = False,
    cache_ttl_seconds: int = 0,
    refreshable: bool = True,
    last_success_at: Optional[str] = None,
    error_code: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "key": key,
        "state": state,
        "data": data or {},
        "setup_blockers": setup_blockers or [],
        "updated_at": _utc_now_iso(),
        "example": example,
        "cache_ttl_seconds": cache_ttl_seconds,
        "refreshable": refreshable,
        "last_success_at": last_success_at,
        "error_code": error_code,
    }


def _install_snapshot(install: TenantWorkspaceInstall | None) -> Dict[str, Any] | None:
    if install is None:
        return None
    return {
        "id": str(install.id),
        "workspace_slug": install.workspace_slug,
        "status": install.status,
        "display_order": install.display_order,
        "pinned": install.pinned,
        "config": install.config or {},
        "installed_version": install.installed_version,
        "enabled_at": install.enabled_at.isoformat() if install.enabled_at else None,
        "disabled_at": install.disabled_at.isoformat() if install.disabled_at else None,
    }


def _feature_flag_field(feature_flag: str | None) -> str | None:
    if feature_flag is None:
        return None
    return FEATURE_FLAG_FIELDS.get(feature_flag)


def _feature_enabled(
    db: Session,
    tenant_id: uuid.UUID,
    pack: WorkspacePackDefinition,
) -> bool:
    field = _feature_flag_field(pack.feature_flag)
    if field is None:
        return True
    row = (
        db.query(TenantFeatures)
        .filter(TenantFeatures.tenant_id == tenant_id)
        .first()
    )
    return bool(row and getattr(row, field, False))


def _ensure_feature_enabled(
    db: Session,
    tenant_id: uuid.UUID,
    pack: WorkspacePackDefinition,
) -> None:
    field = _feature_flag_field(pack.feature_flag)
    if field is None:
        return
    row = (
        db.query(TenantFeatures)
        .filter(TenantFeatures.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        row = TenantFeatures(tenant_id=tenant_id)
        db.add(row)
    setattr(row, field, True)
    db.flush()


def _variant_from_install(install: TenantWorkspaceInstall | None) -> str:
    config = install.config if install and isinstance(install.config, dict) else {}
    variant = config.get("fleet_variant")
    if variant in {"gp_full", "cardiology_v1"}:
        return variant
    return "gp_full"


def _workspace_agent_names(
    pack: WorkspacePackDefinition,
    install: TenantWorkspaceInstall | None,
) -> list[str]:
    if pack.slug != "vet-practice":
        return []
    manifest = get_manifest(_variant_from_install(install))
    return [spec["name"] for spec in manifest.agents]


def _can_view_workspace(
    db: Session,
    tenant_id: uuid.UUID,
    pack: WorkspacePackDefinition,
    install: TenantWorkspaceInstall | None,
    user_id: uuid.UUID | None,
) -> bool:
    if pack.category == "core" or user_id is None:
        return True
    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == tenant_id)
        .first()
    )
    if user is None:
        return False
    if user.is_superuser:
        return True
    if install and install.installed_by == user.id:
        return True

    agent_names = _workspace_agent_names(pack, install)
    if not agent_names:
        return False
    agent_ids = [
        row[0]
        for row in (
            db.query(Agent.id)
            .filter(
                Agent.tenant_id == tenant_id,
                Agent.name.in_(agent_names),
            )
            .all()
        )
    ]
    if not agent_ids:
        return False
    return (
        db.query(AgentPermission.id)
        .filter(
            AgentPermission.tenant_id == tenant_id,
            AgentPermission.agent_id.in_(agent_ids),
            AgentPermission.principal_type == "user",
            AgentPermission.principal_id == user.id,
            AgentPermission.permission.in_(["viewer", "edit", "admin"]),
        )
        .first()
        is not None
    )


def _audit(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    workspace_slug: str,
    install: TenantWorkspaceInstall | None,
    actor_user_id: uuid.UUID | None,
    event_type: str,
    before: Dict[str, Any] | None,
    after: Dict[str, Any] | None,
    reason: str | None = None,
) -> None:
    db.add(
        TenantWorkspaceAuditLog(
            tenant_id=tenant_id,
            workspace_slug=workspace_slug,
            install_id=install.id if install else None,
            actor_user_id=actor_user_id,
            event_type=event_type,
            before=before,
            after=after,
            reason=reason,
        )
    )


def _setup_state_from_summary(summary: dict[str, Any]) -> tuple[WidgetState, list[str]]:
    blockers: list[str] = []
    if summary.get("agents_present", 0) < summary.get("agents_expected", 0):
        blockers.append("Run veterinary workspace provisioning to seed the practice agents.")
    if summary.get("workflows_installed", 0) < summary.get("workflows_expected", 0):
        blockers.append("Install the native practice workflow templates for this tenant.")
    if summary.get("storage_connected", 0) < summary.get("storage_expected", 0):
        blockers.append("Connect Google Drive or OneDrive before claiming file packet automation is live.")
    return ("setup_required", blockers) if blockers else ("ready", [])


class VetWorkspaceProvider:
    slug = "vet-practice"

    def _variant(self, db: Session, tenant_id: uuid.UUID) -> str:
        install = _query_install(db, tenant_id, self.slug)
        return _variant_from_install(install)

    def _dashboard(self, db: Session, tenant_id: uuid.UUID) -> Dict[str, Any]:
        return build_vet_practice_dashboard(
            db,
            tenant_id,
            variant=self._variant(db, tenant_id),
        )

    def summary(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> Dict[str, Any]:
        dashboard = self._dashboard(db, tenant_id)
        state, blockers = _setup_state_from_summary(dashboard.get("summary") or {})
        queue_count = sum(len(flow.get("sample_queue") or []) for flow in dashboard.get("flows") or [])
        return {
            "state": state,
            "setup_blockers": blockers,
            "readiness": dashboard.get("summary") or {},
            "open_work_count": 0,
            "example_work_count": queue_count,
            "example": True,
            "practice_name": dashboard.get("practice_name"),
            "updated_at": _utc_now_iso(),
        }

    def widget(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        widget_key: str,
        user_id: uuid.UUID | None = None,
    ) -> Dict[str, Any]:
        try:
            dashboard = self._dashboard(db, tenant_id)
            state, blockers = _setup_state_from_summary(dashboard.get("summary") or {})
        except Exception:
            return widget_payload(
                widget_key,
                state="error",
                setup_blockers=["The veterinary workspace provider failed safely."],
                refreshable=True,
                error_code="provider_error",
            )

        flows = dashboard.get("flows") or []
        agents = dashboard.get("agents") or []
        storage = dashboard.get("storage") or []

        if widget_key == "launch_brief":
            return widget_payload(
                widget_key,
                state="ready",
                data={
                    "practice_name": dashboard.get("practice_name"),
                    "mode": dashboard.get("mode"),
                    "launch_context": dashboard.get("launch_context") or {},
                },
                example=True,
                refreshable=False,
                cache_ttl_seconds=300,
            )

        if widget_key == "daily_work_queue":
            items: list[dict[str, Any]] = []
            for flow in flows:
                for item in flow.get("sample_queue") or []:
                    items.append({
                        **item,
                        "flow_key": flow.get("key"),
                        "flow_name": flow.get("name"),
                        "primary_agent": flow.get("primary_agent"),
                    })
            return widget_payload(
                widget_key,
                state="empty" if not items else state,
                data={"items": items, "flows": flows},
                setup_blockers=blockers,
                example=True,
            )

        if widget_key == "file_packet_flows":
            return widget_payload(
                widget_key,
                state=state,
                data={
                    "flows": [
                        {
                            "key": flow.get("key"),
                            "name": flow.get("name"),
                            "description": flow.get("description"),
                            "ready": flow.get("ready"),
                            "readiness": flow.get("readiness"),
                            "packet_checklist": flow.get("packet_checklist"),
                            "workflow_steps": flow.get("workflow_steps"),
                            "operator_actions": flow.get("operator_actions"),
                            "workflow": flow.get("workflow"),
                        }
                        for flow in flows
                    ]
                },
                setup_blockers=blockers,
                example=True,
            )

        if widget_key == "review_gates":
            return widget_payload(
                widget_key,
                state="ready" if flows else "empty",
                data={
                    "gates": [
                        {
                            "flow_key": flow.get("key"),
                            "flow_name": flow.get("name"),
                            "approval_required": flow.get("approval_required"),
                            "review_gate": flow.get("review_gate"),
                            "human_approval_steps": flow.get("human_approval_steps"),
                        }
                        for flow in flows
                    ]
                },
                example=True,
            )

        if widget_key == "agent_fleet":
            return widget_payload(
                widget_key,
                state=state,
                data={"agents": agents},
                setup_blockers=blockers,
            )

        if widget_key == "system_readiness":
            return widget_payload(
                widget_key,
                state=state,
                data={
                    "summary": dashboard.get("summary") or {},
                    "storage": storage,
                    "practice_systems": dashboard.get("future_practice_systems") or [],
                },
                setup_blockers=blockers,
            )

        if widget_key == "specialist_referral_lane":
            lanes = dashboard.get("specialist_lanes") or []
            return widget_payload(
                widget_key,
                state="empty" if not lanes else "ready",
                data={"lanes": lanes},
                example=True,
            )

        return widget_payload(widget_key, state="unsupported", error_code="unknown_widget")


class SalesCrmWorkspaceProvider:
    slug = "sales-crm"

    def summary(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
    ) -> Dict[str, Any]:
        return {
            "state": "setup_required",
            "setup_blockers": ["Bind sales agents, follow-up workflows, and source systems before using this workspace."],
            "readiness": {"agents_present": 0, "agents_expected": 3, "workflows_installed": 0, "workflows_expected": 2},
            "open_work_count": 0,
            "example": False,
            "updated_at": _utc_now_iso(),
        }

    def widget(
        self,
        db: Session,
        tenant_id: uuid.UUID,
        widget_key: str,
        user_id: uuid.UUID | None = None,
    ) -> Dict[str, Any]:
        if widget_key in {"pipeline_overview", "follow_up_queue", "approval_gates"}:
            return widget_payload(
                widget_key,
                state="setup_required",
                data={"items": []},
                setup_blockers=["This native pack is a registry validation stub until a sales tenant binds real primitives."],
            )
        return widget_payload(widget_key, state="unsupported", error_code="unknown_widget")


CORE_WORKSPACE = WorkspacePackDefinition(
    slug="alpha-control",
    label="Alpha Control",
    description="Generic AgentProvision orchestration command center.",
    status="production",
    icon="FaHome",
    version="1.0.0",
    feature_flag=None,
    required_capabilities=("chat", "agents", "workflows", "files"),
    widgets=(),
    category="core",
)

VET_PRACTICE_PACK = WorkspacePackDefinition(
    slug="vet-practice",
    label="Vet Practice",
    description="File-first operating workspace for veterinary practice management.",
    status="production",
    icon="FaHeartbeat",
    version="1.0.0",
    feature_flag="native_workspace_packs",
    required_capabilities=("drive_packets", "approval_gates", "agent_handoffs"),
    setup_requirements=("vet practice provisioning", "Drive or OneDrive file storage"),
    widgets=(
        WorkspaceWidgetDefinition("launch_brief", "Launch Brief", "launch_brief", span=2),
        WorkspaceWidgetDefinition("daily_work_queue", "Daily Work Queue", "work_queue", span=2),
        WorkspaceWidgetDefinition("file_packet_flows", "File Packet Flows", "flow_board", span=2),
        WorkspaceWidgetDefinition("review_gates", "Review Gates", "review_gates", span=1),
        WorkspaceWidgetDefinition("agent_fleet", "Agent Fleet", "agent_fleet", span=1),
        WorkspaceWidgetDefinition("system_readiness", "Practice Software Prep", "system_readiness", span=1),
        WorkspaceWidgetDefinition("specialist_referral_lane", "Specialist Referral Lane", "referral_lane", span=1),
    ),
    category="veterinary",
)

SALES_CRM_PACK = WorkspacePackDefinition(
    slug="sales-crm",
    label="Sales CRM",
    description="Native validation pack for account, deal, and follow-up operations.",
    status="staging",
    icon="FaChartLine",
    version="0.1.0",
    feature_flag="native_workspace_packs",
    required_capabilities=("agent_handoffs", "approval_gates"),
    setup_requirements=("sales agent bindings", "follow-up workflow templates"),
    widgets=(
        WorkspaceWidgetDefinition("pipeline_overview", "Pipeline Overview", "metric_strip", span=1),
        WorkspaceWidgetDefinition("follow_up_queue", "Follow-Up Queue", "work_queue", span=1),
        WorkspaceWidgetDefinition("approval_gates", "Approval Gates", "review_gates", span=1),
    ),
    category="sales",
)

PACKS: dict[str, WorkspacePackDefinition] = {
    CORE_WORKSPACE.slug: CORE_WORKSPACE,
    VET_PRACTICE_PACK.slug: VET_PRACTICE_PACK,
    SALES_CRM_PACK.slug: SALES_CRM_PACK,
}

PROVIDERS: dict[str, WorkspaceProvider] = {
    "vet-practice": VetWorkspaceProvider(),
    "sales-crm": SalesCrmWorkspaceProvider(),
}


def get_workspace_pack(slug: str) -> WorkspacePackDefinition | None:
    return PACKS.get(slug)


def native_workspace_catalog() -> list[WorkspacePackDefinition]:
    return [
        pack for pack in PACKS.values()
        if pack.category != "core" and pack.status != "deprecated"
    ]


def _query_install(
    db: Session,
    tenant_id: uuid.UUID,
    workspace_slug: str,
) -> TenantWorkspaceInstall | None:
    return (
        db.query(TenantWorkspaceInstall)
        .filter(
            TenantWorkspaceInstall.tenant_id == tenant_id,
            TenantWorkspaceInstall.workspace_slug == workspace_slug,
        )
        .first()
    )


def require_enabled_install(
    db: Session,
    tenant_id: uuid.UUID,
    workspace_slug: str,
) -> TenantWorkspaceInstall | None:
    if workspace_slug == CORE_WORKSPACE.slug:
        return None
    return (
        db.query(TenantWorkspaceInstall)
        .filter(
            TenantWorkspaceInstall.tenant_id == tenant_id,
            TenantWorkspaceInstall.workspace_slug == workspace_slug,
            TenantWorkspaceInstall.status == "enabled",
        )
        .first()
    )


def _descriptor_for_pack(
    db: Session,
    tenant_id: uuid.UUID,
    pack: WorkspacePackDefinition,
    *,
    install: TenantWorkspaceInstall | None = None,
    user_id: uuid.UUID | None = None,
    include_summary: bool = True,
) -> Dict[str, Any]:
    descriptor = pack.descriptor()
    descriptor["install"] = _install_snapshot(install)
    descriptor["feature_enabled"] = _feature_enabled(db, tenant_id, pack)
    descriptor["installed"] = pack.category == "core" or install is not None
    descriptor["enabled"] = (
        pack.category == "core"
        or (
            descriptor["feature_enabled"]
            and install is not None
            and install.status == "enabled"
        )
    )
    descriptor["display_order"] = install.display_order if install else 0
    descriptor["pinned"] = bool(install.pinned) if install else pack.category == "core"
    if include_summary and descriptor["enabled"]:
        provider = PROVIDERS.get(pack.slug)
        descriptor["summary"] = provider.summary(db, tenant_id, user_id=user_id) if provider else {
            "state": "ready",
            "setup_blockers": [],
            "readiness": {},
            "open_work_count": 0,
            "example": False,
            "updated_at": _utc_now_iso(),
        }
    return descriptor


def list_enabled_workspaces(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
    include_core: bool = True,
) -> list[dict[str, Any]]:
    rows = (
        db.query(TenantWorkspaceInstall)
        .filter(
            TenantWorkspaceInstall.tenant_id == tenant_id,
            TenantWorkspaceInstall.status == "enabled",
        )
        .order_by(TenantWorkspaceInstall.display_order.asc(), TenantWorkspaceInstall.created_at.asc())
        .all()
    )
    descriptors: list[dict[str, Any]] = []
    if include_core:
        descriptors.append(_descriptor_for_pack(db, tenant_id, CORE_WORKSPACE, user_id=user_id))
    for install in rows:
        pack = get_workspace_pack(install.workspace_slug)
        if pack is None or pack.status == "deprecated":
            continue
        if not _feature_enabled(db, tenant_id, pack):
            continue
        if not _can_view_workspace(db, tenant_id, pack, install, user_id):
            continue
        descriptors.append(_descriptor_for_pack(db, tenant_id, pack, install=install, user_id=user_id))
    return descriptors


def list_catalog(
    db: Session,
    tenant_id: uuid.UUID,
    *,
    user_id: uuid.UUID | None = None,
) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []
    user = (
        db.query(User)
        .filter(User.id == user_id, User.tenant_id == tenant_id)
        .first()
        if user_id is not None
        else None
    )
    for pack in native_workspace_catalog():
        install = _query_install(db, tenant_id, pack.slug)
        feature_enabled = _feature_enabled(db, tenant_id, pack)
        if not feature_enabled and not bool(user and user.is_superuser):
            continue
        descriptors.append(
            _descriptor_for_pack(
                db,
                tenant_id,
                pack,
                install=install,
                user_id=user_id,
                include_summary=bool(install and install.status == "enabled"),
            )
        )
    return descriptors


def get_workspace_detail(
    db: Session,
    tenant_id: uuid.UUID,
    slug: str,
    *,
    user_id: uuid.UUID | None = None,
    include_widgets: bool = True,
) -> dict[str, Any] | None:
    pack = get_workspace_pack(slug)
    if pack is None:
        return None

    install = require_enabled_install(db, tenant_id, slug)
    if pack.category != "core" and install is None:
        return None
    if not _feature_enabled(db, tenant_id, pack):
        return None
    if not _can_view_workspace(db, tenant_id, pack, install, user_id):
        return None

    descriptor = _descriptor_for_pack(db, tenant_id, pack, install=install, user_id=user_id)
    detail = {
        "descriptor": descriptor,
        "layout": pack.layout(),
        "widgets": [],
    }
    if include_widgets:
        provider = PROVIDERS.get(slug)
        detail["widgets"] = [
            provider.widget(db, tenant_id, widget.key, user_id=user_id)
            if provider else widget_payload(widget.key, state="unsupported", error_code="missing_provider")
            for widget in pack.widgets
        ]
    return detail


def get_workspace_widget(
    db: Session,
    tenant_id: uuid.UUID,
    slug: str,
    widget_key: str,
    *,
    user_id: uuid.UUID | None = None,
) -> dict[str, Any] | None:
    pack = get_workspace_pack(slug)
    if pack is None:
        return None
    install = require_enabled_install(db, tenant_id, slug)
    if install is None:
        return None
    if not _feature_enabled(db, tenant_id, pack):
        return None
    if not _can_view_workspace(db, tenant_id, pack, install, user_id):
        return None
    provider = PROVIDERS.get(slug)
    if provider is None:
        return widget_payload(widget_key, state="unsupported", error_code="missing_provider")
    return provider.widget(db, tenant_id, widget_key, user_id=user_id)


def install_workspace_pack(
    db: Session,
    tenant_id: uuid.UUID,
    workspace_slug: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    display_order: int | None = None,
    pinned: bool = True,
    config: Optional[Dict[str, Any]] = None,
    status: str = "enabled",
    reason: str | None = None,
) -> TenantWorkspaceInstall:
    pack = get_workspace_pack(workspace_slug)
    if pack is None or pack.category == "core":
        raise ValueError(f"Unknown native workspace pack: {workspace_slug}")
    if status not in {"enabled", "disabled"}:
        raise ValueError("Workspace install status must be enabled or disabled")
    if db.query(Tenant.id).filter(Tenant.id == tenant_id).first() is None:
        raise ValueError(f"Tenant {tenant_id} does not exist")

    now = datetime.utcnow()
    if status == "enabled":
        _ensure_feature_enabled(db, tenant_id, pack)
    existing = _query_install(db, tenant_id, workspace_slug)
    before = _install_snapshot(existing)
    if existing is None:
        install = TenantWorkspaceInstall(
            tenant_id=tenant_id,
            workspace_slug=workspace_slug,
            status=status,
            display_order=display_order if display_order is not None else 100,
            pinned=pinned,
            config=config or {},
            installed_by=actor_user_id,
            installed_version=pack.version,
            enabled_at=now if status == "enabled" else None,
            disabled_at=now if status == "disabled" else None,
        )
        db.add(install)
        db.flush()
        _audit(
            db,
            tenant_id=tenant_id,
            workspace_slug=workspace_slug,
            install=install,
            actor_user_id=actor_user_id,
            event_type="install",
            before=before,
            after=_install_snapshot(install),
            reason=reason,
        )
        return install

    existing.display_order = display_order if display_order is not None else existing.display_order
    existing.pinned = pinned
    existing.config = config if config is not None else (existing.config or {})
    if existing.installed_by is None and actor_user_id is not None:
        existing.installed_by = actor_user_id
    existing.installed_version = pack.version
    if existing.status != status:
        existing.status = status
        if status == "enabled":
            existing.enabled_at = now
            existing.disabled_at = None
        else:
            existing.disabled_at = now
    elif status == "enabled" and existing.disabled_at is not None:
        existing.disabled_at = None
    existing.updated_at = now
    db.add(existing)
    db.flush()
    _audit(
        db,
        tenant_id=tenant_id,
        workspace_slug=workspace_slug,
        install=existing,
        actor_user_id=actor_user_id,
        event_type="enable" if status == "enabled" else "disable",
        before=before,
        after=_install_snapshot(existing),
        reason=reason,
    )
    return existing


def update_workspace_install(
    db: Session,
    tenant_id: uuid.UUID,
    workspace_slug: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    status: str | None = None,
    display_order: int | None = None,
    pinned: bool | None = None,
    config: Optional[Dict[str, Any]] = None,
    reason: str | None = None,
) -> TenantWorkspaceInstall | None:
    install = _query_install(db, tenant_id, workspace_slug)
    if install is None:
        return None
    before = _install_snapshot(install)
    now = datetime.utcnow()

    if status is not None:
        if status not in {"enabled", "disabled"}:
            raise ValueError("Workspace install status must be enabled or disabled")
        if install.status != status:
            install.status = status
            if status == "enabled":
                install.enabled_at = now
                install.disabled_at = None
            else:
                install.disabled_at = now
    if display_order is not None:
        install.display_order = display_order
    if pinned is not None:
        install.pinned = pinned
    if config is not None:
        install.config = config
    install.updated_at = now
    db.add(install)
    db.flush()
    _audit(
        db,
        tenant_id=tenant_id,
        workspace_slug=workspace_slug,
        install=install,
        actor_user_id=actor_user_id,
        event_type="update",
        before=before,
        after=_install_snapshot(install),
        reason=reason,
    )
    return install


def disable_workspace_install(
    db: Session,
    tenant_id: uuid.UUID,
    workspace_slug: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    reason: str | None = None,
) -> TenantWorkspaceInstall | None:
    return update_workspace_install(
        db,
        tenant_id,
        workspace_slug,
        actor_user_id=actor_user_id,
        status="disabled",
        reason=reason,
    )


__all__ = [
    "CORE_WORKSPACE",
    "VET_PRACTICE_PACK",
    "SALES_CRM_PACK",
    "get_workspace_detail",
    "get_workspace_pack",
    "get_workspace_widget",
    "install_workspace_pack",
    "list_catalog",
    "list_enabled_workspaces",
    "native_workspace_catalog",
    "disable_workspace_install",
    "update_workspace_install",
    "widget_payload",
]
