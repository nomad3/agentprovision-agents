#!/usr/bin/env python3
"""End-to-end Luna chat latency benchmark.

Phase B of docs/plans/2026-04-23-luna-latency-reduction-plan.md, with one
caveat: Phase A's per-stage instrumentation (recall_ms / cli_spawn_ms /
cli_first_byte_ms / cli_total_ms / post_dispatch_ms) hasn't landed yet,
so this v0 measures *what users feel* — wall time of the
``POST /chat/sessions/{id}/messages/enhanced`` round trip — and pulls
whatever fields the existing ``ChatMessage`` carries (tokens, platform,
duration_ms) out of the response.

Run from a clean shell:

    cd apps/api
    python ../../scripts/benchmark_luna.py \\
        --base-url http://localhost:8000 \\
        --email test@example.com --password password \\
        --runs 2 --warmup 1

Outputs JSON + markdown to ``benchmarks/<date>-luna-bench.{json,md}``.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid as _uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

import requests

# Critical-path prompt matrix. Tools_expected is a hint to the report
# author, not a contract — the agent decides at runtime which tools to
# call. ``write`` prompts are intentionally skipped; we don't want to
# create real calendar entries / messages during a bench run.
PROMPTS = [
    ("greeting",      "hola luna",                                      "none"),
    ("light_recall",  "qué te dije la última vez?",                     "memory"),
    ("entity_recall", "qué sabes de mi negocio?",                       "knowledge_graph"),
    ("tool_read",     "lista mis workflows recientes",                  "workflows (read)"),
    ("multi_step",    "dame un resumen rápido de qué pasó hoy",         "memory + light synthesis"),
]


@dataclass
class TurnResult:
    cell: str
    prompt: str
    run_idx: int
    cold: bool
    wall_ms: int
    server_duration_ms: Optional[int]
    tokens: Optional[int]
    platform: Optional[str]
    response_len: int
    success: bool
    error: Optional[str] = None
    response_preview: str = ""
    # Phase A.1 stage breakdown (populated when the api response carries
    # timings via assistant_message.context.timings). Empty until A.1 lands.
    timings: dict = field(default_factory=dict)


@dataclass
class BenchmarkRun:
    started_at: str = ""
    finished_at: str = ""
    base_url: str = ""
    tenant_id: str = ""
    runs_per_cell: int = 0
    warmup: int = 0
    rows: list[TurnResult] = field(default_factory=list)


def _login(base: str, email: str, password: str) -> tuple[str, str]:
    r = requests.post(
        f"{base}/api/v1/auth/login",
        data={"username": email, "password": password},
        timeout=15,
    )
    r.raise_for_status()
    j = r.json()
    token = j["access_token"]

    me = requests.get(
        f"{base}/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    me.raise_for_status()
    tenant_id = me.json()["tenant_id"]
    return token, tenant_id


def _new_session(base: str, token: str) -> str:
    """Create a fresh chat session bound to the tenant's primary agent."""
    # Fetch agents and pick one — prefer Luna by name, else first agent.
    r = requests.get(
        f"{base}/api/v1/agents",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    r.raise_for_status()
    agents = r.json() or []
    chosen = None
    for a in agents:
        if (a.get("name") or "").lower().startswith("luna"):
            chosen = a
            break
    if chosen is None and agents:
        chosen = agents[0]
    payload = {"title": f"bench {_uuid.uuid4().hex[:6]}"}
    if chosen:
        payload["agent_id"] = chosen["id"]
    s = requests.post(
        f"{base}/api/v1/chat/sessions",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=15,
    )
    s.raise_for_status()
    return s.json()["id"]


def _send_message(base: str, token: str, session_id: str, content: str, timeout: int = 180) -> tuple[int, dict]:
    """Send a message and return (wall_ms, full_response_dict)."""
    started = time.monotonic()
    r = requests.post(
        f"{base}/api/v1/chat/sessions/{session_id}/messages/enhanced",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"content": content},
        timeout=timeout,
    )
    wall_ms = int((time.monotonic() - started) * 1000)
    r.raise_for_status()
    return wall_ms, r.json()


