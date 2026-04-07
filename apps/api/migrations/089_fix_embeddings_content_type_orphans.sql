-- 089_fix_embeddings_content_type_orphans.sql
-- Fix orphaned embeddings rows from the historic backfill script.
--
-- BUG: scripts/backfill_knowledge_from_sessions.py wrote rows with
-- content_type='knowledge_entity' and content_type='knowledge_observation',
-- but the active code (and all readers) use 'entity' and 'observation'.
-- Result: 344 entity embeddings + 4,817 observation embeddings have been
-- silently invisible to semantic search since the backfill ran. Semantic
-- entity search has been returning zero hits and falling through to ILIKE
-- keyword search for the entire history of those rows.
--
-- This is a pure data migration — no active code paths produce the bad
-- values anymore (verified by grep across apps/api and scripts/). The
-- historic backfill script is also being patched in this PR so it can't
-- recur if rerun.
--
-- Discovered while implementing memory.recall() in PR #130 (Plan Task 10).

UPDATE embeddings
   SET content_type = 'entity',
       updated_at = NOW()
 WHERE content_type = 'knowledge_entity';

UPDATE embeddings
   SET content_type = 'observation',
       updated_at = NOW()
 WHERE content_type = 'knowledge_observation';
