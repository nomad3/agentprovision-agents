#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Luna Phase 5.1 — SIGNED BOUNDED ACTUATION arg-flow live validation
# ──────────────────────────────────────────────────────────────────────────────
# The canary suite (computer-use-suite.sh) only ever fires the FIXED canary (it
# puts text/keys at payload top-level, which the server ignores → client falls
# back to "luna canary" / Right-arrow / screen-centre). This script proves the
# Phase 5.1 ARG flow: the server signs the EXACT actuation args (pointer coords as
# integer micro-units, keyboard text) into the Ed25519 envelope, and the client
# actuates THOSE — not the canary.
#
# Requires the Phase 5.1 WAVE deployed: #851 (server signs args as int micro-units)
# AND #852 (client parses + actuates verified args) — i.e. the NEW Luna DMG must be
# installed. Run AFTER confirming the installed Luna version carries #852.
#
# VISUAL CONFIRMATION IS THE REAL ASSERTION: the server strips typed text and never
# persists coords, so a DB status of 'succeeded' is necessary-but-not-sufficient.
# Focus a visible text field in Luna and WATCH it type the real string / the cursor
# land at the real point.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail
cd /Users/nomade/Documents/GitHub/agentprovision-agents || exit 1

TID="${LUNA_E2E_TENANT_ID:-752626d9-8b2c-4aa2-87ef-c458d48bd38a}"
USERID="${LUNA_E2E_USER_ID:-577c1796-1ed6-4735-9b8e-83fd89f44182}"
CANARY="com.agentprovision.luna"
BASE="http://localhost:8000/api/v1/desktop-control/internal"
SHELL_ID_FILE="$HOME/Library/Application Support/com.agentprovision.luna/desktop-shell-id"

TYPE_TEXT="${PHASE5_TYPE_TEXT:-phase5 works}"     # the real string we expect typed
CLICK_X="${PHASE5_CLICK_X:-0.7}"                   # normalized fraction (issuer API)
CLICK_Y="${PHASE5_CLICK_Y:-0.3}"

KEY="${API_INTERNAL_KEY:-$(grep -E '^API_INTERNAL_KEY=' apps/api/.env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]')}"
SHELL_ID="$(tr -d '[:space:]' < "$SHELL_ID_FILE" 2>/dev/null)"
[ -z "$KEY" ] && { echo "FATAL: API_INTERNAL_KEY not found"; exit 1; }
[ -z "$SHELL_ID" ] && { echo "FATAL: no shell id at $SHELL_ID_FILE — launch Luna once first"; exit 1; }

H=(-H "X-Internal-Key: $KEY" -H "X-Tenant-Id: $TID" -H "X-User-Id: $USERID" -H "Content-Type: application/json")
ts() { date '+%H:%M:%S'; }
log() { echo "[$(ts)] $*"; }
db()  { docker compose exec -T db psql -U postgres -d agentprovision -t -A -c "$1" 2>/dev/null | tr -d '[:space:]'; }
jget(){ python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null; }
frontmost() { open -a Luna 2>/dev/null; sleep 2; }

grant() {  # grant <capability> <action> -> approval_id
  curl -s -X POST "$BASE/approval-grants" "${H[@]}" -d \
    "{\"session_id\":\"$SID\",\"shell_id\":\"$SHELL_ID\",\"risk_tier\":\"native_control\",\"capability\":\"$1\",\"max_actions\":2,\"expires_in_seconds\":120,\"target_binding\":{\"bundle_id\":\"$CANARY\",\"action\":\"$2\"}}" | jget approval_id
}

# enqueue_args <action> <tool> <approval_id> <args_json>  (args_json = the inner {…})
enqueue_args() {
  local action="$1" tool="$2" appr="$3" args="$4"
  curl -s -X POST "$BASE/commands" "${H[@]}" -d \
    "{\"session_id\":\"$SID\",\"shell_id\":\"$SHELL_ID\",\"action\":\"$action\",\"tool_name\":\"$tool\",\"approval_id\":\"$appr\",\"nonce\":\"p5args-${action}-$(date +%s%N)\",\"payload\":{\"args\":$args,\"target\":{\"bundle_id\":\"$CANARY\",\"action\":\"$action\"}}}" | jget desktop_command_id
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
signed_args() { db "SELECT (payload::json->'request') IS NOT NULL FROM desktop_commands WHERE id='$1';" >/dev/null; }

SID="$(db "SELECT id FROM chat_sessions WHERE owner_user_id='$USERID' ORDER BY created_at DESC LIMIT 1;")"
[ -z "$SID" ] && { echo "FATAL: no chat session for $USERID"; exit 1; }
log "session=$SID shell=$SHELL_ID"
log "Bring Luna frontmost with a VISIBLE TEXT FIELD focused, then watch the screen."

# ── A1 — keyboard_type actuates the REAL signed text ──────────────────────────
frontmost
A="$(grant keyboard_control keyboard_type)"
CID="$(enqueue_args keyboard_type desktop_keyboard_type "$A" "{\"text\":\"$TYPE_TEXT\"}")"
ST="$(poll_status "$CID")"
log "A1 keyboard_type args.text='$TYPE_TEXT' -> status=$ST  (id=$CID)"
log "   VISUAL: confirm Luna typed '$TYPE_TEXT'  (NOT 'luna canary')"

# ── A2 — pointer_click actuates the REAL signed coords ────────────────────────
frontmost
A="$(grant pointer_control pointer_click)"
CID="$(enqueue_args pointer_click desktop_pointer_click "$A" "{\"x\":$CLICK_X,\"y\":$CLICK_Y}")"
ST="$(poll_status "$CID")"
log "A2 pointer_click args.x=$CLICK_X y=$CLICK_Y -> status=$ST  (id=$CID)"
log "   VISUAL: confirm the cursor landed at ${CLICK_X}x/${CLICK_Y}y of the screen (NOT centre 0.5/0.5)"

echo
log "DB status 'succeeded' proves the signed→verified→actuated path completed."
log "The PROOF that the SIGNED ARGS (not the canary) actuated is what you SEE on screen."
