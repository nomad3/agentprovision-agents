-- 168_enable_desktop_perception.sql
-- Luna Phase 5.2 — enable GOVERNED PERCEPTION across the environment.
--
-- desktop_control_enabled is the master switch that gates observation (Luna L-N2),
-- and is the flag enforced by the P5.2 governed-perception upload
-- (record_observation_artifact). Turning it on enables Luna to capture + quarantine
-- screenshots of the frontmost window.
--
-- This enables PERCEPTION ONLY. It does NOT enable ACTUATION: pointer/keyboard
-- actuation is governed separately by pointer_control_enabled / keyboard_control_enabled
-- (left FALSE here) + the client LUNA_ACTUATION_* env flags + signed Ed25519 envelopes
-- + per-action approval grants. So enabling the master switch cannot drive the
-- mouse/keyboard.
--
-- Perception is gated/audited/no-read-by-construction/TTL-cleaned (PR4) and is
-- further bounded by Luna desktop-client install + macOS Screen Recording grant +
-- device enrollment + an active session — so the effective reach is wherever the
-- Luna desktop client actually runs.

UPDATE tenant_features SET desktop_control_enabled = true;
ALTER TABLE tenant_features ALTER COLUMN desktop_control_enabled SET DEFAULT true;
