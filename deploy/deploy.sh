#!/usr/bin/env bash
# Usage: deploy/deploy.sh <image:tag>
# Pulls the image, restarts the stack, waits for /healthz, and rolls back to the
# previous image if the new one never becomes healthy.
set -euo pipefail

NEW_IMAGE="$1"
PTK_DIR="${PTK_DIR:-/opt/ptk}"
HERE="$(cd "$(dirname "$0")" && pwd)"
cp "$HERE/docker-compose.prod.yml" "$PTK_DIR/docker-compose.yml"
cd "$PTK_DIR"

[ -f .env ] || { echo "missing $PTK_DIR/.env" >&2; exit 1; }
PROFILE="$(grep -E '^PTK_PROFILE=' .env | cut -d= -f2- || true)"   # tunnel | https | empty
compose() { API_IMAGE="$1" docker compose ${PROFILE:+--profile "$PROFILE"} "${@:2}"; }

PREV_IMAGE="$(cat current_image 2>/dev/null || true)"

healthy() {
  for _ in $(seq 1 60); do
    curl -fsS http://127.0.0.1:8000/healthz >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

compose "$NEW_IMAGE" pull api
compose "$NEW_IMAGE" up -d --remove-orphans

if healthy; then
  echo "$NEW_IMAGE" > current_image
  docker image prune -f >/dev/null
  echo "deployed $NEW_IMAGE"
  exit 0
fi

echo "new image unhealthy; recent logs:" >&2
compose "$NEW_IMAGE" logs --tail 80 api >&2 || true
if [ -n "$PREV_IMAGE" ]; then
  echo "rolling back to $PREV_IMAGE" >&2
  compose "$PREV_IMAGE" up -d api
  healthy && echo "rollback ok" >&2
fi
exit 1
