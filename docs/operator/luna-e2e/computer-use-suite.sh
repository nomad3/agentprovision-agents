#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Luna macOS computer-use real-life E2E suite — pointer (Phase 3) + keyboard (Phase 4)
# ──────────────────────────────────────────────────────────────────────────────
# Fires signed native-control commands at the LIVE installed Luna.app and asserts
# the persisted DB outcome for each case. Exercises both allow paths (pointer move/
# click, keyboard type/chord) and denial paths that prove the safety gates hold
# (non-allowlisted target, capability mismatch, budget exhaustion).
#
# This is an OPERATOR tool, not a unit test — it drives the real OS event stream
# through the same server-issued → Ed25519-signed → boundary-gated → enigo path a
# production actuation takes. The boundary/lease/bounds logic is unit-tested in
# apps/luna-client/src-tauri (cargo) and apps/api/tests (pytest); this proves the
# wires connect end to end on a real machine.
#
# Prereqs (see README.md):
#   1. Phase 4 merged + deployed:
#        - api: _DISABLED_NATIVE_CONTROL_ACTIONS == frozenset()  (keyboard enabled)
#        - Luna DMG: keyboard canary actuation present
#   2. api force-recreated with the E2E .env (signing key + bundle allowlist):
#        docker compose up -d --force-recreate api
#   3. Luna launched with the per-capability flags + signer public key:
#        LUNA_ACTUATION_POINTER_ENABLED=true LUNA_ACTUATION_KEYBOARD_ENABLED=true \
#        LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY=$PUBKEY \
#        /Applications/Luna.app/Contents/MacOS/luna &
#      (the launch_luna helper below does this for you)
#   4. A chat session owned by $USERID exists (the suite picks the most recent).
#
# Manual safety cases that need a human/UI and are NOT scripted here (see README):
#   - Durable Stop latch: click Stop in the Control strip → every command denied
#     (reason=stopped) → only the UI "Resume" (control_clear_stop) re-enables.
#   - Secure-input: focus a password field → keyboard canary denied (fail-closed).
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail
cd /Users/nomade/Documents/GitHub/agentprovision-agents || exit 1

# ── Config (UUIDs + public key are not secrets; the internal key is sourced at
#    runtime from apps/api/.env so nothing secret is committed) ────────────────
TID="${LUNA_E2E_TENANT_ID:-752626d9-8b2c-4aa2-87ef-c458d48bd38a}"
USERID="${LUNA_E2E_USER_ID:-577c1796-1ed6-4735-9b8e-83fd89f44182}"
PUBKEY="${LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY:-6jwnVWgGQGoMd3Ck84TzxixHj5oiC-74amrZIXe-V1U}"
SHELL_ID_FILE="$HOME/Library/Application Support/com.agentprovision.luna/desktop-shell-id"
CANARY="com.agentprovision.luna"
NONALLOW="com.apple.TextEdit"   # deliberately NOT in the canary allowlist
BASE="http://localhost:8000/api/v1/desktop-control/internal"

KEY="${API_INTERNAL_KEY:-$(grep -E '^API_INTERNAL_KEY=' apps/api/.env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]')}"
SHELL_ID="$(tr -d '[:space:]' < "$SHELL_ID_FILE" 2>/dev/null)"

if [ -z "$KEY" ]; then echo "FATAL: API_INTERNAL_KEY not found (env or apps/api/.env)"; exit 1; fi
if [ -z "$SHELL_ID" ]; then echo "FATAL: no shell id at $SHELL_ID_FILE — launch Luna once first"; exit 1; fi

H=(-H "X-Internal-Key: $KEY" -H "X-Tenant-Id: $TID" -H "X-User-Id: $USERID" -H "Content-Type: application/json")
PASS=0; FAIL=0; RESULTS=()

# ── Helpers ───────────────────────────────────────────────────────────────────
ts() { date '+%H:%M:%S'; }
log() { echo "[$(ts)] $*"; }
db()  { docker compose exec -T db psql -U postgres -d agentprovision -t -A -c "$1" 2>/dev/null | tr -d '[:space:]'; }
jget(){ python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null; }

