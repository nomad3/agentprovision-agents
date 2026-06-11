-- 174_desktop_command_no_op_status.sql
--
-- Background-control dry-run commands complete without native actuation and
-- persist status/outcome `no_op`. Migration 158 created the command tables
-- before that lifecycle state existed, so Postgres rejected the live dry-run
-- claim path even though the service and tests already use `no_op`.

BEGIN;

ALTER TABLE desktop_commands
    DROP CONSTRAINT IF EXISTS desktop_commands_status_check;

ALTER TABLE desktop_commands
    ADD CONSTRAINT desktop_commands_status_check CHECK (
        status IN (
            'pending',
            'claimed',
            'running',
            'succeeded',
            'failed',
            'denied',
            'no_op',
            'preempted',
            'expired'
        )
    );

ALTER TABLE desktop_command_events
    DROP CONSTRAINT IF EXISTS desktop_command_events_outcome_check;

ALTER TABLE desktop_command_events
    ADD CONSTRAINT desktop_command_events_outcome_check CHECK (
        outcome IN (
            'requested',
            'approved',
            'started',
            'succeeded',
            'failed',
            'denied',
            'no_op',
            'stopped',
            'preempted',
            'expired'
        )
    );

INSERT INTO _migrations(filename) VALUES ('174_desktop_command_no_op_status.sql')
ON CONFLICT DO NOTHING;

COMMIT;
