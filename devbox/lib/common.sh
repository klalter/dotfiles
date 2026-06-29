#!/usr/bin/env bash
# devbox/lib/common.sh
# Shared helpers for the devbox workflow scripts. Sourced, never executed.
# Keep this file dependency-free (POSIX-ish bash) so it works on a stock Ubuntu host.

# Guard against double-sourcing.
[ -n "${_DEVBOX_COMMON_SOURCED:-}" ] && return 0
_DEVBOX_COMMON_SOURCED=1

# ---- configuration (overridable via environment) ---------------------------
# These defaults are deliberately stable so the workflow is reproducible.
DEVBOX_IMAGE="${DEVBOX_IMAGE:-devbox:latest}"
DEVBOX_PROJECT="${DEVBOX_PROJECT:-devbox}"      # docker compose project name
DEVBOX_SERVICE="${DEVBOX_SERVICE:-devbox}"      # service name inside compose

# Absolute path to the devbox/ directory, regardless of caller's CWD.
# BASH_SOURCE[0] is this file (devbox/lib/common.sh); its parent's parent is devbox/.
DEVBOX_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DEVBOX_DIR

# ---- logging ---------------------------------------------------------------
# Colour only when stdout is a TTY, so logs stay clean in CI and pipes.
if [ -t 1 ]; then
  _C_BLUE=$'\033[34m'; _C_GREEN=$'\033[32m'; _C_YELLOW=$'\033[33m'
  _C_RED=$'\033[31m'; _C_DIM=$'\033[2m'; _C_RST=$'\033[0m'
else
  _C_BLUE=''; _C_GREEN=''; _C_YELLOW=''; _C_RED=''; _C_DIM=''; _C_RST=''
fi

log()   { printf '%s[devbox]%s %s\n' "$_C_BLUE"  "$_C_RST" "$*"; }
ok()    { printf '%s[ ok ]%s %s\n'  "$_C_GREEN" "$_C_RST" "$*"; }
warn()  { printf '%s[warn]%s %s\n'  "$_C_YELLOW" "$_C_RST" "$*" >&2; }
err()   { printf '%s[fail]%s %s\n'  "$_C_RED"   "$_C_RST" "$*" >&2; }
debug() { [ -n "${DEVBOX_DEBUG:-}" ] && printf '%s[dbg ]%s %s\n' "$_C_DIM" "$_C_RST" "$*" >&2; return 0; }

die()   { err "$*"; exit 1; }

# ---- small utilities -------------------------------------------------------
have() { command -v "$1" >/dev/null 2>&1; }

# Resolve the docker compose entrypoint: prefer the v2 plugin, fall back to
# the legacy docker-compose binary. Echoes the command to use.
compose_cmd() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
  elif have docker-compose; then
    echo "docker-compose"
  else
    return 1
  fi
}
