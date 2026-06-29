#!/usr/bin/env bash
# tests/lib/assert.sh
# A tiny, dependency-free test harness (TAP-ish output). Sourced by each test
# file. Keeps a per-file pass/fail count and prints one line per assertion so a
# human (or CI) can see exactly which deliverable was checked.

_TESTS_RUN=0
_TESTS_FAILED=0
_CURRENT="<none>"

# Colours only on a TTY.
if [ -t 1 ]; then _G=$'\033[32m'; _R=$'\033[31m'; _Y=$'\033[33m'; _Z=$'\033[0m'
else _G=''; _R=''; _Y=''; _Z=''; fi

# it "name"  — declare the current assertion's description.
it() { _CURRENT="$1"; }

_pass() { _TESTS_RUN=$((_TESTS_RUN+1)); printf '  %sok%s   %s\n' "$_G" "$_Z" "${1:-$_CURRENT}"; }
_fail() {
  _TESTS_RUN=$((_TESTS_RUN+1)); _TESTS_FAILED=$((_TESTS_FAILED+1))
  printf '  %sFAIL%s %s\n' "$_R" "$_Z" "${1:-$_CURRENT}"
  [ -n "${2:-}" ] && printf '       %s↳ %s%s\n' "$_Y" "$2" "$_Z"
  return 0
}

skip() { printf '  %sskip%s %s\n' "$_Y" "$_Z" "$1"; }

# assert_eq EXPECTED ACTUAL [msg]
assert_eq() {
  if [ "$1" = "$2" ]; then _pass; else _fail "" "expected [$1], got [$2]"; fi
}

# assert_contains HAYSTACK NEEDLE [msg]  — substring match.
assert_contains() {
  case "$1" in
    *"$2"*) _pass ;;
    *) _fail "" "string does not contain: [$2]" ;;
  esac
}

# assert_not_contains HAYSTACK NEEDLE
assert_not_contains() {
  case "$1" in
    *"$2"*) _fail "" "string unexpectedly contains: [$2]" ;;
    *) _pass ;;
  esac
}

# assert_success "cmd ..."  — run via bash -c, expect exit 0.
assert_success() {
  if bash -c "$1" >/dev/null 2>&1; then _pass; else _fail "" "command failed (expected success): $1"; fi
}

# assert_fail "cmd ..."  — run via bash -c, expect non-zero exit.
assert_fail() {
  if bash -c "$1" >/dev/null 2>&1; then _fail "" "command succeeded (expected failure): $1"; else _pass; fi
}

# assert_file FILE
assert_file() {
  if [ -f "$1" ]; then _pass; else _fail "" "file not found: $1"; fi
}

# Print a per-file summary and return non-zero if anything failed.
finish() {
  printf -- '  ---- %d checks, %d failed ----\n' "$_TESTS_RUN" "$_TESTS_FAILED"
  [ "$_TESTS_FAILED" -eq 0 ]
}
