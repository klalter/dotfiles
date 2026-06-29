#!/usr/bin/env bash
# devbox/devbox.sh
# Lifecycle CLI for the ephemeral dev container. Thin, predictable wrapper around
# `docker compose` so the whole workflow is a handful of memorable verbs:
#
#   devbox build     build the image
#   devbox up        build (if needed) and start the box in the background
#   devbox shell     open an interactive shell inside the running box
#   devbox doctor    run the in-container selftest (DinD + browser) and report
#   devbox status    show whether the box is up and healthy
#   devbox logs      tail the box's entrypoint/daemon logs
#   devbox down      stop and remove the box AND its volumes (fully ephemeral)
#
# Every state-changing docker command goes through run() so DEVBOX_DRY_RUN=1
# turns the CLI into a deterministic planner for the test suite.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$DIR/lib/common.sh"

DRY_RUN="${DEVBOX_DRY_RUN:-}"

run() {
  if [ -n "$DRY_RUN" ]; then printf 'DRYRUN %s\n' "$*"; return 0; fi
  debug "exec: $*"
  "$@"
}

# Resolve compose into an array so it works whether it's "docker compose" or
# "docker-compose", and always point it at our project + compose file.
_compose() {
  local base; base="$(compose_cmd)" || die "docker compose not found — run ./bootstrap.sh first"
  # shellcheck disable=SC2206
  local parts=( $base )
  run "${parts[@]}" -p "$DEVBOX_PROJECT" -f "$DIR/docker-compose.yml" "$@"
}

container_name() { echo "${DEVBOX_PROJECT}-${DEVBOX_SERVICE}"; }

require_docker() {
  have docker || die "docker not installed — run ./bootstrap.sh on this host first"
}

cmd_build()  { require_docker; log "building ${DEVBOX_IMAGE}"; _compose build "$@"; ok "image built"; }

cmd_up() {
  require_docker
  log "starting ephemeral devbox (project: ${DEVBOX_PROJECT})"
  _compose up -d --build "$@"
  ok "devbox is up — try 'devbox doctor' or 'devbox shell'"
}

cmd_shell() {
  require_docker
  log "attaching shell to $(container_name)"
  # No run() wrapper here: an interactive shell shouldn't be dry-run swallowed,
  # but we still honour dry-run by printing the command.
  if [ -n "$DRY_RUN" ]; then printf 'DRYRUN docker exec -it %s bash\n' "$(container_name)"; return 0; fi
  docker exec -it "$(container_name)" bash -l
}

cmd_doctor() {
  require_docker
  log "running in-container selftest (DinD + browser)"
  # Forward an optional offline image tar so the DinD check works without
  # registry access (air-gapped hosts / CI). The path is resolved inside the
  # container, so copy/mount the tar there first.
  local exec_env=()
  [ -n "${DEVBOX_SELFTEST_IMAGE_TAR:-}" ] && exec_env=(-e "DEVBOX_SELFTEST_IMAGE_TAR=${DEVBOX_SELFTEST_IMAGE_TAR}")
  if [ -n "$DRY_RUN" ]; then printf 'DRYRUN docker exec %s devbox-selftest\n' "$(container_name)"; return 0; fi
  if docker exec "${exec_env[@]}" "$(container_name)" devbox-selftest; then
    ok "doctor: all checks passed"
  else
    die "doctor: selftest failed (see output above)"
  fi
}

cmd_status() {
  require_docker
  local name; name="$(container_name)"
  if [ -n "$DRY_RUN" ]; then printf 'DRYRUN docker inspect %s\n' "$name"; return 0; fi
  if ! docker inspect "$name" >/dev/null 2>&1; then
    warn "devbox is not running (no container named ${name})"; return 1
  fi
  local state health
  state="$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || echo unknown)"
  health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}n/a{{end}}' "$name" 2>/dev/null || echo n/a)"
  log "container: ${name}"
  log "state:     ${state}"
  log "health:    ${health}"
  [ "$state" = "running" ]
}

cmd_logs()  { require_docker; _compose logs "$@"; }

cmd_down() {
  require_docker
  log "tearing down devbox and removing volumes (ephemeral)"
  _compose down -v --remove-orphans "$@"
  ok "devbox removed — host is clean"
}

usage() {
  grep -E '^#( |$)' "$0" | sed -E 's/^# ?//'
}

main() {
  [ $# -ge 1 ] || { usage; exit 1; }
  local sub="$1"; shift
  case "$sub" in
    build)  cmd_build  "$@" ;;
    up)     cmd_up     "$@" ;;
    shell)  cmd_shell  "$@" ;;
    doctor) cmd_doctor "$@" ;;
    status) cmd_status "$@" ;;
    logs)   cmd_logs   "$@" ;;
    down)   cmd_down   "$@" ;;
    -h|--help|help) usage ;;
    *) err "unknown command: $sub"; usage; exit 1 ;;
  esac
}

main "$@"
