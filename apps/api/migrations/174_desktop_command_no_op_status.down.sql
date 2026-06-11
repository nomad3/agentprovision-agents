-- 174_desktop_command_no_op_status.down.sql

BEGIN;

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
            'stopped',
            'preempted',
            'expired'
        )
    );

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
            'preempted',
            'expired'
        )
    );

DELETE FROM _migrations WHERE filename = '174_desktop_command_no_op_status.sql';

COMMIT;
