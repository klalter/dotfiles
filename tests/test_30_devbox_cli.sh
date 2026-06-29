#!/usr/bin/env bash
# test_30_devbox_cli.sh
# Proves the devbox.sh CLI maps each verb to exactly the right docker/compose
# command, deterministically, using DEVBOX_DRY_RUN (the CLI prints its plan
# instead of executing). A fake `docker` on PATH makes compose detection and
# require_docker succeed without a real daemon.
set -uo pipefail
. "$TESTS_DIR/lib/assert.sh"

CLI="$DEVBOX_DIR/devbox.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Fake docker: makes `docker compose version` and presence checks succeed.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/docker" <<'EOF'
#!/usr/bin/env bash
case "$1" in
  compose) [ "$2" = "version" ] && { echo "Docker Compose version v9.9-fake"; exit 0; }; exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$WORK/bin/docker"

# helper: run a CLI verb under dry-run with the fake docker, capture output
plan() { PATH="$WORK/bin:$PATH" DEVBOX_DRY_RUN=1 bash "$CLI" "$@" 2>&1; }

COMPOSE_PREFIX="docker compose -p devbox -f $DEVBOX_DIR/docker-compose.yml"

echo "[*] each verb plans the correct command"
it "build -> compose build"
assert_contains "$(plan build)" "DRYRUN $COMPOSE_PREFIX build"

it "up -> compose up -d --build"
assert_contains "$(plan up)" "DRYRUN $COMPOSE_PREFIX up -d --build"

it "down -> compose down -v --remove-orphans (ephemeral)"
assert_contains "$(plan down)" "DRYRUN $COMPOSE_PREFIX down -v --remove-orphans"

it "logs -> compose logs"
assert_contains "$(plan logs)" "DRYRUN $COMPOSE_PREFIX logs"

it "shell -> docker exec -it <container> bash"
assert_contains "$(plan shell)" "DRYRUN docker exec -it devbox-devbox bash"

it "doctor -> docker exec <container> devbox-selftest"
assert_contains "$(plan doctor)" "DRYRUN docker exec devbox-devbox devbox-selftest"

it "status -> docker inspect <container>"
assert_contains "$(plan status)" "DRYRUN docker inspect devbox-devbox"

echo "[*] project/image names are overridable (reproducible naming)"
it "DEVBOX_PROJECT overrides compose project + container name"
out="$(PATH="$WORK/bin:$PATH" DEVBOX_DRY_RUN=1 DEVBOX_PROJECT=ci bash "$CLI" doctor 2>&1)"
assert_contains "$out" "docker exec ci-devbox devbox-selftest"

echo "[*] usage / error handling"
it "no args -> usage, non-zero exit"
assert_fail "PATH=\"$WORK/bin:\$PATH\" bash '$CLI'"
it "unknown verb -> non-zero exit"
assert_fail "PATH=\"$WORK/bin:\$PATH\" bash '$CLI' frobnicate"
it "--help exits 0 and lists verbs"
help="$(bash "$CLI" --help 2>&1)"; assert_contains "$help" "devbox doctor"

finish
