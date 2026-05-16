# Workspace Persistence

**Status:** Shipped (existing) + extended with `alpha workspace clone` (parallel PR, 2026-05-16).
**Backend:** `apps/api/app/api/v1/workspace.py`
**Volume:** `agentprovision-agents_workspaces` (docker-compose) / `workspaces-pvc` (Helm)
**Authoritative kernel principle:** [`alpha_cli_kernel.md`](alpha_cli_kernel.md)

Per-tenant durable filesystem mounted into the `api` and `code-worker` services. This is what makes Alpha's memory, plans, and project trees survive container restarts, image rebuilds, and deploys — and what lets the `/dashboard` Files tab and `alpha workspace …` verbs share the same view of disk.

---

## 1. Volume + mount

| Layer | Name | Mount path | Size |
|---|---|---|---|
| docker-compose | named volume `agentprovision-agents_workspaces` | `/var/agentprovision/workspaces` | host-driven, unbounded |
| Helm | PVC `<release>-workspaces` (`helm/charts/microservice/templates/workspaces-pvc.yaml`) | `/var/agentprovision/workspaces` | `workspaces.size` default **10 GiB** |

Mounted on **both** `api` and `code-worker`. The api serves the workspace HTTP endpoints; the code-worker is where `git clone`, file edits, and CLI-runtime working directories live. After PR #517 lands the `code-worker` mount, both services see exactly the same bytes — a file Luna writes via a CLI tool is immediately readable via the dashboard tree and vice versa.

The Helm PVC is **opt-in**: the chart only renders the PVC when `workspaces.enabled=true`. Production values live in `helm/values/agentprovision-api.yaml`. Override env: `WORKSPACES_ROOT` (defaults to `/var/agentprovision/workspaces`).

### Persistence guarantees

- Survives `docker compose restart`, `docker compose down && up`, image rebuilds, and routine `helm upgrade`.
- Survives node reboots (PVC backed by the default storage class).
- **Only `docker volume rm agentprovision-agents_workspaces`** (or `kubectl delete pvc`) wipes it.
- **Never `docker volume prune`** — the daily `docker-cleanup.yaml` cron is image- and builder-only for exactly this reason (see memory `runner_keychain_credstore.md` + the CLAUDE.md "Build Discipline" section).

---

## 2. Per-tenant layout

```
/var/agentprovision/workspaces/
└── <tenant_id>/                      ← one subtree per tenant (UUID)
    ├── README.md                     ← auto-seeded on first _resolve_root()
    ├── docs/
    │   └── plans/                    ← design docs, plans
    ├── memory/                       ← persistent memory files (e.g. <topic>.md)
    └── projects/                     ← per-project working notes
        └── <repo>/                   ← populated by `alpha workspace clone`
```

The subtree is **auto-created on first access** by `_seed_tenant_workspace()` in `workspace.py`. A freshly-onboarded tenant never 404s — their first `GET /api/v1/workspace/tree?scope=tenant` lazy-seeds the directories + the README in the same call.

### Platform scope (superuser-only)

