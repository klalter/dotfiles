#!/usr/bin/env bash
# devbox/selftest.sh  (installed as /usr/local/bin/devbox-selftest)
# Runs INSIDE the devbox container and asserts the two things the box exists to
# provide:
#   1. a headless browser that can render UI
#   2. Docker-in-Docker that can actually run a container
#
# It is deterministic: every check prints a single stable marker on success and
# the script exits non-zero on the first failure. Markers are what the test
# suite greps for, so keep them stable.
set -uo pipefail

pass() { printf 'PASS %s\n' "$1"; }
fail() { printf 'FAIL %s :: %s\n' "$1" "${2:-}"; exit 1; }

# --- 0. environment ---------------------------------------------------------
if [ -r /etc/devbox-release ]; then
  pass "devbox-image"
else
  fail "devbox-image" "not running inside a devbox image (/etc/devbox-release missing)"
fi

# --- 1. headless browser renders UI ----------------------------------------
if ! command -v google-chrome >/dev/null 2>&1; then
  fail "browser-present" "google-chrome not found"
fi
pass "browser-present ($(google-chrome --version 2>/dev/null))"

# Render a trivial page and confirm Chrome produced the expected DOM. Using a
# data: URL keeps this fully offline and deterministic.
RENDER="$(google-chrome --headless=new --no-sandbox --disable-gpu \
            --dump-dom 'data:text/html,<h1>UI-RENDER-OK</h1>' 2>/dev/null || true)"
if printf '%s' "$RENDER" | grep -q 'UI-RENDER-OK'; then
  pass "browser-render"
else
  fail "browser-render" "chrome did not render expected DOM"
fi

# --- 2. Docker-in-Docker can run a container -------------------------------
if ! docker info >/dev/null 2>&1; then
  fail "dind-daemon" "docker daemon not reachable inside container (need --privileged)"
fi
pass "dind-daemon (server $(docker info --format '{{.ServerVersion}}' 2>/dev/null))"

# Run a container. Prefer an image pre-loaded from a tar (offline, deterministic
# in CI/sandboxes); otherwise pull the canonical hello-world.
SELFTEST_IMAGE="hello-world"
if [ -n "${DEVBOX_SELFTEST_IMAGE_TAR:-}" ] && [ -r "${DEVBOX_SELFTEST_IMAGE_TAR}" ]; then
  docker load -i "${DEVBOX_SELFTEST_IMAGE_TAR}" >/dev/null 2>&1 \
    || fail "dind-run" "could not load ${DEVBOX_SELFTEST_IMAGE_TAR}"
fi

RUN_OUT="$(docker run --rm "$SELFTEST_IMAGE" 2>&1 || true)"
if printf '%s' "$RUN_OUT" | grep -qi 'hello from docker'; then
  pass "dind-run"
else
  fail "dind-run" "could not run a container in DinD: $(printf '%s' "$RUN_OUT" | tail -1)"
fi

printf 'SELFTEST-OK\n'
