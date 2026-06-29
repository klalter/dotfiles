#!/usr/bin/env bash
# devbox/entrypoint.sh  (installed as /usr/local/bin/devbox-entrypoint)
# Container entrypoint: start the in-container Docker daemon (Docker-in-Docker)
# and then hand off to CMD. Designed to be safe to run unprivileged (it simply
# skips dockerd if it cannot start) so the container is still usable as a plain
# dev box when --privileged is not available.
set -euo pipefail

log() { printf '[devbox-entrypoint] %s\n' "$*"; }

DOCKER_SOCK="/var/run/docker.sock"

start_dockerd() {
  if [ ! -e /usr/bin/dockerd ] && ! command -v dockerd >/dev/null 2>&1; then
    log "dockerd not installed; skipping Docker-in-Docker"
    return 0
  fi

  # Already running (e.g. socket bind-mounted from host)? Don't start a second.
  if docker info >/dev/null 2>&1; then
    log "docker daemon already reachable; not starting a nested one"
    return 0
  fi

  log "starting in-container dockerd (Docker-in-Docker)..."
  # --host pinned to the unix socket so the bundled CLI (DOCKER_HOST) finds it.
  dockerd --host="unix://${DOCKER_SOCK}" >/var/log/dockerd.log 2>&1 &

  # Wait up to ~30s for the daemon to come up. This bound is what makes the
  # readiness deterministic for the doctor/selftest steps.
  for _ in $(seq 1 30); do
    if docker info >/dev/null 2>&1; then
      log "dockerd ready (server $(docker info --format '{{.ServerVersion}}' 2>/dev/null))"
      return 0
    fi
    sleep 1
  done

  log "WARNING: dockerd did not become ready within 30s; see /var/log/dockerd.log"
  log "(this usually means the container was not started with --privileged)"
  return 0
}

start_dockerd

# Hand off to whatever command was provided (default: sleep infinity).
exec "$@"
