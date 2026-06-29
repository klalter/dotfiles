#!/usr/bin/env bash
# test_20_bootstrap.sh
# Proves bootstrap.sh delivers a *correct, idempotent* host-provisioning plan,
# deterministically and without root/network, by driving it with fake binaries
# on PATH and DEVBOX_DRY_RUN (plan, don't execute).
#
# Deliverables checked:
#   * when Docker is already healthy -> it is a no-op (idempotent skip), twice
#   * --check reflects real readiness (0 when ready, non-0 when not)
#   * when Docker is absent -> it plans the official-repo install for THIS host
set -uo pipefail
. "$TESTS_DIR/lib/assert.sh"

BS="$DEVBOX_DIR/bootstrap.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- build two fake-bin dirs: one with a healthy docker, one with a dead one ---
mk_fakebin() {
  # $1 = dir, $2 = docker-info-exit-code (0 healthy / 1 daemon down)
  local d="$1" info="$2"
  mkdir -p "$d"
  cat > "$d/docker" <<EOF
#!/usr/bin/env bash
case "\$1" in
  info) exit $info ;;
  --version) echo "Docker version 99.0-fake"; exit 0 ;;
  compose) [ "\$2" = "version" ] && { echo "Docker Compose version v9.9-fake"; exit 0; }; exit 0 ;;
  *) exit 0 ;;
esac
EOF
  # A sudo shim that simply runs its arguments with PATH intact. The real sudo
  # resets PATH (secure_path) and would reach the host's real docker, defeating
  # this simulation when the suite runs as a non-root user (e.g. in CI).
  printf '#!/usr/bin/env bash\nexec "$@"\n' > "$d/sudo"
  # Stubs for the install path so nothing real happens even if dry-run is off.
  for tool in apt-get gpg tee systemctl usermod install; do
    printf '#!/usr/bin/env bash\nexit 0\n' > "$d/$tool"
  done
  printf '#!/usr/bin/env bash\necho amd64\n' > "$d/dpkg"
  printf '#!/usr/bin/env bash\nexit 0\n' > "$d/curl"
  chmod +x "$d"/*
}

mk_fakebin "$WORK/healthy" 0
mk_fakebin "$WORK/dead"    1

expected_codename="$( . /etc/os-release 2>/dev/null && echo "${UBUNTU_CODENAME:-${VERSION_CODENAME:-noble}}" )"

# ---------------------------------------------------------------------------
echo "[*] idempotent skip when Docker is already healthy"
out1="$(PATH="$WORK/healthy:$PATH" DEVBOX_DRY_RUN= bash "$BS" 2>&1)"; rc1=$?
it "first run exits 0";            assert_eq 0 "$rc1"
it "first run reports no-op skip"; assert_contains "$out1" "nothing to do"
it "first run makes no DRYRUN/install calls"; assert_not_contains "$out1" "docker-ce"

out2="$(PATH="$WORK/healthy:$PATH" bash "$BS" 2>&1)"; rc2=$?
it "second run also exits 0 (idempotent)"; assert_eq 0 "$rc2"
it "second run identical to first";        assert_eq "$out1" "$out2"

# ---------------------------------------------------------------------------
echo "[*] --check reflects real readiness"
it "--check exits 0 when docker healthy"
assert_success "PATH=\"$WORK/healthy:\$PATH\" bash '$BS' --check"
it "--check exits non-zero when daemon dead"
assert_fail "PATH=\"$WORK/dead:\$PATH\" bash '$BS' --check"

# ---------------------------------------------------------------------------
echo "[*] plans the official-repo install when Docker is absent"
plan="$(PATH="$WORK/dead:$PATH" DEVBOX_DRY_RUN=1 bash "$BS" 2>&1)"; prc=$?
it "dry-run install plan exits 0";              assert_eq 0 "$prc"
it "installs the docker-ce package set";        assert_contains "$plan" "docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin"
it "adds Docker's official apt repo";           assert_contains "$plan" "download.docker.com/linux/ubuntu"
it "pins the repo to THIS host's codename";     assert_contains "$plan" "ubuntu ${expected_codename} stable"
it "fetches and dearmors the signing key";      assert_contains "$plan" "download.docker.com/linux/ubuntu/gpg"
it "enables the docker service";                assert_contains "$plan" "systemctl enable --now docker"
it "dry-run makes NO real apt-get execution";   assert_contains "$plan" "DRYRUN"

# ---------------------------------------------------------------------------
echo "[*] --help works and documents usage"
it "--help exits 0";            assert_success "bash '$BS' --help"
it "--help mentions idempotent" ; help="$(bash "$BS" --help 2>&1)"; assert_contains "$help" "Idempotent"

finish
