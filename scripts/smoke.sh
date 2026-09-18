#!/bin/bash
set -euo pipefail
: "${HERMES_IMAGE:?Missing image}"
password=$(openssl rand -hex 24)
export HERMES_DASHBOARD_BASIC_AUTH_PASSWORD="$password"
docker pull "$HERMES_IMAGE"
trap 'docker logs hermes-fnos-smoke > smoke.log 2>&1 || true; docker rm -fv hermes-fnos-smoke >/dev/null 2>&1 || true' EXIT
docker run -d --name hermes-fnos-smoke -p 127.0.0.1:19119:9119 \
  -e HERMES_DASHBOARD=true -e HERMES_DASHBOARD_HOST=0.0.0.0 \
  -e HERMES_DASHBOARD_BASIC_AUTH_USERNAME=admin \
  -e HERMES_DASHBOARD_BASIC_AUTH_PASSWORD \
  "$HERMES_IMAGE" sleep infinity
for attempt in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:19119/api/auth/providers -o /dev/null; then
    python3 scripts/check_auth.py
    docker exec hermes-fnos-smoke hermes --version
    exit 0
  fi
  sleep 2
done
echo 'Dashboard failed to start' >&2
exit 1
