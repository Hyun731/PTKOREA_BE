#!/usr/bin/env bash
# Usage: deploy/deploy.sh <image:tag>
# Pulls the image, restarts the stack, waits for /healthz, and rolls back to the
# previous image if the new one never becomes healthy.
set -euo pipefail

NEW_IMAGE="$1"
PTK_DIR="${PTK_DIR:-/opt/ptk}"
HERE="$(cd "$(dirname "$0")" && pwd)"
cp "$HERE/docker-compose.prod.yml" "$PTK_DIR/docker-compose.yml"
mkdir -p "$PTK_DIR/monitoring"
cp -R "$HERE/monitoring/." "$PTK_DIR/monitoring/"
cd "$PTK_DIR"

[ -f .env ] || { echo "missing $PTK_DIR/.env" >&2; exit 1; }
PROFILE_LIST="$(grep -E '^PTK_PROFILES=' .env | tail -n1 | cut -d= -f2- || true)"
if [ -z "$PROFILE_LIST" ]; then
  LEGACY_PROFILE="$(grep -E '^PTK_PROFILE=' .env | tail -n1 | cut -d= -f2- || true)"
  PROFILE_LIST="${LEGACY_PROFILE:+$LEGACY_PROFILE,}monitoring"
fi
PROFILE_ARGS=()
MONITORING=0
IFS=',' read -ra PROFILES <<< "$PROFILE_LIST"
for profile in "${PROFILES[@]}"; do
  profile="${profile//[[:space:]]/}"
  [ -n "$profile" ] || continue
  PROFILE_ARGS+=(--profile "$profile")
  [ "$profile" = "monitoring" ] && MONITORING=1
done
compose() {
  local image="$1"
  shift
  API_IMAGE="$image" docker compose "${PROFILE_ARGS[@]}" "$@"
}

if [ "$MONITORING" = "1" ]; then
  BACKEND_TOKEN_VALUE="$(grep -E '^BACKEND_TOKEN=' .env | tail -n1 | cut -d= -f2- || true)"
  BACKEND_TOKEN_VALUE="${BACKEND_TOKEN_VALUE#\"}"
  BACKEND_TOKEN_VALUE="${BACKEND_TOKEN_VALUE%\"}"
  GRAFANA_PASSWORD="$(grep -E '^GRAFANA_ADMIN_PASSWORD=' .env | tail -n1 | cut -d= -f2- || true)"
  [ -n "$BACKEND_TOKEN_VALUE" ] || { echo "monitoring requires BACKEND_TOKEN" >&2; exit 1; }
  if [ -z "$GRAFANA_PASSWORD" ]; then
    GRAFANA_PASSWORD="$(openssl rand -hex 24)"
    printf '\nGRAFANA_ADMIN_PASSWORD=%s\n' "$GRAFANA_PASSWORD" >> .env
    echo "generated GRAFANA_ADMIN_PASSWORD in $PTK_DIR/.env"
  fi
  umask 077
  mkdir -p monitoring/secrets
  printf '%s' "$BACKEND_TOKEN_VALUE" > monitoring/secrets/backend_token
fi

PREV_IMAGE="$(cat current_image 2>/dev/null || true)"

healthy() {
  for _ in $(seq 1 60); do
    curl -fsS http://127.0.0.1:8000/health/ready >/dev/null 2>&1 && return 0
    sleep 3
  done
  return 1
}

monitoring_healthy() {
  [ "$MONITORING" = "0" ] && return 0
  for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:9090/-/ready >/dev/null 2>&1 \
      && curl -fsS http://127.0.0.1:3001/api/health >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

compose "$NEW_IMAGE" pull api
compose "$NEW_IMAGE" up -d --remove-orphans

if healthy && monitoring_healthy; then
  echo "$NEW_IMAGE" > current_image
  docker image prune -f >/dev/null
  echo "deployed $NEW_IMAGE"
  exit 0
fi

echo "new image unhealthy; recent logs:" >&2
compose "$NEW_IMAGE" logs --tail 80 api >&2 || true
if [ "$MONITORING" = "1" ]; then
  compose "$NEW_IMAGE" logs --tail 80 prometheus grafana >&2 || true
fi
if [ -n "$PREV_IMAGE" ]; then
  echo "rolling back to $PREV_IMAGE" >&2
  compose "$PREV_IMAGE" up -d api
  healthy && echo "rollback ok" >&2
fi
exit 1