def _run_cell(
    *,
    base: str,
    token: str,
    cell: str,
    prompt: str,
    runs_per_cell: int,
    warmup: int,
) -> list[TurnResult]:
    """Run all repetitions of one (prompt-class) cell with a fresh session.

    Every step is wrapped — a single transient connection drop (api
    recreate, network blip) records a fail row and lets the rest of
    the matrix continue. The final report is always written.
    """
    out: list[TurnResult] = []
    for idx in range(runs_per_cell + warmup):
        is_warmup = idx < warmup
        is_cold = idx == warmup  # first non-warmup run is "cold" in this batch
        row: TurnResult
        try:
            session_id = _new_session(base, token)
            wall_ms, payload = _send_message(base, token, session_id, prompt)
            assistant = payload.get("assistant_message") or {}
            ctx = assistant.get("context") or {}
            row = TurnResult(
                cell=cell,
                prompt=prompt,
                run_idx=idx,
                cold=is_cold,
                wall_ms=wall_ms,
                server_duration_ms=assistant.get("duration_ms"),
                tokens=assistant.get("tokens_used"),
                platform=ctx.get("platform") or assistant.get("platform"),
                response_len=len(assistant.get("content") or ""),
                success=True,
                response_preview=(assistant.get("content") or "")[:200],
                timings=ctx.get("timings") or {},
            )
        except requests.HTTPError as e:
            row = TurnResult(
                cell=cell, prompt=prompt, run_idx=idx, cold=is_cold,
                wall_ms=0,
                server_duration_ms=None, tokens=None, platform=None, response_len=0,
                success=False, error=f"HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except Exception as e:
            row = TurnResult(
                cell=cell, prompt=prompt, run_idx=idx, cold=is_cold,
                wall_ms=0, server_duration_ms=None, tokens=None, platform=None,
                response_len=0, success=False, error=f"{type(e).__name__}: {e}",
            )
        marker = " (warmup)" if is_warmup else ""
        print(
            f"  [{cell}] run={idx}{marker} wall_ms={row.wall_ms} "
            f"server_ms={row.server_duration_ms} platform={row.platform} "
            f"resp_len={row.response_len} ok={row.success}",
            flush=True,
        )
        if not is_warmup:
            out.append(row)
    return out


def timed_p(values: list[int], pct: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[idx]


def _summarize(rows: list[TurnResult]) -> dict:
    by_cell: dict[str, dict] = {}
    for r in rows:
        b = by_cell.setdefault(r.cell, {"walls": [], "servers": [], "ok": 0, "fail": 0})
        if r.success:
            b["walls"].append(r.wall_ms)
            if r.server_duration_ms is not None:
                b["servers"].append(int(r.server_duration_ms))
            b["ok"] += 1
        else:
            b["fail"] += 1
    summary = {}
    for cell, b in by_cell.items():
        walls = b["walls"]
        # Aggregate per-stage timings across the OK rows in this cell.
        stage_avg: dict = {}
        successful = [r for r in rows if r.cell == cell and r.success and r.timings]
        if successful:
            keys = set()
            for r in successful:
                keys.update(r.timings.keys())
            for k in keys:
                vals = [r.timings.get(k, 0) for r in successful]
                stage_avg[k] = int(statistics.mean(vals))
        summary[cell] = {
            "n_ok": b["ok"],
            "n_fail": b["fail"],
            "wall_p50_ms": timed_p(walls, 50),
            "wall_p95_ms": timed_p(walls, 95),
            "wall_min_ms": min(walls) if walls else 0,
            "wall_max_ms": max(walls) if walls else 0,
            "wall_avg_ms": int(statistics.mean(walls)) if walls else 0,
            "server_p50_ms": timed_p(b["servers"], 50),
            "platforms": sorted(set(filter(None, [r.platform for r in rows if r.cell == cell]))),
            "stage_avg_ms": stage_avg,
        }
    return summary


def _write_markdown(path: str, run: BenchmarkRun, summary: dict) -> None:
    lines = [
        f"# Luna latency benchmark — {run.started_at[:10]}",
        "",
        f"- base_url: `{run.base_url}`",
        f"- tenant: `{run.tenant_id}`",
        f"- runs/cell: {run.runs_per_cell} (after {run.warmup} warmup)",
        f"- started: {run.started_at}",
        f"- finished: {run.finished_at}",
        "",
        "**v0 caveat:** Phase A per-stage instrumentation (recall_ms / cli_spawn_ms / "
        "cli_first_byte_ms / post_dispatch_ms) is not in yet. Numbers below are "
        "**end-to-end wall time** of `POST /messages/enhanced` — what the user feels.",
        "",
        "## Summary by prompt class",
        "",
        "| cell | n | n_fail | wall p50 | wall p95 | wall avg | server p50 | platforms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for cell, s in summary.items():
        lines.append(
            f"| {cell} | {s['n_ok']} | {s['n_fail']} | "
            f"{s['wall_p50_ms']} ms | {s['wall_p95_ms']} ms | "
            f"{s['wall_avg_ms']} ms | "
            f"{s['server_p50_ms']} ms | {', '.join(s['platforms']) or '—'} |"
        )

    # Per-stage breakdown (Phase A.1 — populated when api response carries timings).
    has_stage_data = any(s.get("stage_avg_ms") for s in summary.values())
    if has_stage_data:
        all_stages = sorted({k for s in summary.values() for k in (s.get("stage_avg_ms") or {})})
        lines += ["", "## Stage breakdown (avg ms)", "", "| cell | " + " | ".join(all_stages) + " |"]
        lines.append("|---" * (1 + len(all_stages)) + "|")
        for cell, s in summary.items():
            stages = s.get("stage_avg_ms") or {}
            row = [cell] + [str(stages.get(k, "—")) for k in all_stages]
            lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## All rows", "", "| cell | run | cold | wall | server | tokens | platform | ok | error / preview |", "|---|---|---|---|---|---|---|---|---|"]
    for r in run.rows:
        snippet = (r.error or r.response_preview).replace("|", "\\|").replace("\n", " ")[:120]
        lines.append(
            f"| {r.cell} | {r.run_idx} | {'Y' if r.cold else 'N'} | "
            f"{r.wall_ms} ms | {r.server_duration_ms or '—'} ms | "
            f"{r.tokens or '—'} | {r.platform or '—'} | "
            f"{'✅' if r.success else '❌'} | {snippet} |"
        )

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def main() -> int:
    alpha = argparse.ArgumentParser()
    alpha.add_argument("--base-url", default=os.environ.get("BENCH_BASE_URL", "http://localhost:8000"))
    alpha.add_argument("--email", default=os.environ.get("BENCH_EMAIL", "test@example.com"))
    alpha.add_argument("--password", default=os.environ.get("BENCH_PASSWORD", "password"))
    alpha.add_argument("--token", default=os.environ.get("BENCH_TOKEN"),
                    help="Pre-minted JWT — skips login. Use to bench any tenant without sharing the password.")
    alpha.add_argument("--runs", type=int, default=2, help="non-warmup runs per cell")
    alpha.add_argument("--warmup", type=int, default=1)
    alpha.add_argument("--out-prefix", default="benchmarks")
    args = alpha.parse_args()

    base = args.base_url.rstrip("/")
    if args.token:
        token = args.token
        me = requests.get(
            f"{base}/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        me.raise_for_status()
        tenant_id = me.json()["tenant_id"]
        print(f"using --token → tenant_id={tenant_id}\n", flush=True)
    else:
        print(f"login → {base} as {args.email}", flush=True)
        token, tenant_id = _login(base, args.email, args.password)
        print(f"  tenant_id={tenant_id}\n", flush=True)

    started = datetime.now(tz=timezone.utc).isoformat()
    run = BenchmarkRun(
        started_at=started,
        base_url=base,
        tenant_id=tenant_id,
        runs_per_cell=args.runs,
        warmup=args.warmup,
    )

    aborted_reason: Optional[str] = None
    try:
        for cell, prompt, _hint in PROMPTS:
            print(f"=== cell: {cell} :: {prompt!r} ===", flush=True)
            rows = _run_cell(
                base=base, token=token,
                cell=cell, prompt=prompt,
                runs_per_cell=args.runs, warmup=args.warmup,
            )
            run.rows.extend(rows)
            print()
    except KeyboardInterrupt:
        aborted_reason = "KeyboardInterrupt"
    except Exception as e:
        aborted_reason = f"{type(e).__name__}: {e}"
        print(f"\n!!! bench aborted mid-run: {aborted_reason}\n  (writing partial report)", flush=True)

    run.finished_at = datetime.now(tz=timezone.utc).isoformat()
    summary = _summarize(run.rows)

    os.makedirs(args.out_prefix, exist_ok=True)
    stamp = run.started_at[:10]
    json_path = f"{args.out_prefix}/{stamp}-luna-bench.json"
    md_path = f"{args.out_prefix}/{stamp}-luna-bench.md"

    payload = asdict(run)
    payload["summary"] = summary
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    _write_markdown(md_path, run, summary)

    print(f"\nwrote {json_path}")
    print(f"wrote {md_path}\n")
    print("=== summary ===")
    for cell, s in summary.items():
        print(
            f"  {cell:14s}  p50={s['wall_p50_ms']:>5d} ms  "
            f"p95={s['wall_p95_ms']:>5d} ms  "
            f"n={s['n_ok']}  fail={s['n_fail']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