active_session() { db "SELECT id FROM chat_sessions WHERE owner_user_id='$USERID' ORDER BY created_at DESC LIMIT 1;"; }
frontmost()      { open -a Luna 2>/dev/null; sleep 2; }

launch_luna() {
  pkill -f "/Applications/Luna.app/Contents/MacOS/luna" 2>/dev/null; sleep 2
  LUNA_ACTUATION_POINTER_ENABLED=true LUNA_ACTUATION_KEYBOARD_ENABLED=true \
    LUNA_DESKTOP_COMMAND_ENVELOPE_ED25519_PUBLIC_KEY="$PUBKEY" \
    nohup /Applications/Luna.app/Contents/MacOS/luna >/tmp/luna-e2e/luna-suite.log 2>&1 &
  sleep 22
}

# grant <capability> <action> <max_actions> -> approval_id (bound to the canary)
grant() {
  curl -s -X POST "$BASE/approval-grants" "${H[@]}" -d \
    "{\"session_id\":\"$SID\",\"shell_id\":\"$SHELL_ID\",\"risk_tier\":\"native_control\",\"capability\":\"$1\",\"max_actions\":$3,\"expires_in_seconds\":120,\"target_binding\":{\"bundle_id\":\"$CANARY\",\"action\":\"$2\"}}" | jget approval_id
}

# enqueue <action> <tool_name> <approval_id> <target_bundle> <payload_json_no_braces>
# returns desktop_command_id ("" if the server rejected the enqueue)
enqueue() {
  local action="$1" tool="$2" appr="$3" bundle="$4" extra="$5"
  local nonce
  nonce="suite-${action}-$(date +%s%N)"
  local payload="\"target\":{\"bundle_id\":\"$bundle\",\"action\":\"$action\"}"
  [ -n "$extra" ] && payload="$extra,$payload"
  curl -s -X POST "$BASE/commands" "${H[@]}" -d \
    "{\"session_id\":\"$SID\",\"shell_id\":\"$SHELL_ID\",\"action\":\"$action\",\"tool_name\":\"$tool\",\"approval_id\":\"$appr\",\"nonce\":\"$nonce\",\"payload\":{$payload}}"
}

poll_status() {
  local st=""
  for _ in $(seq 1 15); do
    st="$(db "SELECT status FROM desktop_commands WHERE id='$1';")"
    case "$st" in succeeded|failed|denied|preempted|expired) break;; esac
    sleep 2
  done
  echo "${st:-pending}"
}
audit_reason() { db "SELECT COALESCE(reason,'') FROM desktop_command_events WHERE desktop_command_id='$1' AND event_type='desktop_command_completed' LIMIT 1;"; }

record_pass() { PASS=$((PASS+1)); RESULTS+=("PASS $1"); log "PASS  $1"; }
record_fail() { FAIL=$((FAIL+1)); RESULTS+=("FAIL $1"); log "FAIL  $1"; }
assert_eq()  { [ "$1" = "$2" ] && record_pass "$3 (got=$1)" || record_fail "$3 (got=$1 want=$2)"; }
assert_in()  { local got="$1" label="$2"; shift 2; for w in "$@"; do [ "$got" = "$w" ] && { record_pass "$label (got=$got)"; return; }; done; record_fail "$label (got=$got want∈{$*})"; }

# ── Preflight ─────────────────────────────────────────────────────────────────
mkdir -p /tmp/luna-e2e
log "Luna computer-use E2E suite — shell=$SHELL_ID"
if ! pgrep -f "/Applications/Luna.app/Contents/MacOS/luna" >/dev/null; then
  log "Luna not running — launching with pointer+keyboard flags"
  launch_luna
fi
SID="$(active_session)"
[ -z "$SID" ] && { echo "FATAL: no chat session for user $USERID"; exit 1; }
log "session=$SID"

# ════════════════════════════ ALLOW PATHS ════════════════════════════════════
# P1 — pointer move actuates
frontmost
A="$(grant pointer_control pointer_move 2)"
CID="$(enqueue pointer_move desktop_pointer_move "$A" "$CANARY" "" | jget desktop_command_id)"
ST="$(poll_status "$CID")"; log "  P1 reason=$(audit_reason "$CID")"
assert_eq "$ST" succeeded "P1 pointer_move actuates"

