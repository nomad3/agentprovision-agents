# WhatsApp session durability — never force a QR re-pair from server-side corruption

**Date:** 2026-06-02 · **Status:** Design v2 (Codex-5.5 review incorporated — see §7)
**Files:** `apps/api/app/services/whatsapp_service.py`, `apps/api/app/main.py` (lifespan), `apps/api/app/models/channel_account.py` (+ new `whatsapp_session_backups` table / migration), `docker-compose.yml` + `helm` (grace), neonize session storage.
**Related memories:** whatsapp_silent_disconnect_recovery, whatsapp_auto_restore_handler, whatsapp_pairing_qr_regen_race.

## The problem (recurring, operator-confirmed)
WhatsApp on AgentProvision has a long tail of reliability pain, all converging on one unacceptable outcome — **the operator/customer is asked to re-scan a QR because the *server* corrupted the pair**:
- Silent socket death (socket dead, DB says "connected") — partly handled by `_socket_heartbeat`.
- Reactive band-aids: restart-the-api, the `readonly database` auto-restore handler (PR #299), `.corrupt-backup`/`.pre-repair` files.
- **Session corruption → forced QR re-pair** (terrible UX, especially for *customer* tenants like Chielo/leidy/Brett who must physically re-link their phone).
- **The api hangs ~180s on restart** (`stop_grace_period: 180s` + WhatsApp/SSE connections never close on SIGTERM → uvicorn waits → SIGKILL).

## Root cause (the hang and the corruption are the SAME bug)
The neonize device session is an **on-disk SQLite file** (`_client_name(...)`), persisted to Postgres as a gzip blob in `channel_accounts.session_blob` (`_save_session_to_db`). Saves are serialized by a per-account lock and a `_socket_heartbeat` detects silent death. **But nothing protects against a process death mid-write, and nothing validates a blob before it overwrites the good one.** Verified corruption vectors in the current code:

1. **SIGKILL mid-SQLite-write** — today's `restart` → 180s hung grace → SIGKILL lands *during* a session write → corrupt SQLite → corrupt blob → QR.
2. **The "corruption amplifier" in `_save_session_to_db`** (lines 542–562, verified): it attempts `PRAGMA wal_checkpoint(FULL)` with `timeout=2`; **on failure it logs at `debug` ("likely locked") and then unconditionally reads the file and overwrites `session_blob`.** No `integrity_check`, no validation, no backup. A locked / mid-write / inconsistent SQLite therefore **silently replaces the last known-good Postgres copy.**
3. **The restore path** (`_restore_session_from_db`, lines 571–602, verified) decompresses and writes **whatever blob is stored** with zero validation → a corrupt blob round-trips straight back onto disk → QR.
4. **A single `session_blob` field** (`channel_account.py`) means there is no second copy to fall back to once it's been overwritten.

So the shutdown hang is not separate from the corruption — it *triggers* it, and the unvalidated save/restore path *amplifies and persists* it.

## Design — the proper fix
Guarantee: **a re-scan is required ONLY when WhatsApp itself revoked the device** (user unlinks / 30-day inactivity / `LoggedOutEv`). Server crashes, restarts, and concurrency must always recover from a durable, *validated* copy — never QR.

Two contracts make this testable, and both came directly out of the Codex-5.5 review:
- **C1 — Drain barrier (do not trust silent disconnect).** `client.disconnect()` is **not** a proven flush barrier for whatsmeow's SQLite/WAL. We never assume it succeeded; we **validate after** it returns and treat any timeout/failure as "keep the known-good backup, do not overwrite."
- **C2 — Never overwrite known-good.** A blob becomes the **current** session only if it passes validation. A failed checkpoint/validation **must preserve** the existing current + backups. This is the inverse of today's behaviour.

### 1. Clean shutdown with an explicit, bounded drain barrier (kills the #1 corruption vector AND the hang)
A FastAPI `lifespan` shutdown handler that, on SIGTERM, **before** the process exits:
1. **Mark the service `draining`** — reject *new* inbound WhatsApp work and cancel the reconnect/heartbeat tasks (so no concurrent writer races the shutdown save).
2. **Bounded-wait for in-flight chat turns** (see §5) up to a `DRAIN_DEADLINE` that is strictly **less** than the container stop grace.
3. For each connected account, **under the per-account `_session_lock`**:
   - `await asyncio.wait_for(client.disconnect(), timeout=DISCONNECT_TIMEOUT)`,
   - `PRAGMA wal_checkpoint(FULL)` (assert it returns success, not just "tried"),
   - **validate** the SQLite (§2), and only on PASS persist it as the new current + push a backup;
   - **on disconnect timeout OR checkpoint/validate failure → do NOT write.** Leave the last known-good current + backups untouched (C1/C2).
4. Close SSE event streams so uvicorn drains immediately.

Then set `stop_grace_period` to `DRAIN_DEADLINE + DISCONNECT_TIMEOUT + margin` (a *bounded* value, **not** a blind 30s — see §5), so a `restart` comes back in seconds with a clean, flushed, validated session. No 180s hang, no SIGKILL-mid-write.

### 2. Mandatory validation before a blob becomes "current" (C2 — recover-never-QR)
Replace the debug-log-and-continue in `_save_session_to_db` with a hard gate. Before a blob is written as **current**:
- checkpoint must have **succeeded** (a failed/locked checkpoint means the on-disk file may be mid-write → abort the save);
- `PRAGMA integrity_check` must return `ok`;
- the **device-identity assertion**: the expected whatsmeow auth/device tables and key rows are present and non-empty (a structurally-valid-but-keyless DB is useless — Codex's note: "check expected auth/device tables/keys, not only `integrity_check`").
Only a blob passing **all three** replaces current. Any failure → keep current, log **loudly** (warning/error, not debug), and leave recovery to the backups.

### 3. Validated, backed-up Postgres persistence — dedicated table
Backups live in **Postgres, not filesystem sidecars** (the FS is the fragile artifact we're trying to escape). New `whatsapp_session_backups` table:

| column | purpose |
|---|---|
| `tenant_id`, `account_id` | scope |
| `created_at` | ordering / prune key |
| `blob` (gzip) | the validated SQLite snapshot |
| `sha256`, `size_bytes` | integrity + dedupe |
| `validation_status` | `ok` (only `ok` rows are restore candidates) |
| `source_event` | `shutdown` / `periodic` / `post_pair` / `pre_repair` |

- `channel_accounts.session_blob` stays as the **current** pointer/cache.
- Every validated save also inserts a backup row; **prune to the last N `ok` rows** (e.g. N=3).
- **Restore order:** current (re-validate on read) → newest `ok` backup → next → … QR is reached only if *every* `ok` copy fails validation (effectively never) or the device was genuinely revoked.
- A corrupt local SQLite can therefore **never overwrite a good Postgres session**, and a corrupt **current** can always fall back to a good backup.

### 4. SQLite hardening
- `journal_mode=WAL`, `synchronous=FULL` (or NORMAL + explicit checkpoint-before-save), `busy_timeout` to kill the `readonly database` races, checkpoint-before-save. Single-writer is guaranteed by the existing `_session_lock`; assert no second process/connection opens the same file during the shutdown save.

### 5. Decouple chat turns from shutdown (why 30s alone is unsafe)
The original 180s grace existed to let 30–90s chat turns finish. WhatsApp inbound runs `post_user_message` in `asyncio.to_thread`, and **that thread is not cancellable once started** (Codex). So a blind 30s grace can still kill an in-flight response. Two acceptable resolutions:
- **Now (fold in):** the drain handler (§1.1–1.2) stops accepting new WhatsApp work and **bounded-waits** for active turns up to `DRAIN_DEADLINE`; the stop grace is sized to cover that deadline + the disconnect/save. Bounded, not blind.
- **Later (follow-up, bigger change):** move WhatsApp turns onto durable Temporal/chat jobs so an api restart never interrupts a turn at all. Tracked separately.

### 6. Keep + sharpen the heartbeat; QR only on true revoke
- Keep `_socket_heartbeat` (silent-death detection → reconnect). On reconnect failure, **recover from the durable validated Postgres copy**, never QR.
- **Recovery code must NEVER call the destructive path.** `start_pairing(force=True)` deletes `.db/-wal/-shm` and **nulls `session_blob`** (lines 1455–1484) — that path is reserved for **explicit operator unlink / re-pair only**. Add a guard/assert so no auto-recovery, heartbeat, or restore branch can reach `force=True` or the blob-clearing branch.
- Surface a QR **only** on a true `LoggedOutEv` / explicit operator unlink. A recoverable server-side corruption must *self-heal* from backup and log loudly, never prompt the user.

## Acceptance criteria (testable)
- `docker compose restart api` → WhatsApp reconnects in **seconds**, no corruption, no QR.
- `kill -9` the api mid-operation → on restart, session restores from the last known-good Postgres copy, **no QR**.
- **Inject a checkpoint failure / locked DB at save time** → the save is **aborted**, current + backups are **untouched** (C2), loud warning logged — *no* silently-corrupt overwrite.
- **Inject a corrupt `current` blob** → restore falls back to a good backup, **no QR**; loud log, no user prompt.
- **Disconnect that hangs past `DISCONNECT_TIMEOUT`** → save aborts, known-good preserved (C1), process still exits within grace.
- An in-flight WhatsApp chat turn at SIGTERM is **allowed to finish** within `DRAIN_DEADLINE` (not truncated by a blind grace).
- A real device unlink → QR shown (the *only* legitimate QR path). Auto-recovery never reaches `force=True`/blob-clearing.

## 7. Codex-5.5 review — verdict + resolutions (incorporated)
**Verdict: Request Changes → addressed.** Highest-risk gap and all five findings are folded in above. Verified each claim against the source before integrating:

1. *Highest-risk gap — disconnect-as-drain-barrier is unproven.* → **C1 / §1.3:** `wait_for(disconnect)` + validate-after; timeout ⇒ keep known-good.
2. *Shutdown disconnects but never persists/validates/checkpoints under lock.* → **§1:** new lifespan handler does mark-draining → bounded-wait → `disconnect` → checkpoint → validate → save, all under `_session_lock`.
3. *`_save_session_to_db` overwrites good state on checkpoint failure (corruption amplifier).* → **C2 / §2:** mandatory checkpoint-success + `integrity_check` + device-key assertion before a blob becomes current; failure preserves known-good and logs loudly (was `debug`).
4. *Backups belong in Postgres, not FS sidecars; single `session_blob` is insufficient.* → **§3:** dedicated `whatsapp_session_backups` table (sha256/size/validation_status/source_event), prune to N `ok` rows, multi-tier restore.
5. *30s grace risky — `post_user_message` in `asyncio.to_thread` is not cancellable.* → **§5:** drain-and-bounded-wait + grace sized to the drain deadline (not blind 30s); durable-turn migration tracked as follow-up.
6. *`start_pairing(force=True)` can still force a QR.* → **§6:** destructive path reserved for explicit operator unlink only; guard added so recovery code can never reach it.

**Pressure-test answers (Codex), now design contracts:**
- Clean disconnect: *plausible, not proven* → wrapped in `wait_for`; validate/checkpoint after; timeout ⇒ "do not overwrite good backup."
- Integrity check + rolling backup: *sound if validation gates writes and backups live in Postgres with metadata; check auth/device tables/keys, not just `integrity_check`.* → §2 + §3.
- 30s grace: *not safe by itself; safe only with draining semantics or durable async chat execution.* → §5.
- Still-QR set: *true `LoggedOutEv`, user unlink, 30-day device expiry, all backups missing/corrupt, or accidental `force=True`/blob-clearing.* → §6 closes the accidental-`force=True` path; the rest are the legitimate (rare) QR cases.

## Implementation order (for the build PR)
1. Migration + model: `whatsapp_session_backups` table.
2. `_save_session_to_db` → validated-save (checkpoint-success + integrity_check + device-key assert + backup insert + prune). **Inverts the current overwrite behaviour.**
3. `_restore_session_from_db` → re-validate current, multi-tier fallback to backups.
4. Guard `force=True`/blob-clearing to operator-only.
5. `main.py` lifespan shutdown handler (drain → disconnect → validated-save under lock) + SSE close.
6. Tune `stop_grace_period` (+ helm mirror) to the bounded drain budget.
7. Tests for each acceptance criterion (esp. the "checkpoint-fail must NOT overwrite" and "corrupt-current falls back to backup" cases).

## 8. Implementation + review round 2 (built; adversarial panel + Codex-5.5)

Built on `docs/whatsapp-session-durability`. After implementing, a 5-dimension adversarial review (each finding verified against the source) surfaced 3 blockers + 4 important + nits — all folded in:

- **Grace stays 180s (NOT 30s).** Codex's "30s unsafe" holds: WhatsApp inbound turns run in a non-cancellable `asyncio.to_thread`. The fix is the bounded drain, not a shorter grace. The drain bounded-waits in-flight turns (deadline 90s), then disconnects+saves; `main.py` caps the whole thing at 165s < 180s. compose + helm comments pin this so nobody drops it.
- **C1-1/C1-2 (blockers) — concurrent-writer race.** `on_disconnected` no longer resets status / schedules reconnect while `_draining`; `_auto_reconnect` and `reconnect` hard short-circuit on `_draining`; the drain cancels all recovery tasks (heartbeat/stable-reset/watchdog/connect) up front before the wait.
- **C1-3 (important) — drain bounded for N accounts.** Per-account disconnect+save runs concurrently (`asyncio.gather`), so total ≈ one disconnect window regardless of account count.
- **C1-4 (important) — drain gate at the true entrypoint.** `_handle_inbound` rejects on `_draining` before the up-to-90s media download, not only at the chat-turn boundary.
- **FG-1 (blocker) — `start_pairing(force=True)` deadlock.** Disconnect moved OUTSIDE the session lock (same hazard the drain avoids); destructive file/DB teardown stays under the lock.
- **C2-VALIDATE (important) — no false-positive.** A device-less / unrecognised-schema blob is now a HARD FAIL in `_validate_sqlite_bytes` (integrity-only is no longer "known-good"), so it can never become current or an `ok` backup.
- **MTR-1 (important) — loud self-heal failure;** **MTR-3 (important) — on total-failure, normalise on-disk state** (stash torn `.db` → `.corrupt-backup`, drop `-wal/-shm`) so neonize starts deterministically.
- **Nits folded:** MTR-5 stable order tiebreaker, MTR-6 close DB before the slow validate/write loop, FG-3 prune comment, FG-4 meaningful `source_event`, FG-5 redundant imports, F1/F2 model↔migration parity (timezone-aware NOT NULL `created_at`, CHECK + composite index + server_defaults). 26 unit tests cover validation, never-overwrite, multi-tier restore, on-disk normalisation, the force guard, and drain behaviour.

**Deferred (surfaced to Luna):** the residual restart-hang lever is closing the v2 `/api/v2/sessions/{id}/events` SSE streams on shutdown so uvicorn drains immediately. The corruption fix already makes any SIGKILL recoverable (restore falls back to a validated backup → no QR), so this is a latency/UX follow-up, not a durability one — tracked separately rather than expanding this PR into the SSE path.
