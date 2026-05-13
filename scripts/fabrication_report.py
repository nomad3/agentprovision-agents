#!/usr/bin/env python3
"""Per-tenant fabrication-candidate report from the audit pipeline.

Reads `vw_fabrication_candidates` (migration 109) and produces a
tenant-grouped summary plus a sample of the highest-risk turns.

A "fabrication candidate" is an assistant turn that:
  - is substantive (>= 200 chars), AND
  - shows zero successful tool_calls server-side (PR #178/#180 audit), AND
  - shows zero stderr-side tool errors (PR #175 capture).

i.e. Luna emitted specific data without grounding it in any tool result.
This is a heuristic, not a verdict — turns that grounded fully in
recalled entities or chat history will also show zero tool calls. Use
this report to prioritize manual review of the highest-volume cases,
not to auto-flag.

Usage:
  ./scripts/fabrication_report.py                   # last 24h
  ./scripts/fabrication_report.py --hours 168       # last 7 days
  ./scripts/fabrication_report.py --tenant aremko   # single tenant
  ./scripts/fabrication_report.py --samples 10      # show 10 worst turns
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


SQL_TEMPLATE_SUMMARY = """
WITH recent AS (
    SELECT *
    FROM vw_fabrication_candidates
    WHERE created_at > NOW() - INTERVAL '{hours} hours'
      {tenant_filter}
)
SELECT
    t.name AS tenant,
    COUNT(*) AS substantive_turns,
    COUNT(*) FILTER (WHERE audit_tool_calls > 0) AS grounded,
    COUNT(*) FILTER (WHERE audit_tool_calls = 0 AND stderr_tool_errors = 0) AS ungrounded_candidates,
    ROUND(100.0 * COUNT(*) FILTER (WHERE audit_tool_calls > 0) / NULLIF(COUNT(*), 0), 1) AS pct_grounded,
    MIN(created_at) AS oldest_turn,
    MAX(created_at) AS newest_turn
FROM recent r
JOIN tenants t ON t.id = r.tenant_id
GROUP BY t.name
ORDER BY substantive_turns DESC;
"""

SQL_TEMPLATE_SAMPLES = """
SELECT
    t.name AS tenant,
    r.created_at,
    r.resp_chars,
    r.platform,
    r.agent_slug,
    LEFT(r.response_preview, 160) AS preview
FROM vw_fabrication_candidates r
JOIN tenants t ON t.id = r.tenant_id
WHERE r.audit_tool_calls = 0
  AND r.stderr_tool_errors = 0
  AND r.created_at > NOW() - INTERVAL '{hours} hours'
  {tenant_filter}
ORDER BY r.resp_chars DESC
LIMIT {samples};
"""


def run_sql(sql: str) -> str:
    """Run a query inside the running db container and return stdout."""
    container = os.environ.get("FAB_DB_CONTAINER", "agentprovision-agents-db-1")
    db = os.environ.get("FAB_DB_NAME", "agentprovision")
    user = os.environ.get("FAB_DB_USER", "postgres")
    res = subprocess.run(
        ["docker", "exec", "-i", container, "psql", "-U", user, db, "-c", sql],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        sys.stderr.write(res.stderr)
        sys.exit(res.returncode)
    return res.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hours", type=int, default=24, help="lookback window in hours (default: 24)")
    parser.add_argument("--tenant", help="filter to one tenant by name (e.g. aremko)")
    parser.add_argument("--samples", type=int, default=5, help="how many worst turns to print (default: 5)")
    args = parser.parse_args()

    if args.tenant:
        tenant_filter = f"AND tenant_id = (SELECT id FROM tenants WHERE name = '{args.tenant.replace(chr(39), chr(39)+chr(39))}')"
    else:
        tenant_filter = ""

    print(f"\n=== Fabrication candidate summary — last {args.hours}h ===")
    print(run_sql(SQL_TEMPLATE_SUMMARY.format(hours=args.hours, tenant_filter=tenant_filter)))

    print(f"\n=== Top {args.samples} ungrounded turns by response size ===")
    print(run_sql(SQL_TEMPLATE_SAMPLES.format(
        hours=args.hours, tenant_filter=tenant_filter, samples=args.samples
    )))

    return 0


if __name__ == "__main__":
    sys.exit(main())
