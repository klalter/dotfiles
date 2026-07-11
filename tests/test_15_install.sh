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
SHARED_SKILLS="$SANDBOX/shared-skills"
EXISTING_SKILL="$SANDBOX/existing-example-skill"
mkdir -p "$SHARED_SKILLS/workspace-skill" "$SANDBOX/.codex/skills/bundled-skill" "$EXISTING_SKILL"
printf '%s\n' '---' 'name: workspace-skill' 'description: A shared workspace test skill.' '---' >"$SHARED_SKILLS/workspace-skill/SKILL.md"
printf '%s\n' '---' 'name: bundled-skill' 'description: A pre-existing Codex test skill.' '---' >"$SANDBOX/.codex/skills/bundled-skill/SKILL.md"
printf '%s\n' '---' 'name: example-skill' 'description: A pre-existing linked test skill.' '---' >"$EXISTING_SKILL/SKILL.md"
ln -s "$EXISTING_SKILL" "$SANDBOX/.codex/skills/example-skill"

run_install() {
  HOME="$SANDBOX" DOTFILES_NO_NETWORK=1 DOTFILES_SHARED_SKILLS_DIR="$SHARED_SKILLS" bash "$REPO_ROOT/install.sh"
}

echo "[*] install.sh on a fresh HOME"
it "install.sh exits 0 on a fresh HOME (no network)"
if out="$(run_install 2>&1)"; then _pass; else _fail "" "$(printf '%s' "$out" | tail -5)"; fi

it "HOME/.bashrc gained the shell hook"
assert_success "grep -qF 'shell/bashrc.sh' '$SANDBOX/.bashrc'"

it "Claude discovers a dotfiles skill through its global skills directory"
assert_eq "$REPO_ROOT/skills/example-skill" "$(readlink "$SANDBOX/.claude/skills/example-skill" 2>/dev/null)"

it "Codex discovers a dotfiles skill without replacing its existing skills directory"
assert_eq "$REPO_ROOT/skills/kyndryl-drawio-deck" "$(readlink "$SANDBOX/.codex/skills/kyndryl-drawio-deck" 2>/dev/null)"

it "both CLIs discover a workspace-shared skill"
assert_eq "$SHARED_SKILLS/workspace-skill" "$(readlink "$SANDBOX/.claude/skills/workspace-skill" 2>/dev/null)"
assert_eq "$SHARED_SKILLS/workspace-skill" "$(readlink "$SANDBOX/.codex/skills/workspace-skill" 2>/dev/null)"

it "Codex and Copilot discover both sources through the shared agents root"
assert_eq "$SHARED_SKILLS/workspace-skill" "$(readlink "$SANDBOX/.agents/skills/workspace-skill" 2>/dev/null)"
assert_eq "$REPO_ROOT/skills/example-skill" "$(readlink "$SANDBOX/.agents/skills/example-skill" 2>/dev/null)"

it "Copilot discovers both sources through its global skills root"
assert_eq "$SHARED_SKILLS/workspace-skill" "$(readlink "$SANDBOX/.copilot/skills/workspace-skill" 2>/dev/null)"
assert_eq "$REPO_ROOT/skills/example-skill" "$(readlink "$SANDBOX/.copilot/skills/example-skill" 2>/dev/null)"

it "pre-existing Codex skills are preserved"
assert_file "$SANDBOX/.codex/skills/bundled-skill/SKILL.md"
assert_eq "$EXISTING_SKILL" "$(readlink "$SANDBOX/.codex/skills/example-skill" 2>/dev/null)"

it "HOME/.claude/CLAUDE.md -> repo agent/CLAUDE.md"
assert_eq "$REPO_ROOT/agent/CLAUDE.md" "$(readlink "$SANDBOX/.claude/CLAUDE.md" 2>/dev/null)"

it "HOME/.codex/AGENTS.md -> repo agent/AGENTS.md"
assert_eq "$REPO_ROOT/agent/AGENTS.md" "$(readlink "$SANDBOX/.codex/AGENTS.md" 2>/dev/null)"

it "HOME/.codex/CODEX.md -> repo agent/CODEX.md"
assert_eq "$REPO_ROOT/agent/CODEX.md" "$(readlink "$SANDBOX/.codex/CODEX.md" 2>/dev/null)"

it "HOME/.copilot/instructions/global.instructions.md -> repo agent/AGENTS.md"
assert_eq "$REPO_ROOT/agent/AGENTS.md" "$(readlink "$SANDBOX/.copilot/instructions/global.instructions.md" 2>/dev/null)"

