-- Migration 034: Add channel_accounts and channel_events tables
-- Direct WhatsApp integration via neonize (replacing OpenClaw channel proxy)

CREATE TABLE IF NOT EXISTS channel_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    channel_type VARCHAR(50) NOT NULL DEFAULT 'whatsapp',
    account_id VARCHAR(100) NOT NULL DEFAULT 'default',
    enabled BOOLEAN NOT NULL DEFAULT false,
    dm_policy VARCHAR(20) DEFAULT 'allowlist',
    allow_from JSONB DEFAULT '[]'::jsonb,
    config JSONB DEFAULT '{}'::jsonb,
    status VARCHAR(30) NOT NULL DEFAULT 'disconnected',
    connected_at TIMESTAMP,
    disconnected_at TIMESTAMP,
    last_error TEXT,
    reconnect_attempts INTEGER DEFAULT 0,
    phone_number VARCHAR(30),
    display_name VARCHAR(200),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(tenant_id, channel_type, account_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_accounts_tenant ON channel_accounts(tenant_id);

CREATE TABLE IF NOT EXISTS channel_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    channel_account_id UUID NOT NULL REFERENCES channel_accounts(id),
    event_type VARCHAR(50) NOT NULL,
    direction VARCHAR(10),
    remote_id VARCHAR(100),
    message_content TEXT,
    media_url TEXT,
    chat_session_id UUID,
    agent_id UUID,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_channel_events_account ON channel_events(channel_account_id);
CREATE INDEX IF NOT EXISTS idx_channel_events_created ON channel_events(created_at);
