-- 126_tenants_onboarding_state.sql
--
-- Adds onboarding state to tenants so `ap quickstart` (and the web
-- onboarding wizard) can auto-trigger on first login. Once a tenant
-- completes the wedge picker + initial training, `onboarded_at` is
-- stamped and auto-trigger never fires again. A user who opts to
-- skip stamps `onboarding_deferred_at`; auto-trigger is suppressed
-- on subsequent logins, but an explicit `ap quickstart` (or
-- `--force`) still works.
--
-- See: docs/plans/2026-05-11-ap-quickstart-design.md §2.1, §7.0.

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS onboarded_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS onboarding_deferred_at TIMESTAMP NULL,
    ADD COLUMN IF NOT EXISTS onboarding_source VARCHAR(32) NULL;

-- Index lets `GET /onboarding/status` answer in one indexed lookup
-- per request without scanning a full tenants table at higher tenant
-- counts. NULL onboarded_at is the common case (un-onboarded), so
-- a partial index keeps the index small.
CREATE INDEX IF NOT EXISTS idx_tenants_onboarded
    ON tenants (id)
    WHERE onboarded_at IS NULL;

COMMENT ON COLUMN tenants.onboarded_at IS
    'Timestamp the tenant completed initial wedge-training (ap quickstart or web /onboarding). NULL = un-onboarded; auto-trigger fires.';
COMMENT ON COLUMN tenants.onboarding_deferred_at IS
    'Timestamp the user pressed Skip during onboarding. Suppresses auto-trigger; explicit ap quickstart still works.';
COMMENT ON COLUMN tenants.onboarding_source IS
    'cli | web — which surface initiated the completed onboarding. Audit only; no business logic keys off this.';
