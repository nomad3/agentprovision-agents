# WhatsApp session durability — never force a QR re-pair from server-side corruption

**Date:** 2026-06-02 · **Status:** Design (for Codex-5.5 + Luna review before implementing)
**Files:** `apps/api/app/services/whatsapp_service.py`, `apps/api/app/main.py` (lifespan), `docker-compose.yml` + `helm` (grace), neonize session storage.
**Related memories:** whatsapp_silent_disconnect_recovery, whatsapp_auto_restore_handler, whatsapp_pairing_qr_regen_race.

## The problem (recurring, operator-confirmed)
WhatsApp on AgentProvision has a long tail of reliability pain, all converging on one unacceptable outcome — **the operator/customer is asked to re-scan a QR because the *server* corrupted the pair**:
- Silent socket death (socket dead, DB says "connected") — partly handled by `_socket_heartbeat`.
- Reactive band-aids: restart-the-api, the `readonly database` auto-restore handler (PR #299), `.corrupt-backup`/`.pre-repair` files.
- **Session corruption → forced QR re-pair** (terrible UX, especially for *customer* tenants like Chielo/leidy/Brett who must physically re-link their phone).
- **The api hangs ~180s on restart** (`stop_grace_period: 180s` + WhatsApp/SSE connections never close on SIGTERM → uvicorn waits → SIGKILL).

## Root cause (the hang and the corruption are the SAME bug)
The neonize device session is an **on-disk SQLite file** (`_client_name(...)`), persisted to Postgres as a blob (`_save_session_to_db` → "Saved neonize session to DB"). Saves are serialized by a per-account lock and a `_socket_heartbeat` detects silent death. **But nothing protects against a process death mid-write.** Corruption vectors:
1. **SIGKILL mid-SQLite-write** — today's `restart` → 180s hung grace → SIGKILL lands *during* a session write → corrupt SQLite → corrupt blob → QR.
2. **The on-disk SQLite is the fragile artifact** — partial writes, `readonly database` lock states, concurrent access.
3. **A corrupt SQLite blob saved to Postgres overwrites the good one** — restore then rehydrates corruption → QR.

So the shutdown hang is not separate from the corruption — it *causes* it.

## Design — the proper fix
Guarantee: **a re-scan is required ONLY when WhatsApp itself revoked the device** (user unlinks / 30-day inactivity / `LoggedOutEv`). Server crashes, restarts, and concurrency must always recover from a durable copy — never QR.

### 1. Clean shutdown (kills the #1 corruption vector AND the hang)
A FastAPI `lifespan`/shutdown handler that on SIGTERM, before the process exits:
- stops accepting new inbound work,
- for each connected account: WAL-checkpoint the SQLite, **cleanly disconnect** the neonize client, then **persist the validated session to Postgres**,
- closes SSE event streams so uvicorn drains immediately.
Then drop `stop_grace_period` to a sane value (e.g. 30s) — the handler does the draining, so a `restart` comes back in seconds with a clean, flushed session. No 180s hang, no SIGKILL-mid-write.

### 2. Validated, backed-up Postgres persistence (recover-never-QR)
- Before writing a blob as the **current** session: run `PRAGMA integrity_check` (and assert the device-identity keys are present). Only a passing blob becomes "current".
- Keep **N rolling known-good backups** in Postgres (e.g. last 3).
- On restore: current → if `integrity_check` fails, fall back to the newest known-good backup → … . QR is reached only if *every* copy is corrupt (effectively never) or the device was genuinely revoked.
- A corrupt local SQLite can therefore **never overwrite a good Postgres session**.

### 3. SQLite hardening
- `journal_mode=WAL`, `synchronous=FULL` (or NORMAL+explicit checkpoint), `busy_timeout` to kill the `readonly database` races, checkpoint-before-save. Single-writer guaranteed by the existing `_session_lock`; assert no second process opens the same file.

### 4. Keep + sharpen the heartbeat
Keep `_socket_heartbeat` (silent-death detection → reconnect). On reconnect failure, **recover the session from the durable Postgres blob**, never QR.

### 5. Make "needs QR" explicit and rare
Only surface a QR on a true `LoggedOutEv` / explicit operator unlink. A recoverable server-side corruption must *self-heal* from backup and log loudly, never prompt the user.

## Acceptance criteria
- `docker compose restart api` → WhatsApp reconnects in **seconds**, no corruption, no QR.
- `kill -9` the api mid-operation → on restart, session restores from the last known-good Postgres blob, **no QR**.
- Inject a corrupt SQLite → recovery from backup, **no QR**; loud log, no user prompt.
- A real device unlink → QR shown (the *only* legitimate QR path).

## Open questions for Codex-5.5 + Luna review
1. Is the neonize SQLite safely closable on SIGTERM from the async handler (does whatsmeow expose a clean `Disconnect()`/close that flushes), or do we need to checkpoint the file directly?
2. Rolling-backup count + where (a `whatsapp_session_backups` table vs versioned rows) — and pruning.
3. Should WhatsApp eventually move out of the api process into a dedicated resilient sidecar (so api restarts never touch the socket at all)? Bigger change — track as a follow-up vs fold in now.
4. The 30s grace vs in-flight chat-turn draining (the original 180s existed to let chat turns finish) — does the lifespan handler need to also drain in-flight chat requests, or are those already bounded elsewhere?
