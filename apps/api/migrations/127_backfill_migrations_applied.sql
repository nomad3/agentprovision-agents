-- 127_backfill_migrations_applied.sql
--
-- One-time backfill: mark every shipped migration as applied so
-- repeated deploys never re-execute them. The deploy runner in
-- scripts/deploy_k8s_local.sh skips any filename present in
-- _migrations, so this catch-up keeps already-applied migrations
-- (recorded or otherwise) from running twice on a long-lived DB.
--
-- Safe to re-run: ON CONFLICT DO NOTHING. Listed migrations are
-- frozen to those shipped at the time this file was created — any
-- migrations added after 127 simply record themselves via their
-- own INSERT (the established pattern).

CREATE TABLE IF NOT EXISTS _migrations (
    filename TEXT PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT now()
);

INSERT INTO _migrations (filename) VALUES
    ('002_update_connectors_table.sql'),
    ('003_add_connectors_timestamps.sql'),
    ('026_add_execution_traces.sql'),
    ('027_add_tenant_instances.sql'),
    ('028_add_skill_configs_and_credentials.sql'),
    ('029_extend_knowledge_entities.sql'),
    ('030_add_knowledge_entity_description_aliases.sql'),
    ('031_add_entity_category.sql'),
    ('032_add_lead_scoring.sql'),
    ('033_add_scoring_rubric.sql'),
    ('034_add_channel_accounts_and_events.sql'),
    ('035_add_session_blob_to_channel_accounts.sql'),
    ('036_add_skill_config_account_email.sql'),
    ('037_add_memory_activities.sql'),
    ('038_add_notifications.sql'),
    ('039_extend_metadata_richness.sql'),
    ('040_skills_and_integration_rename.sql'),
    ('041_rename_skill_name_to_integration_name.sql'),
    ('042_add_pgvector_and_embeddings.sql'),
    ('043_add_skill_registry.sql'),
    ('045_add_rl_framework.sql'),
    ('046_add_active_llm_provider.sql'),
    ('046_rl_memory_distributed.sql'),
    ('047_add_cli_orchestrator_fields.sql'),
    ('047_add_webhook_connectors.sql'),
    ('048_add_mcp_server_connectors.sql'),
    ('049_git_history_tracking.sql'),
    ('050_dynamic_workflows.sql'),
    ('051_knowledge_search_indexes.sql'),
    ('052_add_safety_governance_phase1.sql'),
    ('053_add_safety_evidence_packs.sql'),
    ('054_add_safety_evidence_pack_retention.sql'),
    ('055_add_agent_trust_profiles.sql'),
    ('056_add_goal_and_commitment_records.sql'),
    ('057_add_agent_identity_profiles.sql'),
    ('058_add_world_state_assertions.sql'),
    ('059_add_world_state_disputes_and_decay.sql'),
    ('060_add_causal_edges.sql'),
    ('061_add_plan_runtime.sql'),
    ('062_add_blackboard.sql'),
    ('063_add_collaboration_sessions.sql'),
    ('064_add_coalition_routing.sql'),
    ('065_add_learning_experiments.sql'),
    ('066_add_rollout_exclusivity.sql'),
    ('067_add_simulation_engine.sql'),
    ('068_add_proactive_actions.sql'),
    ('069_add_feedback_and_config.sql'),
    ('070_add_cost_budgets.sql'),
    ('071_add_auto_dream.sql'),
    ('072_cost_tracking_unique.sql'),
    ('073_decision_point_config_unique.sql'),
    ('074_add_observation_source_channel.sql'),
    ('075_add_conversation_episodes.sql'),
    ('076_add_user_preferences.sql'),
    ('077_add_observation_sentiment.sql'),
    ('078_extend_execution_traces.sql'),
    ('079_add_user_activities.sql'),
    ('080_add_device_registry.sql'),
    ('081_default_cli_platform_claude_code.sql'),
    ('082_add_agent_tier_and_toolgroups.sql'),
    ('083_add_session_journals.sql'),
    ('084_add_behavioral_signals.sql'),
    ('085_widen_is_significant_column.sql'),
    ('086_extend_conversation_episodes.sql'),
    ('087_add_visibility_scoping.sql'),
    ('088_memory_activities_workflow_id.sql'),
    ('089_fix_embeddings_content_type_orphans.sql'),
    ('090_add_missing_embeddings_columns.sql'),
    ('091_blackboard_chat_session_and_source_node.sql'),
    ('092_add_password_reset_to_users.sql'),
    ('093_agent_integration_configs.sql'),
    ('094_external_agents.sql'),
    ('095_agent_ownership_and_status.sql'),
    ('096_agent_permissions.sql'),
    ('097_agent_policies.sql'),
    ('098_agent_audit_log.sql'),
    ('099_agent_performance_rollup.sql'),
    ('100_agent_versions.sql'),
    ('101_chat_sessions_agent_id.sql'),
    ('102_agent_name_unique_per_tenant.sql'),
    ('103_workflow_counter_defaults.sql'),
    ('104_agent_marketplace_listings.sql'),
    ('105_agent_test_suites.sql'),
    ('106_aremko_receptionist_skill.sql'),
    ('107_aremko_catalog_seed.sql'),
    ('108_tool_calls_audit.sql'),
    ('109_fabrication_candidate_view.sql'),
    ('110_library_revisions.sql'),
    ('111_external_agent_performance.sql'),
    ('112_external_agent_call_log_constraints.sql'),
    ('113_tenant_github_primary_account.sql'),
    ('114_user_preferences_value_json.sql'),
    ('115_brightlocal_seo_sentinel_wiring.sql'),
    ('116_harriet_to_herriot_rename.sql'),
    ('117_tenant_features_cpa_export_format.sql'),
    ('118_bookkeeper_workflow_use_export_tool.sql'),
    ('119_pulse_revenue_sync_wiring.sql'),
    ('120_bookkeeper_workflow_rewire_proper.sql'),
    ('121_tenant_features_resilient_executor.sql'),
    ('122_agent_tasks_last_seen_at.sql'),
    ('123_luna_meta_tool_group.sql'),
    ('124_agents_strip_null_tool_group_entries.sql'),
    ('125_luna_prospecting_tool_groups.sql'),
    -- PR-Q0 migration on the feat/quickstart-q0-onboarding-state branch.
    -- Pre-recorded here so that when Q0 merges and the deploy runner
    -- picks up its file on disk, it doesn't try to re-apply 126 on long-
    -- lived envs (where 127's backfill will already have stamped it).
    -- Idempotent for Q0 itself: 126 is ADD COLUMN IF NOT EXISTS, but
    -- belt-and-suspenders means it never has the chance to re-run.
    ('126_tenants_onboarding_state.sql'),
    -- Down-migrations live in the repo for review + manual recovery but
    -- must NEVER be auto-applied. Pre-record them here so that even if a
    -- future deploy runner change forgets to skip *.down.sql, the
    -- _migrations row already exists and the runner's skip-if-recorded
    -- check kicks in. Defense-in-depth alongside the explicit
    -- `case *.down.sql) continue` guard added in scripts/deploy_k8s_local.sh.
    ('106_aremko_receptionist_skill.down.sql'),
    ('107_aremko_catalog_seed.down.sql'),
    ('113_tenant_github_primary_account.down.sql'),
    ('114_user_preferences_value_json.down.sql'),
    ('117_tenant_features_cpa_export_format.down.sql'),
    ('121_tenant_features_resilient_executor.down.sql'),
    ('127_backfill_migrations_applied.sql')
ON CONFLICT DO NOTHING;
