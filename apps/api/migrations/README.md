# Database Migrations

This directory contains SQL migration scripts for the AgentProvision database.

## Running Migrations

### Manual Execution

```bash
# Connect to database
docker exec -i agentprovision-db-1 psql -U postgres -d agentprovision < migrations/001_add_postgres_metadata.sql

# Verify
docker exec agentprovision-db-1 psql -U postgres -d agentprovision -c "\d datasets"
```

### Via Python Script

```bash
cd apps/api
python -c "
import asyncio
import asyncpg
import os

async def run_migration():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL').replace('+asyncpg', ''))

    with open('../../migrations/001_add_postgres_metadata.sql', 'r') as f:
        sql = f.read()

    await conn.execute(sql)
    print('Migration completed successfully')
    await conn.close()

asyncio.run(run_migration())
"
```

## Migration Files

- `001_add_postgres_metadata.sql` - Adds metadata_ JSONB column to all PostgreSQL-integrated tables
- `002_update_connectors_table.sql` - Updates connectors table schema
- `003_add_connectors_timestamps.sql` - Adds timestamps to connectors
- `026_add_execution_traces.sql` - Adds execution_traces table for task audit trails
- `027_add_tenant_instances.sql` - Adds tenant_instances table for managed OpenClaw pods
- `028_add_skill_configs_and_credentials.sql` - Adds skill_configs and skill_credentials tables
- `029_extend_knowledge_entities.sql` - Adds status lifecycle, collection_task_id, source_url, enrichment_data to knowledge_entities
- `030_add_knowledge_entity_description_aliases.sql` - Adds description, properties, aliases columns to knowledge_entities; creates knowledge_observations and knowledge_entity_history tables
- `035_add_session_blob_to_channel_accounts.sql` - Adds session_blob column to channel_accounts
- `036_add_skill_config_account_email.sql` - Adds account_email to skill_config for multi-account OAuth
- `037_add_memory_activities.sql` - Adds memory_activities table for knowledge graph audit log
- `038_add_notifications.sql` - Adds notifications table for proactive alerts

## Rollback

If you need to rollback the metadata columns:

```sql
-- Remove columns
ALTER TABLE datasets DROP COLUMN IF EXISTS metadata_;
ALTER TABLE notebooks DROP COLUMN IF EXISTS metadata_;
ALTER TABLE data_pipelines DROP COLUMN IF EXISTS metadata_;
ALTER TABLE agents DROP COLUMN IF EXISTS metadata_;
ALTER TABLE vector_stores DROP COLUMN IF EXISTS metadata_;
ALTER TABLE deployments DROP COLUMN IF EXISTS metadata_;

-- Drop indexes
DROP INDEX IF EXISTS idx_datasets_metadata;
DROP INDEX IF EXISTS idx_notebooks_metadata;
DROP INDEX IF EXISTS idx_data_pipelines_metadata;
DROP INDEX IF EXISTS idx_agents_metadata;
DROP INDEX IF EXISTS idx_vector_stores_metadata;
DROP INDEX IF EXISTS idx_deployments_metadata;
```
