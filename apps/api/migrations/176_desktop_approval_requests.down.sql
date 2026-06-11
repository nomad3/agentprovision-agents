-- 176_desktop_approval_requests.down.sql

BEGIN;

DROP TABLE IF EXISTS desktop_approval_requests;

DELETE FROM _migrations WHERE filename = '176_desktop_approval_requests.sql';

COMMIT;
