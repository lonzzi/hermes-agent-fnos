#!/bin/bash
set -euo pipefail
fixture=$(mktemp -d)
export TRIM_PKGETC="$fixture/etc" TRIM_PKGVAR="$fixture/var" TRIM_TEMP_LOGFILE="$fixture/error"
export TRIM_SERVICE_PORT=19119 wizard_username=admin
export wizard_password=$(openssl rand -hex 24)
export HERMES_DASHBOARD_BASIC_AUTH_PASSWORD="$wizard_password"
compose=(docker compose -f .build/package/app/docker/docker-compose.yaml)
cleanup() {
  "${compose[@]}" logs --no-color > smoke.log 2>&1 || true
  "${compose[@]}" down --volumes >/dev/null 2>&1 || true
  sudo rm -rf "$fixture"
}
trap cleanup EXIT
bash .build/package/cmd/install_init
# fnOS validates Docker resources before its post-install callback.
"${compose[@]}" config --quiet
bash .build/package/cmd/install_callback
"${compose[@]}" config --quiet
"${compose[@]}" pull
"${compose[@]}" up -d
for attempt in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:19119/api/auth/providers -o /dev/null; then
    python3 scripts/check_auth.py
    docker exec hermes-agent-fnos hermes --version
    for health_attempt in $(seq 1 30); do
      if bash .build/package/cmd/main status; then exit 0; fi
      sleep 2
    done
    echo 'Package status check did not become healthy' >&2
    exit 1
  fi
  sleep 2
done
echo 'Dashboard failed to start' >&2
exit 1
