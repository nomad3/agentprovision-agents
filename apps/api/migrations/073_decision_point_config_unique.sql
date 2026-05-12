-- Add unique constraint on decision_point_config (tenant_id, decision_point)
-- Required by feedback_activities.py upsert pattern
ALTER TABLE decision_point_config
ADD CONSTRAINT uq_decision_point_config_tenant_dp
UNIQUE (tenant_id, decision_point);
