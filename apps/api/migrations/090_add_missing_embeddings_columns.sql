-- Migration 090: Add missing embedding columns to core models
-- Supports: KnowledgeEntity, CommitmentRecord, GoalRecord

-- Enable pgvector if not enabled
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding column to knowledge_entities
ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS embedding vector(768);
CREATE INDEX IF NOT EXISTS idx_knowledge_entities_embedding ON knowledge_entities USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Add embedding column to commitment_records
ALTER TABLE commitment_records ADD COLUMN IF NOT EXISTS embedding vector(768);
CREATE INDEX IF NOT EXISTS idx_commitment_records_embedding ON commitment_records USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Add embedding column to goal_records
ALTER TABLE goal_records ADD COLUMN IF NOT EXISTS embedding vector(768);
CREATE INDEX IF NOT EXISTS idx_goal_records_embedding ON goal_records USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
