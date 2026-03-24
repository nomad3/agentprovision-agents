-- Phase 2 follow-up: evidence pack retention metadata

ALTER TABLE safety_evidence_packs
ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITHOUT TIME ZONE;

UPDATE safety_evidence_packs
SET expires_at = COALESCE(expires_at, created_at + INTERVAL '30 days');

ALTER TABLE safety_evidence_packs
ALTER COLUMN expires_at SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_safety_evidence_packs_expires_at
ON safety_evidence_packs(expires_at);
