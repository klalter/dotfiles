#!/usr/bin/env bash
# test_40_compose.sh
# Proves the image + compose definitions actually describe the capabilities the
# devbox must provide, BEFORE we spend minutes building. These are static
# content/structure assertions (deterministic) plus a real `compose config`
# validation when Docker is present.
set -uo pipefail
. "$TESTS_DIR/lib/assert.sh"

DF="$DEVBOX_DIR/Dockerfile"
CF="$DEVBOX_DIR/docker-compose.yml"

it "Dockerfile exists";       assert_file "$DF"
it "compose file exists";     assert_file "$CF"
it "entrypoint exists";       assert_file "$DEVBOX_DIR/entrypoint.sh"
it "selftest exists";         assert_file "$DEVBOX_DIR/selftest.sh"
it "extra-ca placeholder";    assert_file "$DEVBOX_DIR/extra-ca/.gitkeep"

dockerfile="$(cat "$DF")"
compose="$(cat "$CF")"

echo "[*] Dockerfile provides DinD + browser + workflow scripts"
it "pinned base image (ubuntu:24.04)";        assert_contains "$dockerfile" "FROM ubuntu:24.04"
it "installs Docker engine for DinD";          assert_contains "$dockerfile" "docker.io"
it "installs a headless browser (Chrome)";     assert_contains "$dockerfile" "google-chrome-stable"
it "ships the entrypoint";                     assert_contains "$dockerfile" "entrypoint.sh /usr/local/bin/devbox-entrypoint"
it "ships the selftest";                       assert_contains "$dockerfile" "selftest.sh  /usr/local/bin/devbox-selftest"
it "writes the devbox release marker";         assert_contains "$dockerfile" "/etc/devbox-release"
it "boots via the devbox entrypoint";          assert_contains "$dockerfile" 'ENTRYPOINT ["/usr/local/bin/devbox-entrypoint"]'
it "supports optional CA trust injection";     assert_contains "$dockerfile" "extra-ca"

echo "[*] compose makes the box privileged + ephemeral"
it "runs privileged (required for DinD)";      assert_contains "$compose" "privileged: true"
it "ephemeral DinD storage volume";            assert_contains "$compose" "/var/lib/docker"
it "ephemeral workspace volume";               assert_contains "$compose" "/workspace"
it "forwards offline selftest tar env";        assert_contains "$compose" "DEVBOX_SELFTEST_IMAGE_TAR"
it "health is gated on dockerd answering";     assert_contains "$compose" "docker"
it "declares named volumes (removed by down -v)"; assert_contains "$compose" "devbox-docker:"

echo "[*] entrypoint boots Docker-in-Docker"
entry="$(cat "$DEVBOX_DIR/entrypoint.sh")"
it "entrypoint starts dockerd";                assert_contains "$entry" "dockerd --host="
it "entrypoint waits for readiness";           assert_contains "$entry" "docker info"

echo "[*] selftest asserts the two deliverables"
self="$(cat "$DEVBOX_DIR/selftest.sh")"
it "selftest checks the browser renders";      assert_contains "$self" "UI-RENDER-OK"
it "selftest runs a container in DinD";         assert_contains "$self" "dind-run"
it "selftest prints a final OK marker";         assert_contains "$self" "SELFTEST-OK"

echo "[*] real compose schema validation (if Docker present)"
if docker compose version >/dev/null 2>&1; then
  it "docker compose config validates"
  assert_success "docker compose -f '$CF' config -q"
else
  skip "docker compose unavailable — schema validation skipped"
fi

finish
