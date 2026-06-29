#!/usr/bin/env bash
# tests/run.sh
# Deterministic test runner for the devbox workflow. Discovers every test_*.sh
# in this directory, runs each in its own process, and aggregates results.
#
# Tiers (run in order):
#   test_10_static.sh       syntax + shellcheck of every workflow script
#   test_20_bootstrap.sh    bootstrap.sh is idempotent and plans the right install
#   test_30_devbox_cli.sh   devbox.sh maps each verb to the right docker command
#   test_40_compose.sh      Dockerfile + compose describe the required capabilities
#   test_90_integration.sh  REAL build+run: proves DinD + browser actually work
#
# Tiers 10–40 need no Docker and are fully deterministic. Tier 90 needs a Docker
# daemon; it self-skips (without failing) when one isn't available, unless you
# pass --require-integration.
#
# Usage:
#   ./run.sh                      run everything available
#   ./run.sh --no-integration     skip the heavy build/run tier
#   ./run.sh --require-integration fail (don't skip) if Docker is unavailable
#   ./run.sh test_20_bootstrap    run a single tier by name/prefix
set -uo pipefail

TESTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$TESTS_DIR/.." && pwd)"
DEVBOX_DIR="$REPO_ROOT/devbox"
export TESTS_DIR REPO_ROOT DEVBOX_DIR

RUN_INTEGRATION=1
REQUIRE_INTEGRATION=0
FILTER=""

while [ $# -gt 0 ]; do
  case "$1" in
    --no-integration) RUN_INTEGRATION=0 ;;
    --require-integration) REQUIRE_INTEGRATION=1 ;;
    -h|--help) grep -E '^#( |$)' "$0" | sed -E 's/^# ?//'; exit 0 ;;
    *) FILTER="$1" ;;
  esac
  shift
done
export REQUIRE_INTEGRATION

if [ -t 1 ]; then C_G=$'\033[32m'; C_R=$'\033[31m'; C_B=$'\033[1m'; C_Z=$'\033[0m'
else C_G=''; C_R=''; C_B=''; C_Z=''; fi

total_failed=0
total_files=0
ran_files=0

shopt -s nullglob
for tf in "$TESTS_DIR"/test_*.sh; do
  name="$(basename "$tf" .sh)"
  total_files=$((total_files+1))

  # name filter
  if [ -n "$FILTER" ] && [[ "$name" != *"$FILTER"* ]]; then
    continue
  fi
  # integration toggle
  if [ "$name" = "test_90_integration" ] && [ "$RUN_INTEGRATION" -eq 0 ]; then
    printf '%s== %s (skipped: --no-integration)%s\n' "$C_B" "$name" "$C_Z"
    continue
  fi

  printf '%s== %s ==%s\n' "$C_B" "$name" "$C_Z"
  ran_files=$((ran_files+1))
  if bash "$tf"; then
    printf '%sPASS%s %s\n\n' "$C_G" "$C_Z" "$name"
  else
    printf '%sFAIL%s %s\n\n' "$C_R" "$C_Z" "$name"
    total_failed=$((total_failed+1))
  fi
done

printf '%s=================================%s\n' "$C_B" "$C_Z"
if [ "$total_failed" -eq 0 ]; then
  printf '%sALL GREEN%s — %d/%d test files passed\n' "$C_G" "$C_Z" "$ran_files" "$ran_files"
  exit 0
else
  printf '%s%d/%d test files FAILED%s\n' "$C_R" "$total_failed" "$ran_files" "$C_Z"
  exit 1
fi