# P2 — pointer click actuates
frontmost
A="$(grant pointer_control pointer_click 2)"
CID="$(enqueue pointer_click desktop_pointer_click "$A" "$CANARY" "" | jget desktop_command_id)"
ST="$(poll_status "$CID")"; log "  P2 reason=$(audit_reason "$CID")"
assert_eq "$ST" succeeded "P2 pointer_click actuates"

# K1 — keyboard type actuates (client types its fixed canary string; server strips text)
frontmost
A="$(grant keyboard_control keyboard_type 2)"
CID="$(enqueue keyboard_type desktop_keyboard_type "$A" "$CANARY" "\"text\":\"luna canary\"" | jget desktop_command_id)"
ST="$(poll_status "$CID")"; log "  K1 reason=$(audit_reason "$CID")"
assert_eq "$ST" succeeded "K1 keyboard_type actuates"

# K2 — keyboard chord (Right arrow) actuates
frontmost
A="$(grant keyboard_control keyboard_key_chord 2)"
CID="$(enqueue keyboard_key_chord desktop_keyboard_key_chord "$A" "$CANARY" "\"keys\":[\"right\"]" | jget desktop_command_id)"
ST="$(poll_status "$CID")"; log "  K2 reason=$(audit_reason "$CID")"
assert_eq "$ST" succeeded "K2 keyboard_key_chord actuates"

# ════════════════════════════ DENIAL PATHS ═══════════════════════════════════
# D1 — non-allowlisted target bundle is refused (server allowlist gate). The
#      enqueue should be rejected outright (no command id); if a command is
#      created it must not reach succeeded.
frontmost
A="$(grant pointer_control pointer_move 2)"
RESP="$(enqueue pointer_move desktop_pointer_move "$A" "$NONALLOW" "")"
CID="$(echo "$RESP" | jget desktop_command_id)"
if [ -z "$CID" ]; then
  record_pass "D1 non-allowlisted target refused at enqueue (resp=$(echo "$RESP" | head -c60))"
else
  ST="$(poll_status "$CID")"; assert_in "$ST" "D1 non-allowlisted target not actuated" denied failed expired preempted
fi

# D2 — capability mismatch: a keyboard command presented against a pointer grant
#      must not actuate (boundary/capability gate).
frontmost
A="$(grant pointer_control pointer_move 2)"   # pointer grant
RESP="$(enqueue keyboard_type desktop_keyboard_type "$A" "$CANARY" "\"text\":\"luna canary\"")"
CID="$(echo "$RESP" | jget desktop_command_id)"
if [ -z "$CID" ]; then
  record_pass "D2 capability mismatch refused at enqueue (resp=$(echo "$RESP" | head -c60))"
else
  ST="$(poll_status "$CID")"; assert_in "$ST" "D2 capability mismatch not actuated" denied failed expired preempted
fi

# D3 — budget exhaustion: a grant of max_actions=1 actuates once, then the second
#      actuation against the same grant is refused.
frontmost
A="$(grant pointer_control pointer_move 1)"
CID1="$(enqueue pointer_move desktop_pointer_move "$A" "$CANARY" "" | jget desktop_command_id)"
ST1="$(poll_status "$CID1")"
assert_eq "$ST1" succeeded "D3a first actuation within budget"
RESP2="$(enqueue pointer_move desktop_pointer_move "$A" "$CANARY" "")"
CID2="$(echo "$RESP2" | jget desktop_command_id)"
if [ -z "$CID2" ]; then
  record_pass "D3b over-budget actuation refused at enqueue"
else
  ST2="$(poll_status "$CID2")"; assert_in "$ST2" "D3b over-budget actuation not actuated" denied failed expired preempted
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════════════"
printf '  %s\n' "${RESULTS[@]}"
echo "════════════════════════════════════════════════════════════════"
echo "  TOTAL: $PASS passed, $FAIL failed"
echo "════════════════════════════════════════════════════════════════"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
