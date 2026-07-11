#!/usr/bin/env bash
# test_10_static.sh
# Every workflow script must be syntactically valid bash, and (when shellcheck
# is available) must pass shellcheck. This is the cheapest deterministic guard
# that the scripts won't blow up at runtime.
set -uo pipefail
. "$TESTS_DIR/lib/assert.sh"

SCRIPTS=(
  "$DEVBOX_DIR/lib/common.sh"
  "$DEVBOX_DIR/bootstrap.sh"
  "$DEVBOX_DIR/devbox.sh"
  "$DEVBOX_DIR/entrypoint.sh"
  "$DEVBOX_DIR/selftest.sh"
  "$REPO_ROOT/install.sh"
  "$REPO_ROOT/shell/bashrc.sh"
  "$REPO_ROOT/scripts/cld"
  "$REPO_ROOT/scripts/cdx"
  "$REPO_ROOT/scripts/merge-skills"
  "$TESTS_DIR/run.sh"
)

echo "[*] bash -n (syntax) on every script"
for s in "${SCRIPTS[@]}"; do
  it "syntax: ${s#$REPO_ROOT/}"
  assert_success "bash -n '$s'"
done

echo "[*] scripts are marked executable"
for s in "$DEVBOX_DIR/bootstrap.sh" "$DEVBOX_DIR/devbox.sh" "$DEVBOX_DIR/entrypoint.sh" "$DEVBOX_DIR/selftest.sh" "$REPO_ROOT/scripts/cld" "$REPO_ROOT/scripts/cdx" "$REPO_ROOT/scripts/merge-skills"; do
  it "executable: ${s#$REPO_ROOT/}"
  if [ -x "$s" ]; then _pass; else _fail "" "not executable: $s"; fi
done

echo "[*] Codespaces startup hooks"
it "devcontainer refreshes skill links every time the Codespace starts"
assert_success "grep -q 'postStartCommand.*merge-skills' '$REPO_ROOT/.devcontainer/devcontainer.json'"

echo "[*] herdr terminal behavior"
it "herdr keeps its clickable mouse UI enabled"
assert_success "grep -Eq '^[[:space:]]*mouse_capture[[:space:]]*=[[:space:]]*true' '$REPO_ROOT/config/herdr.toml'"

echo "[*] agent instructions"
it "global agent instructions tell agents how to refresh skills without rebooting"
assert_success "grep -q 'merge-skills' '$REPO_ROOT/agent/AGENTS.md'"

it "global agent instructions ban AI attribution in commits"
assert_success "grep -q 'Never add AI-assistance attribution' '$REPO_ROOT/agent/AGENTS.md'"

if command -v shellcheck >/dev/null 2>&1; then
  echo "[*] shellcheck (severity: warning)"
  for s in "${SCRIPTS[@]}"; do
    it "shellcheck: ${s#$REPO_ROOT/}"
    # -x: follow sourced files (lib/common.sh). Fail only on warnings+.
    if out="$(shellcheck -x -S warning "$s" 2>&1)"; then
      _pass
    else
      _fail "" "$(printf '%s' "$out" | head -8)"
    fi
  done
else
  skip "shellcheck not installed — install it for full static analysis"
fi

finish
