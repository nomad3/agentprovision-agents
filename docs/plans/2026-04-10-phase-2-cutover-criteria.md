# Phase 2 Cutover Criteria: Python to Rust Memory

## Read Path (Recall)

| Criterion | Threshold | Duration |
|-----------|-----------|----------|
| Top-3 entity IDs exact match | 100% | per query |
| Top-10 entity IDs Jaccard similarity | >= 0.9 | per query |
| Queries meeting both criteria above | >= 99% | 3 consecutive days |
| Rust recall p50 latency | <= Python recall p50 | 3 consecutive days |

## Write Path (Record)

| Criterion | Threshold | Duration |
|-----------|-----------|----------|
| Rust write success rate | >= 99.9% | 3 consecutive days |

## How to Enable

1. Set `MEMORY_DUAL_READ=true` and `MEMORY_DUAL_WRITE=true` to begin shadow validation.
2. Monitor via `GET /api/v1/internal/memory/validation-metrics` (requires `X-Internal-Key` header).
3. Once all criteria are met for 3 consecutive days, set `USE_RUST_MEMORY=true` to cut over.

## Rollback

Set `USE_RUST_MEMORY=false` to immediately revert to the Python path. No data migration needed — Python and Rust share the same PostgreSQL database.

## Monitoring Endpoint

```
GET /api/v1/internal/memory/validation-metrics
X-Internal-Key: <API_INTERNAL_KEY>
```

Returns:
```json
{
  "started_at": "2026-04-10T00:00:00+00:00",
  "reads": {
    "total": 1000,
    "matching": 995,
    "divergent": 5,
    "match_rate": 0.995
  },
  "writes": {
    "total": 500,
    "successful": 500,
    "failed": 0,
    "success_rate": 1.0
  }
}
```
