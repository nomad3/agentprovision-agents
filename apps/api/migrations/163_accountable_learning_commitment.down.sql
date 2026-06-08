-- 163_accountable_learning_commitment.down.sql

BEGIN;

DROP INDEX IF EXISTS idx_commitment_records_redflag;

ALTER TABLE commitment_records DROP COLUMN IF EXISTS contract_id;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS proof_required;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS proof_refs;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS stakeholder_refs;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS blocker_refs;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS risk_threshold;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS escalation_policy;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS checkpoint_at;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS escalation_at;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS last_verified_at;
ALTER TABLE commitment_records DROP COLUMN IF EXISTS stale_after;

DELETE FROM _migrations WHERE filename = '163_accountable_learning_commitment.sql';

COMMIT;
