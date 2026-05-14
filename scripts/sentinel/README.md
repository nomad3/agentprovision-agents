# Laptop Sentinel

Always-on health monitor for the `agentprovision-agents` docker-compose stack on this MacBook. Runs as a Claude Code `/loop` session at 5-min cadence. Auto-recovers known-safe failures (disk pressure, missing/unhealthy containers, db down, stale api). Pushes to phone only on critical. Design: `docs/plans/2026-05-14-laptop-sentinel-design.md`.

## Start

In a Claude Code session opened in this repo:

```
/loop 5m run the sentinel runbook at scripts/sentinel/sentinel.md
```

## Stop

End the Claude Code session, or type `stop` to the loop.

## Tail the log

```
tail -f scripts/sentinel/sentinel.log | jq .
```

## Manual tick (test the runbook without arming the loop)

```
claude -p "run scripts/sentinel/sentinel.md"
```

## Files

- `sentinel.md` — the runbook the loop reads each tick (logic lives here)
- `state.json` — workdir cache, api health path cache, failure counters, action cooldowns
- `sentinel.log` — append-only JSONL, one object per tick