it "agent/CLAUDE.md resolves to the one canonical agent/AGENTS.md"
assert_eq "$REPO_ROOT/agent/AGENTS.md" "$(readlink -f "$SANDBOX/.claude/CLAUDE.md" 2>/dev/null)"

it "agent/CODEX.md resolves to the one canonical agent/AGENTS.md"
assert_eq "$REPO_ROOT/agent/AGENTS.md" "$(readlink -f "$SANDBOX/.codex/CODEX.md" 2>/dev/null)"

it "global instruction paths are the same file as agent/AGENTS.md"
canonical_inode="$(stat -c '%d:%i' "$REPO_ROOT/agent/AGENTS.md")"
assert_eq "$canonical_inode" "$(stat -Lc '%d:%i' "$SANDBOX/.claude/CLAUDE.md")"
assert_eq "$canonical_inode" "$(stat -Lc '%d:%i' "$SANDBOX/.codex/AGENTS.md")"
assert_eq "$canonical_inode" "$(stat -Lc '%d:%i' "$SANDBOX/.codex/CODEX.md")"
assert_eq "$canonical_inode" "$(stat -Lc '%d:%i' "$SANDBOX/.copilot/instructions/global.instructions.md")"

it "HOME/.config/starship.toml -> repo config/starship.toml"
assert_eq "$REPO_ROOT/config/starship.toml" "$(readlink "$SANDBOX/.config/starship.toml" 2>/dev/null)"

it "HOME/.config/herdr/config.toml -> repo config/herdr.toml"
assert_eq "$REPO_ROOT/config/herdr.toml" "$(readlink "$SANDBOX/.config/herdr/config.toml" 2>/dev/null)"

it "HOME/.local/bin/merge-skills -> repo scripts/merge-skills"
assert_eq "$REPO_ROOT/scripts/merge-skills" "$(readlink "$SANDBOX/.local/bin/merge-skills" 2>/dev/null)"

it "dotfiles skills resolve through their child symlinks"
assert_file "$SANDBOX/.claude/skills/example-skill/SKILL.md"

echo "[*] install.sh is idempotent"
it "second run exits 0"
assert_success "HOME='$SANDBOX' DOTFILES_NO_NETWORK=1 bash '$REPO_ROOT/install.sh'"

it "shell hook appears exactly once in .bashrc"
assert_eq "1" "$(grep -cF 'shell/bashrc.sh' "$SANDBOX/.bashrc")"

it "merge-skills refreshes missing child skill links without network installs"
rm -f "$SANDBOX/.claude/skills/workspace-skill"
assert_success "HOME='$SANDBOX' DOTFILES_SHARED_SKILLS_DIR='$SHARED_SKILLS' '$SANDBOX/.local/bin/merge-skills' >/dev/null"
assert_eq "$SHARED_SKILLS/workspace-skill" "$(readlink "$SANDBOX/.claude/skills/workspace-skill" 2>/dev/null)"

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

it "sourcing bashrc.sh exports both skill source directories"
assert_eq "$SHARED_SKILLS:$REPO_ROOT/skills" "$(HOME="$SANDBOX" DOTFILES_SHARED_SKILLS_DIR="$SHARED_SKILLS" bash -c ". '$REPO_ROOT/shell/bashrc.sh'; printf %s \"\$DOTFILES_SKILLS_DIRS\"")"

it "cld and cdx pass bash -n"
assert_success "bash -n '$REPO_ROOT/scripts/cld' && bash -n '$REPO_ROOT/scripts/cdx'"

it "cld launches claude in yolo mode without NODE_EXTRA_CA_CERTS (stub binary)"
STUBS="$SANDBOX/stubs"; mkdir -p "$STUBS"
printf '#!/usr/bin/env bash\nprintf "NODE_EXTRA_CA_CERTS:%%s\\n" "${NODE_EXTRA_CA_CERTS-unset}"\necho "ARGS:$*"\n' >"$STUBS/claude"; chmod +x "$STUBS/claude"
out="$(NODE_EXTRA_CA_CERTS=/tmp/broken.pem PATH="$STUBS:$PATH" "$REPO_ROOT/scripts/cld" hello 2>/dev/null)"
assert_contains "$out" "NODE_EXTRA_CA_CERTS:unset"
assert_contains "$out" "ARGS:--dangerously-skip-permissions hello"

it "cdx launches codex in yolo mode (stub binary)"
printf '#!/usr/bin/env bash\necho "ARGS:$*"\n' >"$STUBS/codex"; chmod +x "$STUBS/codex"
out="$(PATH="$STUBS:$PATH" "$REPO_ROOT/scripts/cdx" hello 2>/dev/null)"
assert_contains "$out" "ARGS:--dangerously-bypass-approvals-and-sandbox hello"

finish
