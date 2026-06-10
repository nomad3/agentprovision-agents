"""TenantFeatures model for feature flags and limits."""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.db.base import Base


class TenantFeatures(Base):
    """Tenant feature flags and usage limits."""
    __tablename__ = "tenant_features"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id = Column(UUID(as_uuid=True), ForeignKey("tenants.id"), unique=True, nullable=False)

    # Core Features
    agents_enabled = Column(Boolean, default=True)
    agent_groups_enabled = Column(Boolean, default=True)
    datasets_enabled = Column(Boolean, default=True)
    chat_enabled = Column(Boolean, default=True)
    multi_llm_enabled = Column(Boolean, default=True)
    agent_memory_enabled = Column(Boolean, default=True)

    # AI Intelligence Features
    ai_insights_enabled = Column(Boolean, default=True)
    ai_recommendations_enabled = Column(Boolean, default=True)
    ai_anomaly_detection = Column(Boolean, default=True)

    # Reinforcement Learning Features
    rl_enabled = Column(Boolean, default=True)
    rl_settings = Column(JSONB, nullable=False, default=lambda: {
        "exploration_rate": 0.1,
        "opt_in_global_learning": True,
        "use_global_baseline": True,
        "min_tenant_experiences": 50,
        "blend_alpha_growth": 0.01,
        "reward_weights": {"implicit": 0.3, "explicit": 0.5, "admin": 0.2},
        "review_schedule": "weekly",
        "per_decision_overrides": {}
    })

    # Usage Limits
    max_agents = Column(Integer, default=10)
    max_agent_groups = Column(Integer, default=5)
    monthly_token_limit = Column(Integer, default=1000000)
    storage_limit_gb = Column(Float, default=10.0)

    # UI Customization
    hide_agentprovision_branding = Column(Boolean, default=False)

    # Plan Type
    plan_type = Column(String, default="starter")  # starter, professional, enterprise

    # LLM Provider Selection
    active_llm_provider = Column(String(50), default="gemini_llm")

    # CLI Orchestrator
    cli_orchestrator_enabled = Column(Boolean, default=False)
    default_cli_platform = Column(String(50), default="claude_code")

    # Resilient CLI orchestrator (Phase 2 cutover gate). Default OFF —
    # legacy chain-walk path runs at flag=False with byte-identical
    # behaviour. See migration 121 + design doc §3 for cutover plan.
    #
    # server_default added 2026-05-20 per #631 retroactive review I1:
    # without it, an ORM INSERT against a pre-migration schema
    # (operator-apply-after-deploy window) sends the column as part of
    # the row and fails on environments where the column doesn't yet
    # exist. server_default lets Postgres fill the missing column on
    # default-bearing INSERTs.
    use_resilient_executor = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # Shadow-mode sub-flag. When `use_resilient_executor` is FALSE, we
    # run the new path in shadow alongside the legacy path so we can
    # diff outcomes. Default FALSE = stubbed shadow (replays legacy
    # outcome, no real Temporal/LLM dispatch — the cheap mass path).
    # TRUE = real adapter dispatch (~2x cost; only for ~48h internal
    # tenant validation per the cutover plan).
    shadow_mode_real_dispatch = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # CLI stream-output rollout gate (migration 134). When TRUE the
    # code-worker switches Claude Code to `--output-format stream-json`
    # and streams every reasoning/tool_use/tool_result event into the
    # terminal card. Default OFF prod; seeded ON for the saguilera
    # test tenant. Plan:
    # docs/plans/2026-05-16-terminal-full-cli-output.md §9
    cli_stream_output = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # Per-tenant opt-in for `creative` reflection kind (O3 locked
    # decision #1). Default OFF — the synthesis loop produces
    # creative reflections only for tenants that flipped this.
    # Enforced by reflection_validators.validate_creative_opt_in
    # inside write_reflections. Migration 143.
    creative_reflections_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # Per-tenant kill-switch for the value layer (#647). When FALSE
    # every consult() call returns allow/kill_switch_off. Operators
    # flip per tenant after seeding their value set via PUT /api/v1/
    # luna/values. Default OFF — locked design decision §6 of
    # docs/plans/2026-05-21-luna-value-layer-design.md. Migration 144.
    value_layer_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # NightlyReflectionWorkflow (O2 of #616) per-tenant kill-switch.
    # Default OFF in prod — locked decision #4 in the canonical design.
    # The workflow checks this flag at top-of-run and short-circuits
    # with reason='kill_switch_off' when FALSE. Operators flip per
    # tenant after reviewing dry-run output. Migration 142.
    nightly_reflection_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # Per-tenant opt-in for the red-flag engine (Accountable Learning &
    # Commitment System, plan 2026-06-08 §9). Default OFF, fail-closed.
    # Operators flip per tenant after reviewing dry-run output. Migration 164.
    red_flag_engine_enabled = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # ── Luna macOS computer-use (desktop control) per-tenant gating ──────
    # PR4 of the 2026-06-09 productionization plan. Superuser/operator-only
    # (excluded from member-writable feature updates, enforced in PR4b).
    #
    # `desktop_control_enabled` is the master switch that ALSO gates observation
    # (Luna L-N2) and is the flag enforced by the P5.2 governed-perception upload
    # (record_observation_artifact). Migration 168 enables it across the
    # environment — this turns on PERCEPTION (screenshot capture → quarantine),
    # NOT actuation. Actuation still requires the per-capability flags below
    # (left fail-closed OFF) + the client LUNA_ACTUATION_* env flags + signed
    # Ed25519 envelopes + approval grants, and PR4b wires those flags into the
    # claim boundary. Migrations 166 (create) + 168 (enable master).
    desktop_control_enabled = Column(  # master switch (also gates observation)
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Actuation stays fail-closed OFF — PR4b wires these into the claim boundary.
    pointer_control_enabled = Column(  # Phase 3 pointer actuation
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    keyboard_control_enabled = Column(  # Phase 4 keyboard actuation
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # Per-tenant bundle allowlist; the intended effective list = per-tenant ∩
    # global platform floor (DESKTOP_CONTROL_CANARY_BUNDLE_ALLOWLIST). NOTE: this
    # column is INERT on the actuation path today — PR4b enforces the per-capability
    # flags only and still uses the env floor (_desktop_control_canary_bundle_
    # allowlist); the per-tenant ∩ floor resolution lands in a later PR4 step
    # (PR4c). No server_default (Python default=list only) — same as rl_settings —
    # so SQLite Base.metadata.create_all in unit tests does not emit the
    # Postgres-only `'[]'::jsonb` cast, which SQLite rejects. The DB-level default
    # lives in migration 166 for Postgres prod.
    native_control_target_allowlist = Column(
        JSONB, nullable=False, default=list
    )

    # CPA software export format for the Bookkeeper Agent's weekly
    # categorized output. AAHA stays canonical — the Bookkeeper still
    # categorizes against the AAHA chart of accounts; this just picks
    # which format adapter converts the categorized rows into the
    # CPA's preferred import file. Migration 117.
    # Valid values: xlsx | csv | quickbooks_iif | quickbooks_qbo |
    #               xero_csv | sage_intacct_csv
    cpa_export_format = Column(String(32), nullable=False, default="xlsx")

    # P0a (2026-05-23): per-tenant ramp gate for the tool_audit.py
    # fail-closed default. FALSE = shadow-log denials only (don't
    # enforce). TRUE = enforce (any non-internal_key non-agent_token
    # call to a non-allowlisted tool is rejected with tier_denied).
    # Rollout sequence per docs/plans/2026-05-23-p0a-tool-permission-
    # gate-fix.md §5: flip TRUE for Simon's tenant first (24h watch),
    # then all other tenants, then remove this flag entirely in a
    # follow-up migration after 1 week stable. Migration 149.
    enforce_strict_tool_scope = Column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # GitHub primary account for repo operations.
    # Pins which connected GitHub account the MCP github tools use as
    # default when the caller doesn't pass an explicit account_email.
    # Useful when a tenant has multiple GitHub accounts wired but only
    # one is intended for repo access (e.g. employer EMU accounts that
    # only have Copilot CLI license, no repo visibility under enterprise
    # policy). Null = fall back to the multi-account fan-out behavior.
    github_primary_account = Column(String(255), nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    tenant = relationship("Tenant", back_populates="features")

    def __repr__(self):
        return f"<TenantFeatures {self.tenant_id} plan={self.plan_type}>"
