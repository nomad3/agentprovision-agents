-- Migration 117: AAHA-native bookkeeper export — per-tenant CPA software format.
--
-- Adds a `cpa_export_format` column to `tenant_features` so each tenant
-- (one practice = one CPA = one accounting platform) can pin which format
-- the weekly Bookkeeper Agent export ships in. AAHA stays canonical: the
-- Bookkeeper categorizes against the AAHA chart of accounts, then the
-- format adapter converts to whatever the CPA imports.
--
-- Supported values (validated client-side / by the MCP tool, not by a
-- DB CHECK constraint so we can ship new adapters without a schema bump):
--   - 'xlsx'           (default; AAHA tab + per-location + flagged-for-
--                       review + vendor summary)
--   - 'csv'            (generic flat CSV — importable into anything)
--   - 'quickbooks_iif' (Intuit IIF — QuickBooks Desktop)
--   - 'quickbooks_qbo' (QuickBooks Online bank-statement CSV)
--   - 'xero_csv'       (Xero bank-statement CSV)
--   - 'sage_intacct_csv' (Sage Intacct GL-import CSV)
--
-- This migration is:
--   - **idempotent** — uses ADD COLUMN IF NOT EXISTS, safe to re-run
--   - **tenant-agnostic** — applies to every tenant, not just Animal
--     Doctor SOC, since every VMG-distribution tenant will eventually
--     pick its own format
--   - **non-breaking** — default 'xlsx' preserves existing behavior

ALTER TABLE tenant_features
    ADD COLUMN IF NOT EXISTS cpa_export_format VARCHAR(32) NOT NULL DEFAULT 'xlsx';

-- Self-record so re-applying this migration on a fresh DB is a clean no-op.
INSERT INTO _migrations(filename) VALUES ('117_tenant_features_cpa_export_format.sql')
ON CONFLICT DO NOTHING;