Independent root at `/opt/agentprovision/platform-docs/` (override `PLATFORM_DOCS_ROOT`). Ships pre-populated from `docs/` via the api Dockerfile. **Curated** — never point this at `/app` (that exposes `core/config.py`, `test.db`, the full source tree; the B3 fix on PR #514 documents the prior footgun).

---

## 3. Backend endpoints

All three are kernel verbs (HTTP route ≡ `alpha workspace …` subcommand).

| Verb | Endpoint | Purpose |
|---|---|---|
| `alpha workspace tree` | `GET /api/v1/workspace/tree?scope=tenant\|platform&path=…` | Lazy single-directory listing (`{entries: [{name, kind, size}]}`). Dirs first alpha, then files alpha. |
| `alpha workspace read` | `GET /api/v1/workspace/file?scope=…&path=…` | One file's content. 256 KiB cap → `truncated=true`. Binaries → `{is_binary: true, content: null}`. |
| `alpha workspace clone` | `POST /api/v1/workspace/clone` *(new, parallel impl agent)* | Clone a user's GitHub repo into `projects/<repo>/`. Runs `git clone` inside `code-worker` via background task. Emits `workspace_repo_cloned` SSE event. |

### Security boundaries

Every endpoint applies the same guards (see `_safe_join` + `_reject_hidden_segments` in `workspace.py`):

1. **Tenant isolation** — scope `tenant` resolves the root as `${WORKSPACES_ROOT}/${user.tenant_id}/`. No path can escape via `..` or absolute prefixes (`Path.resolve()` + `relative_to()` check).
2. **Hidden-segment filter** — any path component starting with `.` (e.g. `.git`, `.env`, `.ssh`) or in `_BLOCKED_DIRS` (`__pycache__`, `node_modules`, `.git`, `.venv`, `venv`) is rejected **even when accessed directly** (`?path=.git/HEAD` → 404). Listings filter the same set.
3. **Platform-scope superuser gate** — `scope=platform` is 403 unless `user.is_superuser`. Platform reads are additionally restricted to `{.md, .txt, .rst, .yaml, .yml, .json}`.
4. **256 KiB per-file cap** — files larger than `_MAX_FILE_BYTES` return the first 256 KiB with `truncated=true` (no 413; SPA renders cleanly).
5. **Binary detection** — UTF-8 decode attempt; on `UnicodeDecodeError` returns `is_binary=true, content=null`.
6. **Read-only v1** — no write / delete / move endpoints. `clone` is the one exception and writes only inside `projects/<repo>/`, validated through `_safe_join`. Any future writer must re-audit the TOCTOU contract (`_safe_join` is symlink-safe **only** because no current endpoint creates symlinks).

---

## 4. Memory + sessions persistence

Because `memory/` lives on the workspaces volume, files Luna writes there are durable across:

- container restarts (`docker compose restart api code-worker`),
- image rebuilds + `helm upgrade`,
- node reboots,
- session boundaries — a memory written in one chat is readable from any future session by the same tenant.

This is the substrate for the Memory-First Platform redesign (see memory `memory_first_design.md`). When Luna writes `memory/<topic>.md`, it survives. When the `read_library_skill` MCP tool or a CLI runtime reads from `projects/<repo>/`, they see the same bytes the dashboard tree shows.

Workstation ↔ cloud sync of this tree is tracked separately as task **#256** (backlog).

---

## 5. `alpha workspace clone` — kernel pattern in action

Demonstrates the [`alpha_cli_kernel.md`](alpha_cli_kernel.md) principle end-to-end:

```
Web /dashboard  ─click "Clone repo"─▶  POST /api/v1/workspace/clone {owner, repo}
                                              │
                                              ▼  (kernel verb)
                                ┌──────────────────────────────┐
                                │  alpha workspace clone …     │
                                └──────────────────────────────┘
                                              │
                                              ▼  background task
                              git clone inside code-worker
                              (which now mounts the volume)
                                              │
                                              ▼
                              writes to /var/agentprovision/workspaces/
                                              <tenant_id>/projects/<repo>/
                                              │
                                              ▼
                              publish_session_event("workspace_repo_cloned", …)
                                              │
                                              ▼
                              v2 SSE → dashboard tree refresh
```

Reachable identically from every channel — terminal (`alpha workspace clone owner/repo`), Tauri (Rust shells out), WhatsApp (`/workspace clone owner/repo`), or a leaf agent via MCP. The frontend never invokes `git`; it calls the thin HTTP route that delegates to the same Python entrypoint the `alpha` binary calls.

Adding a sibling verb (e.g. `alpha workspace pull`) means one kernel handler — every viewport gets it for free.

---

## 6. References

| Topic | Doc |
|---|---|
| Kernel principle | [`alpha_cli_kernel.md`](alpha_cli_kernel.md) |
| Dashboard layout (Files mode) | [`dashboard.md`](dashboard.md) |
| Control plane (event protocol, SSE) | [`../plans/2026-05-15-alpha-control-plane-design.md`](../plans/2026-05-15-alpha-control-plane-design.md) |
| Memory-first design | memory `memory_first_design.md` |
| `alpha` CLI reference | [`../cli/README.md`](../cli/README.md) |
| Workspace backend | `apps/api/app/api/v1/workspace.py` |
| Helm PVC | `helm/charts/microservice/templates/workspaces-pvc.yaml` |
