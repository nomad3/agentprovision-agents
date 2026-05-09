-- Migration 120: re-do the Bookkeeper Categorization workflow rewire
-- correctly. The previous attempt (migration 118 in PR #331) used a
-- name+text-replace pattern:
--
--   UPDATE dynamic_workflows
--   SET definition = REPLACE(definition::text,
--                            '"tool": "generate_excel_report"',
--                            '"tool": "bookkeeper_export_aaha"')::jsonb
--   WHERE name = 'Bookkeeper Categorization'
--     AND definition::text LIKE '%"tool": "generate_excel_report"%';
--
-- Two problems flagged by the post-merge code review:
--   (a) No tenant_id filter — would silently rewrite OTHER tenants'
--       workflows that happen to share the name.
--   (b) String-replace on JSONB-cast-to-text is fragile against
--       formatting drift (the Visual Builder re-formats JSON on save).
--       On the live Animal Doctor SOC tenant the workflow JSON had
--       drifted, so 118 silently no-op'd and the workflow still calls
--       `generate_excel_report` instead of the new
--       `bookkeeper_export_aaha`.
--
-- This migration walks the steps array per-step and uses jsonb_set,
-- scoped to the explicit (tenant_id, workflow_id) pair. Idempotent
-- by virtue of the rewire being a no-op once the tool is already
-- correct.

DO $migration$
DECLARE
    target_tenant_id  UUID := '7f632730-1a38-41f1-9f99-508d696dbcf1';  -- Animal Doctor SOC
    target_workflow_id UUID := '5f8302d5-054b-4a14-87ab-0c4bf9a5daea';  -- Bookkeeper Categorization
    new_def          JSONB;
    step_idx         INT;
    steps            JSONB;
BEGIN
    -- Read the current definition; cast to JSONB so we can mutate per-step.
    SELECT definition::jsonb INTO new_def
    FROM dynamic_workflows
    WHERE id = target_workflow_id
      AND tenant_id = target_tenant_id;

    IF new_def IS NULL THEN
        RAISE NOTICE 'Migration 120: workflow %/% not found, skipping (probably a fresh DB)',
                     target_tenant_id, target_workflow_id;
        RETURN;
    END IF;

    steps := new_def -> 'steps';
    IF steps IS NULL OR jsonb_typeof(steps) <> 'array' THEN
        RAISE NOTICE 'Migration 120: workflow has no steps array, skipping';
        RETURN;
    END IF;

    -- Walk the array; for any step whose tool is `generate_excel_report`,
    -- rewrite it to `bookkeeper_export_aaha`. Other tools untouched.
    FOR step_idx IN 0 .. jsonb_array_length(steps) - 1 LOOP
        IF (steps -> step_idx ->> 'tool') = 'generate_excel_report' THEN
            new_def := jsonb_set(
                new_def,
                ARRAY['steps', step_idx::text, 'tool'],
                '"bookkeeper_export_aaha"'::jsonb,
                false
            );
            RAISE NOTICE 'Migration 120: rewired step % to bookkeeper_export_aaha', step_idx;
        END IF;
    END LOOP;

    UPDATE dynamic_workflows
    SET definition = new_def::json
    WHERE id = target_workflow_id
      AND tenant_id = target_tenant_id;
END
$migration$;

-- Self-record per the convention in 110/111/112/113/114/116/117.
INSERT INTO _migrations(filename) VALUES ('120_bookkeeper_workflow_rewire_proper.sql')
ON CONFLICT DO NOTHING;
