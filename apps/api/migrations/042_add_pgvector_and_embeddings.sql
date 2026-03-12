-- 042_add_pgvector_and_embeddings.sql
-- Add pgvector extension and embeddings table for semantic search
-- Supports: skills, knowledge entities, memory activities, chat messages, relations, agent tasks

-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Embeddings table for semantic search across content types
CREATE TABLE IF NOT EXISTS embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES tenants(id) ON DELETE CASCADE,  -- NULL for native/built-in skills
    content_type VARCHAR(50) NOT NULL,  -- 'skill', 'entity', 'memory_activity', 'chat_message', 'relation', 'agent_task'
    content_id VARCHAR(255) NOT NULL,
    embedding vector(768) NOT NULL,
    text_content TEXT,  -- original text that was embedded
    task_type VARCHAR(50) DEFAULT 'RETRIEVAL_DOCUMENT',
    model VARCHAR(100) DEFAULT 'gemini-embedding-2-preview',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Index for tenant-scoped queries filtered by content type
CREATE INDEX idx_embeddings_tenant_type ON embeddings (tenant_id, content_type);

-- Index for looking up embeddings by content reference
CREATE INDEX idx_embeddings_content ON embeddings (content_type, content_id);

-- IVFFlat index for approximate nearest neighbor cosine similarity search
CREATE INDEX idx_embeddings_vector ON embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
