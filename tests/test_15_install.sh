#!/usr/bin/env bash
# test_15_install.sh
# install.sh must be idempotent and wire up the Codespaces environment
# correctly: one shell hook in .bashrc, agent skills/memory symlinked for BOTH
# Claude Code and Codex, and shell/bashrc.sh must actually put the personal
# scripts on PATH. Runs against a throwaway HOME with network installs off, so
# it is fully deterministic.
set -uo pipefail
. "$TESTS_DIR/lib/assert.sh"

SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

run_install() {
  HOME="$SANDBOX" DOTFILES_NO_NETWORK=1 bash "$REPO_ROOT/install.sh"
}

echo "[*] install.sh on a fresh HOME"
it "install.sh exits 0 on a fresh HOME (no network)"
if out="$(run_install 2>&1)"; then _pass; else _fail "" "$(printf '%s' "$out" | tail -5)"; fi

it "HOME/.bashrc gained the shell hook"
assert_success "grep -qF 'shell/bashrc.sh' '$SANDBOX/.bashrc'"

it "HOME/.claude/skills -> repo skills/"
assert_eq "$REPO_ROOT/skills" "$(readlink "$SANDBOX/.claude/skills" 2>/dev/null)"

it "HOME/.codex/skills -> repo skills/"
assert_eq "$REPO_ROOT/skills" "$(readlink "$SANDBOX/.codex/skills" 2>/dev/null)"

it "HOME/.claude/CLAUDE.md -> repo agent/CLAUDE.md"
assert_eq "$REPO_ROOT/agent/CLAUDE.md" "$(readlink "$SANDBOX/.claude/CLAUDE.md" 2>/dev/null)"

it "HOME/.codex/AGENTS.md -> repo agent/AGENTS.md"
assert_eq "$REPO_ROOT/agent/AGENTS.md" "$(readlink "$SANDBOX/.codex/AGENTS.md" 2>/dev/null)"

it "HOME/.config/starship.toml -> repo config/starship.toml"
assert_eq "$REPO_ROOT/config/starship.toml" "$(readlink "$SANDBOX/.config/starship.toml" 2>/dev/null)"

it "skills folder resolves through the symlink"
assert_file "$SANDBOX/.claude/skills/example-skill/SKILL.md"

echo "[*] install.sh is idempotent"
it "second run exits 0"
assert_success "HOME='$SANDBOX' DOTFILES_NO_NETWORK=1 bash '$REPO_ROOT/install.sh'"

it "shell hook appears exactly once in .bashrc"
assert_eq "1" "$(grep -cF 'shell/bashrc.sh' "$SANDBOX/.bashrc")"

it "a pre-existing real file is not clobbered"
rm -f "$SANDBOX/.claude/CLAUDE.md"
echo "user content" >"$SANDBOX/.claude/CLAUDE.md"
run_install >/dev/null 2>&1
assert_eq "user content" "$(cat "$SANDBOX/.claude/CLAUDE.md")"

echo "[*] shell/bashrc.sh behaviour"
it "sourcing bashrc.sh puts cld and cdx on PATH"
assert_success "HOME='$SANDBOX' bash -c '. \"$REPO_ROOT/shell/bashrc.sh\"; command -v cld && command -v cdx'"

it "sourcing bashrc.sh exports DOTFILES_SKILLS_DIR at the repo skills folder"
assert_eq "$REPO_ROOT/skills" "$(HOME="$SANDBOX" bash -c ". '$REPO_ROOT/shell/bashrc.sh'; printf %s \"\$DOTFILES_SKILLS_DIR\"")"

it "cld and cdx pass bash -n"
assert_success "bash -n '$REPO_ROOT/scripts/cld' && bash -n '$REPO_ROOT/scripts/cdx'"

it "cld launches claude in yolo mode (stub binary)"
STUBS="$SANDBOX/stubs"; mkdir -p "$STUBS"
printf '#!/usr/bin/env bash\necho "ARGS:$*"\n' >"$STUBS/claude"; chmod +x "$STUBS/claude"
out="$(PATH="$STUBS:$PATH" "$REPO_ROOT/scripts/cld" hello 2>/dev/null)"
assert_contains "$out" "ARGS:--dangerously-skip-permissions hello"

it "cdx launches codex in yolo mode (stub binary)"
printf '#!/usr/bin/env bash\necho "ARGS:$*"\n' >"$STUBS/codex"; chmod +x "$STUBS/codex"
out="$(PATH="$STUBS:$PATH" "$REPO_ROOT/scripts/cdx" hello 2>/dev/null)"
assert_contains "$out" "ARGS:--dangerously-bypass-approvals-and-sandbox hello"

finish
