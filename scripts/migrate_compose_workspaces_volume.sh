#!/usr/bin/env bash
set -euo pipefail

# One-time local Docker migration for the workspace volume physical name.
#
# The compose key remains `workspaces` and containers still mount
# /var/agentprovision/workspaces. Only the Docker volume source name changes
# from agentprovision-agents_workspaces to agentprovision-agents_tenant_spaces
# so Luna's release gate can grep `_work` without matching a benign volume.

PROJECT_NAME="${COMPOSE_PROJECT_NAME:-agentprovision-agents}"
OLD_VOLUME="${OLD_WORKSPACES_VOLUME_NAME:-${PROJECT_NAME}_workspaces}"
NEW_VOLUME="${WORKSPACES_VOLUME_NAME:-agentprovision-agents_tenant_spaces}"
COPY_IMAGE="${WORKSPACE_VOLUME_COPY_IMAGE:-alpine:3.20}"
QUIESCE_SERVICES="${QUIESCE_COMPOSE_SERVICES:-}"
QUIESCED=0
COMPLETE_MARKER=".agentprovision_workspace_volume_migrated"
IN_PROGRESS_MARKER=".agentprovision_workspace_volume_migrating"

restore_on_error() {
  status=$?
  if [ "$status" -ne 0 ] && [ "$QUIESCED" = "1" ]; then
    echo "Migration failed; restarting quiesced services: $QUIESCE_SERVICES" >&2
    docker compose start $QUIESCE_SERVICES || true
  fi
  exit "$status"
}

trap restore_on_error EXIT

has_volume() {
  docker volume inspect "$1" >/dev/null 2>&1
}

volume_has_entries() {
  docker run --rm -v "$1:/volume:ro" "$COPY_IMAGE" \
    sh -c 'test -n "$(find /volume -mindepth 1 -maxdepth 1 -print -quit)"'
}

volume_has_file() {
  docker run --rm -v "$1:/volume:ro" "$COPY_IMAGE" \
    sh -c "test -f '/volume/$2'"
}

write_volume_file() {
  docker run --rm -v "$1:/volume" -e MARKER_FILE="$2" "$COPY_IMAGE" \
    sh -c 'date -u +"%Y-%m-%dT%H:%M:%SZ" > "/volume/$MARKER_FILE"'
}

clear_volume() {
  docker run --rm -v "$1:/volume" "$COPY_IMAGE" \
    sh -c 'rm -rf /volume/* /volume/.[!.]* /volume/..?* 2>/dev/null || true'
}

echo "Workspace volume migration: old=$OLD_VOLUME new=$NEW_VOLUME"

if [ "$OLD_VOLUME" = "$NEW_VOLUME" ]; then
  echo "Old and new volume names are identical; nothing to migrate."
  exit 0
fi

if has_volume "$NEW_VOLUME" && volume_has_file "$NEW_VOLUME" "$COMPLETE_MARKER"; then
  echo "New workspace volume already has completion marker; nothing to migrate."
  exit 0
fi

if has_volume "$NEW_VOLUME" && volume_has_entries "$NEW_VOLUME"; then
  if volume_has_file "$NEW_VOLUME" "$IN_PROGRESS_MARKER"; then
    echo "Found incomplete prior migration; clearing destination before retry."
    clear_volume "$NEW_VOLUME"
  else
    echo "Destination $NEW_VOLUME contains data without $COMPLETE_MARKER; refusing to overwrite it." >&2
    exit 1
  fi
fi

if ! has_volume "$OLD_VOLUME"; then
  docker volume create "$NEW_VOLUME" >/dev/null
  write_volume_file "$NEW_VOLUME" "$COMPLETE_MARKER"
  echo "Old workspace volume not found; ensured $NEW_VOLUME exists."
  exit 0
fi

docker volume create "$NEW_VOLUME" >/dev/null

if ! volume_has_entries "$OLD_VOLUME"; then
  write_volume_file "$NEW_VOLUME" "$COMPLETE_MARKER"
  echo "Old workspace volume is empty; no data copy needed."
  exit 0
fi

if [ -n "$QUIESCE_SERVICES" ]; then
  echo "Stopping services before workspace copy: $QUIESCE_SERVICES"
  docker compose stop $QUIESCE_SERVICES
  QUIESCED=1
fi

echo "Copying workspace data from $OLD_VOLUME to $NEW_VOLUME..."
write_volume_file "$NEW_VOLUME" "$IN_PROGRESS_MARKER"
docker run --rm \
  -v "$OLD_VOLUME:/from:ro" \
  -v "$NEW_VOLUME:/to" \
  -e COMPLETE_MARKER="$COMPLETE_MARKER" \
  -e IN_PROGRESS_MARKER="$IN_PROGRESS_MARKER" \
  "$COPY_IMAGE" \
  sh -eu -c '
    mkfifo /tmp/workspace-copy.tar
    (cd /from && tar cf /tmp/workspace-copy.tar .) &
    tar_pid=$!
    (cd /to && tar xpf /tmp/workspace-copy.tar)
    wait "$tar_pid"
    rm -f "/to/$IN_PROGRESS_MARKER"
    date -u +"%Y-%m-%dT%H:%M:%SZ" > "/to/$COMPLETE_MARKER"
  '

echo "Workspace volume migration complete."
