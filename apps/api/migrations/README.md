# Database Migrations

This directory contains SQL migration scripts for the AgentProvision database.

## How the deploy runner applies migrations

`scripts/deploy_k8s_local.sh` (and the equivalent local-docker path) walks this directory in lexical order, skipping files that:

- match `*.down.sql` (those are manual rollback scripts — see below)
- have their filename already recorded in the `_migrations` table

For everything else, the runner applies the file then inserts the basename into `_migrations` with `ON CONFLICT DO NOTHING`. Each migration should *also* self-record at the bottom of its own SQL (belt-and-suspenders against a partial-failure mid-deploy):

```sql
INSERT INTO _migrations(filename) VALUES ('NNN_descriptive_slug.sql')
ON CONFLICT DO NOTHING;
```

The `_migrations` table is the source of truth. Migration `127_backfill_migrations_applied.sql` records every previously-shipped filename so long-lived environments don't re-execute them.

## Adding a new migration

1. Pick the next free number (`ls *.sql | sort | tail -3`).
2. Create `NNN_descriptive_slug.sql`. Make every statement idempotent: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`. Avoid bare `INSERT INTO` without `ON CONFLICT` unless you know the row can't exist.
3. End the file with the `INSERT INTO _migrations(filename) VALUES (...) ON CONFLICT DO NOTHING;` pattern.
4. `git add apps/api/migrations/NNN_descriptive_slug.sql`.
5. **Verify the file actually got staged** — run `git check-ignore -v apps/api/migrations/NNN_descriptive_slug.sql`. If git prints any matching pattern that ISN'T the `.gitignore` unignore line at the top of the project `.gitignore`, the file is being ignored and needs `git add -f` plus an investigation of why the unignore didn't fire.

### The `*.sql` global-ignore footgun

Many developers have `*.sql` in their `~/.gitignore_global` to keep accidental DB dumps out of unrelated projects. Migration files must NOT be subject to that rule. The project `.gitignore` therefore starts with:

```
!apps/api/migrations/*.sql
!apps/api/migrations/*.down.sql
```

This negation is placed early so no later pattern (project or global) can re-ignore migration files. If you ever see a missing migration in `git status` after creating one, check that this unignore line still exists at the top of `.gitignore`.

## Down migrations (manual rollback)

Files matching `NNN_*.down.sql` are *not* auto-applied by the deploy runner. They exist for documentation and manual recovery — you apply them by hand against the affected environment, then `DELETE FROM _migrations WHERE filename = 'NNN_<up>.sql'` so the up-migration can be re-run later.

Down files are still committed to git for review + auditability, but `127_backfill_migrations_applied.sql` pre-records their filenames in `_migrations` as defense-in-depth so an accidentally-loosened runner can't re-execute them as "pending" migrations.

## Running Migrations

### Manual Execution

```bash
# K8s (Rancher Desktop) — the production-path tool
PG_POD=$(kubectl get pod -n agentprovision -l app.kubernetes.io/name=postgresql -o jsonpath='{.items[0].metadata.name}')
kubectl cp apps/api/migrations/NNN_slug.sql agentprovision/$PG_POD:/tmp/migration.sql
kubectl exec -n agentprovision $PG_POD -- psql -U postgres agentprovision -f /tmp/migration.sql

# Legacy docker-compose path (use only if not on K8s)
docker exec -i agentprovision-db-1 psql -U postgres -d agentprovision < apps/api/migrations/NNN_slug.sql

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
