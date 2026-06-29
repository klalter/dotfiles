#!/usr/bin/env bash
# devbox/bootstrap.sh
# Provision a FRESH Ubuntu host (any cloud provider, or a local VM) with
# everything the devbox needs: Docker Engine + the compose v2 plugin.
#
# Design goals:
#   * Idempotent  — running it twice is a no-op the second time.
#   * Replicable  — uses Docker's official apt repository, pinned to the host's
#                   own Ubuntu codename, so the result is the same everywhere.
#   * Testable    — every state-changing command goes through run(), which honours
#                   DEVBOX_DRY_RUN=1 (print, don't execute). That makes the script
#                   deterministically testable without root or network.
#
# Usage:
#   sudo ./bootstrap.sh            # install Docker if missing
#   ./bootstrap.sh --check         # report status, change nothing (exit 0 if ready)
#   DEVBOX_DRY_RUN=1 ./bootstrap.sh  # print the plan, change nothing
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$DIR/lib/common.sh"

DRY_RUN="${DEVBOX_DRY_RUN:-}"
MODE="install"   # install | check

# run CMD...  — execute, or just print under dry-run.
run() {
  if [ -n "$DRY_RUN" ]; then
    printf 'DRYRUN %s\n' "$*"
    return 0
  fi
  debug "exec: $*"
  "$@"
}

# Prefix privileged commands with sudo only when we are not already root and
# sudo exists. Keeps the script usable both as root (cloud-init) and as a user.
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if have sudo; then SUDO="sudo"; fi
fi
maybe_sudo() {
  if [ -n "$SUDO" ]; then run "$SUDO" "$@"; else run "$@"; fi
}

docker_ready() {
  # "Ready" means the CLI exists AND the daemon answers. On a host where the
  # current user is not yet in the docker group, the daemon check may need sudo.
  have docker || return 1
  docker info >/dev/null 2>&1 && return 0
  [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1 && return 0
  return 1
}

install_docker() {
  log "installing Docker Engine from the official apt repository"

  # Resolve the Ubuntu codename so the repo line matches this host exactly.
  local codename
  codename="$( . /etc/os-release 2>/dev/null && echo "${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}" )"
  [ -n "$codename" ] || die "could not determine Ubuntu codename from /etc/os-release"
  log "target distribution: ubuntu/${codename}"

  maybe_sudo install -m 0755 -d /etc/apt/keyrings
  run bash -c "curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      | ${SUDO} gpg --dearmor -o /etc/apt/keyrings/docker.gpg"
  maybe_sudo chmod a+r /etc/apt/keyrings/docker.gpg

  local arch repo_line
  arch="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
  repo_line="deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${codename} stable"
  run bash -c "echo '${repo_line}' | ${SUDO} tee /etc/apt/sources.list.d/docker.list >/dev/null"

  maybe_sudo apt-get update
  maybe_sudo apt-get install -y \
      docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  maybe_sudo systemctl enable --now docker || warn "could not enable docker via systemctl (fine on hosts without systemd)"

  # Let the invoking (non-root) user run docker without sudo next login.
  if [ "$(id -u)" -ne 0 ] && [ -n "${SUDO_USER:-${USER:-}}" ]; then
    maybe_sudo usermod -aG docker "${SUDO_USER:-$USER}" || true
    warn "added ${SUDO_USER:-$USER} to the 'docker' group — log out/in (or 'newgrp docker') to use docker without sudo"
  fi
}

print_status() {
  if docker_ready; then
    ok "Docker is installed and the daemon is reachable ($(docker --version 2>/dev/null))"
    local cc; cc="$(compose_cmd 2>/dev/null || true)"
    if [ -n "$cc" ]; then ok "compose available: ${cc} ($($cc version 2>/dev/null | head -1))"
    else warn "docker compose plugin not found"; fi
    return 0
  fi
  warn "Docker is not ready on this host"
  return 1
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --check) MODE="check" ;;
      --dry-run) DRY_RUN=1 ;;
      -h|--help)
        grep -E '^#( |$)' "$0" | sed -E 's/^# ?//'; exit 0 ;;
      *) die "unknown argument: $1 (try --help)" ;;
    esac
    shift
  done

  have apt-get || die "this bootstrap targets Ubuntu/Debian (apt-get not found)"

  if [ "$MODE" = "check" ]; then
    print_status
    exit $?
  fi

  if docker_ready; then
    ok "Docker already present and healthy — nothing to do (idempotent skip)"
    print_status || true
    exit 0
  fi

  install_docker

  if [ -n "$DRY_RUN" ]; then
    ok "dry-run complete (no changes made)"
    exit 0
  fi

  if docker_ready; then
    ok "bootstrap complete — Docker is ready"
  else
    warn "bootstrap ran but the daemon is not reachable yet"
    warn "you may need to re-login for group changes, or start the daemon manually"
  fi
}

main "$@"
