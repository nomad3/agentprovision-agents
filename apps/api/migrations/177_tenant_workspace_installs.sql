-- 177_tenant_workspace_installs.sql
--
-- Tenant-scoped native workspace pack registry. The first production pack is
-- vet-practice; existing Animal Doctor / Brett vet tenants are backfilled only
-- if those tenant rows already exist.

BEGIN;

CREATE TABLE IF NOT EXISTS tenant_workspace_installs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    workspace_slug VARCHAR(96) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'enabled',
    display_order INTEGER NOT NULL DEFAULT 100,
    pinned BOOLEAN NOT NULL DEFAULT TRUE,
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    installed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    installed_version VARCHAR(32) NOT NULL,
    enabled_at TIMESTAMPTZ,
    disabled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_tenant_workspace_install UNIQUE (tenant_id, workspace_slug),
    CONSTRAINT tenant_workspace_installs_status_check CHECK (
        status IN ('enabled', 'disabled')
    )
);

CREATE INDEX IF NOT EXISTS idx_tenant_workspace_installs_tenant_status
    ON tenant_workspace_installs (tenant_id, status, display_order);

CREATE TABLE IF NOT EXISTS tenant_workspace_audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    workspace_slug VARCHAR(96) NOT NULL,
    install_id UUID REFERENCES tenant_workspace_installs(id) ON DELETE SET NULL,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    event_type VARCHAR(48) NOT NULL,
    before JSONB,
    after JSONB,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tenant_workspace_audit_logs_tenant_slug
    ON tenant_workspace_audit_logs (tenant_id, workspace_slug, created_at DESC);

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS native_workspace_packs BOOLEAN NOT NULL DEFAULT FALSE;

WITH vet_tenants AS (
    SELECT id
    FROM tenants
    WHERE id IN (
        '7f632730-1a38-41f1-9f99-508d696dbcf1'::uuid, -- The Animal Doctor SOC
        'b7aa01e6-fe86-5813-a2f6-9152af560474'::uuid, -- BB Cardiology Demo
        '147f3f50-0a47-4f26-951c-de975ba99905'::uuid, -- Brett The Cardio Vet (live)
        'c8a2aff8-67f8-4a90-bd95-b97a31510fae'::uuid  -- Brett The Cardio Vet
    )
), inserted AS (
    INSERT INTO tenant_workspace_installs (
        tenant_id,
        workspace_slug,
        status,
        display_order,
        pinned,
        config,
        installed_version,
        enabled_at
    )
    SELECT
        id,
        'vet-practice',
        'enabled',
        10,
        TRUE,
        '{"source":"migration_backfill","reason":"existing_vet_mvp_tenant"}'::jsonb,
        '1.0.0',
        now()
    FROM vet_tenants
    ON CONFLICT (tenant_id, workspace_slug) DO NOTHING
    RETURNING id, tenant_id, workspace_slug
)
INSERT INTO tenant_workspace_audit_logs (
    tenant_id,
    workspace_slug,
    install_id,
    event_type,
    after,
    reason
)
SELECT
    tenant_id,
    workspace_slug,
    id,
    'backfill',
    '{"status":"enabled","installed_version":"1.0.0"}'::jsonb,
    'Backfilled native vet workspace for existing veterinary MVP tenant'
FROM inserted;

UPDATE tenant_features tf
SET native_workspace_packs = TRUE
FROM vet_tenants vt
WHERE tf.tenant_id = vt.id;

INSERT INTO tenant_features (
    id,
    tenant_id,
    rl_settings,
    native_workspace_packs,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid(),
    id,
    '{
        "exploration_rate": 0.1,
        "opt_in_global_learning": true,
        "use_global_baseline": true,
        "min_tenant_experiences": 50,
        "blend_alpha_growth": 0.01,
        "reward_weights": {"implicit": 0.3, "explicit": 0.5, "admin": 0.2},
        "review_schedule": "weekly",
        "per_decision_overrides": {}
    }'::jsonb,
    TRUE,
    now(),
    now()
FROM vet_tenants vt
WHERE NOT EXISTS (
    SELECT 1 FROM tenant_features tf WHERE tf.tenant_id = vt.id
);

INSERT INTO _migrations(filename) VALUES ('177_tenant_workspace_installs.sql')
ON CONFLICT DO NOTHING;

COMMIT;
