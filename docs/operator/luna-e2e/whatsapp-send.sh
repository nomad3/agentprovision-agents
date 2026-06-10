#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# Luna — send a WhatsApp message via the computer-use ACTUATION stack
# ──────────────────────────────────────────────────────────────────────────────
# Drives the SAME signed-actuation path as the canary, but against the REAL
# WhatsApp desktop app (net.whatsapp.WhatsApp) — the first app beyond the fixed
# canary. Luna types the message and sends it (Enter), all via server-signed
# Ed25519 envelopes the client verifies + actuates.
#
# PREREQS (operator, ~1 min):
#   1. WhatsApp desktop OPEN and FRONTMOST, with the "Message Yourself" self-chat
#      selected and the message input focused (click it once).
#   2. The Luna client running + connected (it polls commands/claim every ~2s) with
#      LUNA_ACTUATION_KEYBOARD_ENABLED=true (the e2e launch env).
#   3. The "enter" send-key requires the NEW client DMG (PR #865). With the older
#      client the keyboard_key_chord(enter) step is rejected — type still works, then
#      press Return yourself to send. (The robust path is the new DMG.)
#
# Server side is already deployed + verified: net.whatsapp.WhatsApp is in the
# operator allowlist (migration 172) ∩ the global floor, and "enter" is in the
# safe-chord allowlist.
# ──────────────────────────────────────────────────────────────────────────────
set -uo pipefail
cd /Users/nomade/Documents/GitHub/agentprovision-agents || exit 1

TID="${LUNA_E2E_TENANT_ID:-752626d9-8b2c-4aa2-87ef-c458d48bd38a}"
USERID="${LUNA_E2E_USER_ID:-577c1796-1ed6-4735-9b8e-83fd89f44182}"
TARGET="net.whatsapp.WhatsApp"
BASE="http://localhost:8000/api/v1/desktop-control/internal"
SHELL_ID_FILE="$HOME/Library/Application Support/com.agentprovision.luna/desktop-shell-id"
MSG="${WHATSAPP_MSG:-Test from Luna via computer-use 🐺}"

KEY="${API_INTERNAL_KEY:-$(grep -E '^API_INTERNAL_KEY=' apps/api/.env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '[:space:]')}"
SHELL_ID="$(tr -d '[:space:]' < "$SHELL_ID_FILE" 2>/dev/null)"
[ -z "$KEY" ] && { echo "FATAL: API_INTERNAL_KEY not found"; exit 1; }
[ -z "$SHELL_ID" ] && { echo "FATAL: no shell id — launch Luna once first"; exit 1; }

H=(-H "X-Internal-Key: $KEY" -H "X-Tenant-Id: $TID" -H "X-User-Id: $USERID" -H "Content-Type: application/json")
log() { echo "[$(date '+%H:%M:%S')] $*"; }
db()  { docker compose exec -T db psql -U postgres -d agentprovision -t -A -c "$1" 2>/dev/null | tr -d '[:space:]'; }
jget(){ python3 -c "import sys,json;print(json.load(sys.stdin).get('$1',''))" 2>/dev/null; }

SID="$(db "SELECT id FROM chat_sessions WHERE owner_user_id='$USERID' ORDER BY created_at DESC LIMIT 1;")"
[ -z "$SID" ] && { echo "FATAL: no chat session for $USERID"; exit 1; }
log "session=$SID shell=$SHELL_ID target=$TARGET"

grant() {  # grant <capability> <action> -> approval_id
  curl -s -X POST "$BASE/approval-grants" "${H[@]}" -d \
    "{\"session_id\":\"$SID\",\"shell_id\":\"$SHELL_ID\",\"risk_tier\":\"native_control\",\"capability\":\"$1\",\"max_actions\":2,\"expires_in_seconds\":120,\"target_binding\":{\"bundle_id\":\"$TARGET\",\"action\":\"$2\"}}" | jget approval_id
}
enqueue() {  # enqueue <action> <tool> <approval_id> <args_json>
  curl -s -X POST "$BASE/commands" "${H[@]}" -d \
    "{\"session_id\":\"$SID\",\"shell_id\":\"$SHELL_ID\",\"action\":\"$1\",\"tool_name\":\"$2\",\"approval_id\":\"$3\",\"nonce\":\"wa-${1}-$(date +%s%N)\",\"payload\":{\"args\":$4,\"target\":{\"bundle_id\":\"$TARGET\",\"action\":\"$1\"}}}" | jget desktop_command_id
}
poll() { local s=""; for _ in $(seq 1 15); do s="$(db "SELECT status FROM desktop_commands WHERE id='$1';")"; case "$s" in succeeded|failed|denied|preempted|expired) break;; esac; sleep 2; done; echo "${s:-pending}"; }

log "WhatsApp must be FRONTMOST with the self-chat input focused. Typing in 3s — do not touch the machine."
sleep 3

# 1. type the message
A="$(grant keyboard_control keyboard_type)"
[ -z "$A" ] && { echo "FATAL: grant(keyboard_type) failed — check WhatsApp is allowlisted (effective=tenant∩floor) + flags on"; exit 1; }
CID="$(enqueue keyboard_type desktop_keyboard_type "$A" "{\"text\":\"$MSG\"}")"
log "keyboard_type '$MSG' -> $(poll "$CID")  (id=$CID)"

# 2. send (Enter) — needs the new DMG (PR #865). Old client: this is denied; press Return yourself.
A="$(grant keyboard_control keyboard_key_chord)"
CID="$(enqueue keyboard_key_chord desktop_keyboard_key_chord "$A" "{\"keys\":[\"enter\"]}")"
ST="$(poll "$CID")"
log "keyboard_key_chord [enter] (SEND) -> $ST  (id=$CID)"
[ "$ST" != "succeeded" ] && log "Enter not actuated (older client without the enter chord?). Press Return in WhatsApp to send."
log "Done. Check WhatsApp — the message should be sent."
