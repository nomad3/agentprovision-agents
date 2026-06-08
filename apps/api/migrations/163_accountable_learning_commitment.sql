-- 163_accountable_learning_commitment.sql
--
-- Accountable Learning & Commitment System (plan 2026-06-08).
-- Extends the existing commitment_records spine (migration 056) with the
-- proof / risk / escalation / checkpoint fields the red-flag engine (PR3) needs
-- to compute deterministic levels from ledger fields. Additive + idempotent;
-- no data migration. The plan also widens the commitment state vocabulary with
-- 'blocked','at_risk','renegotiated' — state is VARCHAR(30), so that is enforced
-- in the pydantic CommitmentState enum, not a DB enum.

BEGIN;

ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS contract_id UUID NULL;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS proof_required JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS proof_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS stakeholder_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS blocker_refs JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS risk_threshold VARCHAR(20) NULL;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS escalation_policy VARCHAR(30) NULL;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS checkpoint_at TIMESTAMP NULL;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS escalation_at TIMESTAMP NULL;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS last_verified_at TIMESTAMP NULL;
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS stale_after TIMESTAMP NULL;

-- Red-flag scan index: open work ordered by its next checkpoint so the
-- scheduled checker (PR3) can find drift cheaply per tenant.
CREATE INDEX IF NOT EXISTS idx_commitment_records_redflag
    ON commitment_records (tenant_id, checkpoint_at)
    WHERE state IN ('open', 'in_progress', 'blocked', 'at_risk');

INSERT INTO _migrations(filename) VALUES ('163_accountable_learning_commitment.sql')
ON CONFLICT DO NOTHING;

COMMIT;
