#!/usr/bin/env bash
# test_90_integration.sh
# The proof-of-the-pudding tier: actually BUILD the image and RUN the box, then
# assert the two deliverables really work:
#   * the headless browser renders UI  (PASS browser-render)
#   * Docker-in-Docker runs a container (PASS dind-run)
#
# It exercises the real workflow scripts: devbox build -> up -> status -> doctor
# -> down. To stay deterministic and offline-capable, the DinD check runs a
# hello-world image that the HOST saves to a tar and we load inside the box
# (no registry access required, so it passes on a clean VM and in CI alike).
#
# Needs a working Docker daemon. Without one it SKIPS (exit 0) unless the runner
# was invoked with --require-integration (REQUIRE_INTEGRATION=1).
set -uo pipefail
. "$TESTS_DIR/lib/assert.sh"

CLI="$DEVBOX_DIR/devbox.sh"
PROJECT="devboxtest"               # isolated project so we never touch a real box
CONTAINER="${PROJECT}-devbox"
export DEVBOX_PROJECT="$PROJECT"
export DEVBOX_IMAGE="devbox:itest"

# --- preflight: is Docker usable? ------------------------------------------
if ! docker info >/dev/null 2>&1; then
  if [ "${REQUIRE_INTEGRATION:-0}" = "1" ]; then
    it "docker daemon available"; _fail "" "no Docker daemon and --require-integration was set"
    finish; exit $?
  fi
  skip "no Docker daemon reachable — integration build/run skipped"
  skip "run on a host with Docker (or after ./devbox/bootstrap.sh) to exercise this tier"
  finish; exit $?
fi

WORK="$(mktemp -d)"
INJECTED_CA=""
cleanup() {
  bash "$CLI" down >/dev/null 2>&1 || true
  docker rmi "$DEVBOX_IMAGE" >/dev/null 2>&1 || true
  [ -n "$INJECTED_CA" ] && rm -f "$INJECTED_CA"
  rm -rf "$WORK"
}
trap cleanup EXIT

# --- sandbox accommodation: trust a TLS-intercepting proxy CA if present ----
# On a normal VM this block does nothing. In a proxied sandbox it lets the image
# build reach https://dl.google.com. Cleaned up afterwards either way.
for ca in /root/.ccr/ca-bundle.crt; do
  if [ -r "$ca" ]; then
    INJECTED_CA="$DEVBOX_DIR/extra-ca/sandbox-proxy.crt"
    cp "$ca" "$INJECTED_CA"
    echo "[*] injected proxy CA for sandbox build: $INJECTED_CA"
    break
  fi
done

# --- prepare an offline image for the DinD run check -----------------------
echo "[*] preparing offline hello-world image (host side)"
docker pull -q hello-world >/dev/null 2>&1 || true
if ! docker image inspect hello-world >/dev/null 2>&1; then
  skip "could not obtain hello-world image on host — DinD run will fall back to pull"
fi
docker save hello-world -o "$WORK/hello.tar" 2>/dev/null || true

# ---------------------------------------------------------------------------
echo "[*] devbox build"
it "image builds successfully"
if bash "$CLI" build >/tmp/itest-build.log 2>&1; then _pass; else _fail "" "$(tail -15 /tmp/itest-build.log)"; fi

echo "[*] devbox up"
it "box starts"
if bash "$CLI" up >/tmp/itest-up.log 2>&1; then _pass; else _fail "" "$(tail -15 /tmp/itest-up.log)"; fi

echo "[*] wait for in-container dockerd to become healthy"
healthy=0
for i in $(seq 1 40); do
  st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER" 2>/dev/null || echo none)"
  if [ "$st" = "healthy" ]; then healthy=1; break; fi
  # If there's no healthcheck status yet but dockerd answers, that's good enough.
  if docker exec "$CONTAINER" docker info >/dev/null 2>&1; then healthy=1; break; fi
  sleep 1
done
it "DinD daemon becomes healthy inside the box"
if [ "$healthy" = "1" ]; then _pass; else _fail "" "dockerd not healthy after 40s: $(docker exec "$CONTAINER" tail -5 /var/log/dockerd.log 2>&1)"; fi

echo "[*] devbox status reports running"
it "status shows running"
assert_contains "$(bash "$CLI" status 2>&1)" "running"

# --- make the offline image available inside the box -----------------------
if [ -f "$WORK/hello.tar" ]; then
  docker cp "$WORK/hello.tar" "$CONTAINER:/tmp/hello.tar" >/dev/null 2>&1 || true
  export DEVBOX_SELFTEST_IMAGE_TAR="/tmp/hello.tar"
fi

echo "[*] devbox doctor (runs the in-container selftest)"
doc="$(bash "$CLI" doctor 2>&1)"; drc=$?
echo "$doc" | sed 's/^/    | /'
it "doctor exits 0";                 assert_eq 0 "$drc"
it "browser renders UI";             assert_contains "$doc" "PASS browser-render"
it "browser binary present";         assert_contains "$doc" "PASS browser-present"
it "DinD daemon reachable";          assert_contains "$doc" "PASS dind-daemon"
it "DinD runs a container";          assert_contains "$doc" "PASS dind-run"
it "selftest overall OK";            assert_contains "$doc" "SELFTEST-OK"

echo "[*] devbox down (full teardown)"
it "teardown succeeds"
assert_success "DEVBOX_PROJECT='$PROJECT' bash '$CLI' down"
it "container is gone after down"
assert_fail "docker inspect '$CONTAINER'"

finish
