#!/usr/bin/env bash
# 01-clean-env.sh — deterministic clean-Codespace validation for dev-shell.
#
# Verifies (against the freshly-created Codespace this script is run inside):
#   1. sshd bring-up via post-start.sh / $SCRIPTS_ROOT/sshd.sh
#   2. global agent-skill wiring (Claude/Codex/Copilot) from the dotfiles repo
#   3. a global git excludesfile is configured and covers Python bytecode junk
#   4. baseline toolchain + clean repo state + devx binary
#  12. the "work" feature (devx work / worksvc / worktree / ado / work-panel /
#      /api/work/*) has been fully removed, while --workspace and
#      /api/workspace/paths remain
#
# Pure bash, no interactive prompts, no network beyond what's already local,
# starts no services. Prints "  ✅ <check>" / "  ❌ <check>" lines grouped
# under "── N. <section> ──" headers, then a final
# "RESULT: N passed, M failed" line. Exits 1 if anything failed.

set -uo pipefail

cd "$(git rev-parse --show-toplevel)" || exit 1

PASS_COUNT=0
FAIL_COUNT=0

section() {
  printf '\n── %s ──\n' "$1"
}

ok() {
  printf '  \xe2\x9c\x85 %s\n' "$1"
  PASS_COUNT=$((PASS_COUNT + 1))
}

bad() {
  printf '  \xe2\x9d\x8c %s\n' "$1"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

# ─────────────────────────────────────────────────────────────────────────
section "1. sshd bring-up"
# ─────────────────────────────────────────────────────────────────────────

SCRIPTS_ROOT="/workspaces/.scripts"
CREATION_LOG="/workspaces/.codespaces/.persistedshare/creation.log"

if pgrep -x sshd >/dev/null 2>&1; then
  ok "sshd master process is running (pgrep -x sshd)"
else
  bad "no sshd master process found (pgrep -x sshd)"
fi

port_reachable() {
  timeout 1 bash -c ":</dev/tcp/127.0.0.1/${1}" >/dev/null 2>&1
}

if port_reachable 22 || port_reachable 2222; then
  ok "sshd is actually accepting TCP connections on 127.0.0.1 (22 or 2222)"
else
  bad "sshd is NOT reachable on 127.0.0.1:22 or 127.0.0.1:2222"
fi

RESOLVED_SCRIPTS_ROOT=""
if [ -e "$SCRIPTS_ROOT" ]; then
  RESOLVED_SCRIPTS_ROOT="$(readlink -f "$SCRIPTS_ROOT" 2>/dev/null || true)"
  ok "$SCRIPTS_ROOT resolves (target: ${RESOLVED_SCRIPTS_ROOT:-<unresolved>})"
else
  bad "$SCRIPTS_ROOT does not exist (dangling symlink or never linked)"
fi

if [ -x "$SCRIPTS_ROOT/sshd.sh" ]; then
  ok "$SCRIPTS_ROOT/sshd.sh is present and executable"
else
  bad "$SCRIPTS_ROOT/sshd.sh is missing or not executable"
fi

# Real functional check, not a restatement of the above: did post-start.sh's
# own sshd.sh invocation actually hit its documented failure fallback
# ('WARN: could not start sshd listener', emitted by post-start.sh's
# `|| echo ...` guard when $SCRIPTS_ROOT/sshd.sh was missing/failed)?
if [ -r "$CREATION_LOG" ]; then
  if grep -q "could not start sshd listener" "$CREATION_LOG" 2>/dev/null; then
    bad "creation.log shows post-start.sh HIT the sshd fallback warning (sshd.sh was missing/failed on first boot)"
  else
    ok "creation.log shows no sshd fallback warning (sshd.sh ran cleanly during postStartCommand)"
  fi
else
  bad "cannot read $CREATION_LOG to verify postStartCommand's sshd outcome"
fi

# ─────────────────────────────────────────────────────────────────────────
section "2. Global skills wiring"
# ─────────────────────────────────────────────────────────────────────────

AI_SKILLS_SRC="/workspaces/.ai/skills"
AI_AREAS_SRC="/workspaces/.ai/areas"

if [ -d "$AI_SKILLS_SRC" ] && [ -n "$(ls -A "$AI_SKILLS_SRC" 2>/dev/null)" ]; then
  ok "source $AI_SKILLS_SRC exists and is populated"
else
  bad "source $AI_SKILLS_SRC is missing or empty"
fi

if [ -d "$AI_AREAS_SRC" ] && [ -n "$(ls -A "$AI_AREAS_SRC" 2>/dev/null)" ]; then
  ok "source $AI_AREAS_SRC exists and is populated"
else
  bad "source $AI_AREAS_SRC is missing or empty"
fi

check_cli_skills_dir() {
  local dir="$1"
  local label="$2"
  if [ -d "$dir" ] && [ -n "$(find "$dir" -mindepth 1 -maxdepth 1 2>/dev/null)" ]; then
    ok "$label skills dir ($dir) exists and is populated"
  else
    bad "$label skills dir ($dir) is missing or empty"
  fi
}

check_cli_skills_dir "$HOME/.claude/skills" "Claude"
check_cli_skills_dir "$HOME/.codex/skills" "Codex"
check_cli_skills_dir "$HOME/.copilot/skills" "Copilot"

if [ -L "$HOME/.codex/AGENTS.md" ] && [ -e "$HOME/.codex/AGENTS.md" ]; then
  ok "~/.codex/AGENTS.md symlink resolves"
else
  bad "~/.codex/AGENTS.md is missing or a dangling symlink"
fi

if [ -L "$HOME/.copilot/instructions/global.instructions.md" ] && [ -e "$HOME/.copilot/instructions/global.instructions.md" ]; then
  ok "~/.copilot/instructions/global.instructions.md symlink resolves"
else
  bad "~/.copilot/instructions/global.instructions.md is missing or a dangling symlink"
fi

DANGLING="$(find "$HOME/.claude" "$HOME/.codex" "$HOME/.copilot" -xtype l 2>/dev/null)"
if [ -z "$DANGLING" ]; then
  ok "no dangling symlinks under ~/.claude, ~/.codex, ~/.copilot"
else
  bad "dangling symlinks found: $(printf '%s' "$DANGLING" | tr '\n' ' ')"
fi

# The refresh helper: documented as `merge-skills`, but this dotfiles repo has
# renamed the actual mechanism to `link-agent-dirs` (merge-skills is not
# installed as a command). Accept either so the check reflects the real
# capability ("can I refresh the skill wiring on demand?"), not a stale name.
#
# Resolve against the binary's location + how PATH actually gets built for a
# real (interactive) session, rather than this script's own inherited PATH:
# `gh codespace ssh -- '<cmd>'` runs a non-interactive, non-login shell, so
# ~/.bashrc (which is what prepends $HOME/.scripts -> $SCRIPTS_ROOT to PATH)
# is never sourced here even though it is for every real terminal/VS Code
# session.
HELPER_BIN=""
if [ -x "$SCRIPTS_ROOT/merge-skills" ]; then
  HELPER_BIN="$SCRIPTS_ROOT/merge-skills"
elif [ -x "$SCRIPTS_ROOT/link-agent-dirs" ]; then
  HELPER_BIN="$SCRIPTS_ROOT/link-agent-dirs"
fi

if [ -n "$HELPER_BIN" ] \
  && grep -Eq '\$HOME/\.scripts.*PATH|PATH=.*\.scripts' "$HOME/.bashrc" 2>/dev/null; then
  ok "skills-refresh helper present ($HELPER_BIN) and ~/.bashrc wires \$HOME/.scripts onto PATH for interactive shells"
else
  bad "no skills-refresh helper (merge-skills/link-agent-dirs) executable under \$SCRIPTS_ROOT with PATH wiring in ~/.bashrc"
fi

# ─────────────────────────────────────────────────────────────────────────
section "3. Global gitignore"
# ─────────────────────────────────────────────────────────────────────────

EXCLUDES_FILE="$(git config --global core.excludesfile 2>/dev/null || true)"

if [ -n "$EXCLUDES_FILE" ]; then
  ok "git config --global core.excludesfile is set: $EXCLUDES_FILE"
else
  bad "git config --global core.excludesfile is NOT set"
fi

if [ -n "$EXCLUDES_FILE" ] && [ -f "$EXCLUDES_FILE" ]; then
  ok "excludesfile ($EXCLUDES_FILE) exists on disk"
else
  bad "no readable excludesfile on disk to verify content"
fi

if [ -n "$EXCLUDES_FILE" ] && [ -f "$EXCLUDES_FILE" ] \
  && grep -Eq '(^|/)__pycache__/?$' "$EXCLUDES_FILE" 2>/dev/null \
  && grep -Eq '\*\.pyc$' "$EXCLUDES_FILE" 2>/dev/null; then
  ok "excludesfile covers Python bytecode (__pycache__/ and *.pyc)"
else
  bad "excludesfile does not cover both __pycache__/ and *.pyc"
fi

# ─────────────────────────────────────────────────────────────────────────
section "4. Clean-env sanity"
# ─────────────────────────────────────────────────────────────────────────

check_tool_version() {
  local name="$1"
  shift
  local out
  if out="$("$@" 2>&1)"; then
    ok "$name available: $(printf '%s' "$out" | tr '\n' ' ' | cut -c1-80)"
  else
    bad "$name is not usable ($*)"
  fi
}

check_tool_version "go" go version
check_tool_version "node" node --version
check_tool_version "npm" npm --version
check_tool_version "jq" jq --version
check_tool_version "gh" gh --version

if docker --version >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
  ok "docker CLI works and the daemon is reachable (docker ps)"
else
  bad "docker is not usable (binary missing or daemon unreachable)"
fi

CURRENT_BRANCH="$(git branch --show-current 2>/dev/null || true)"
if [ "$CURRENT_BRANCH" = "feat/remove-work-feature" ]; then
  ok "repo is on branch feat/remove-work-feature"
else
  bad "repo is on unexpected branch: '${CURRENT_BRANCH:-<detached>}'"
fi

GIT_STATUS_OUT="$(git status --porcelain=v1 2>&1)"
if [ -z "$GIT_STATUS_OUT" ]; then
  ok "git status is clean (no untracked/modified files)"
else
  bad "git status is NOT clean: $(printf '%s' "$GIT_STATUS_OUT" | tr '\n' '|')"
fi

if [ -x devx/devx ] && devx --help 2>&1 | grep -q "devx is a unified CLI"; then
  ok "devx binary exists and runs (devx --help)"
else
  bad "devx binary missing, not executable, or --help failed"
fi

# ─────────────────────────────────────────────────────────────────────────
section "12. Work feature is gone"
# ─────────────────────────────────────────────────────────────────────────

DEVX_HELP="$(devx --help 2>&1 || true)"
if printf '%s' "$DEVX_HELP" | grep -Eq '(^|[[:space:]])work([[:space:]]|$)'; then
  bad "'devx --help' still lists a 'work' command"
else
  ok "'devx --help' does not list a 'work' command"
fi

if devx work >/dev/null 2>&1; then
  bad "'devx work' unexpectedly succeeded"
else
  DEVX_WORK_ERR="$(devx work 2>&1 || true)"
  if printf '%s' "$DEVX_WORK_ERR" | grep -q 'unknown command "work"'; then
    ok "'devx work' is rejected as an unknown command"
  else
    bad "'devx work' failed, but not with the expected 'unknown command' message: $DEVX_WORK_ERR"
  fi
fi

check_no_work_flag_but_workspace_kept() {
  local cmd_desc="$1"
  shift
  local help_out
  help_out="$("$@" --help 2>&1 || true)"

  if printf '%s' "$help_out" | grep -Eq -- '--work([^a-zA-Z0-9_-]|$)'; then
    bad "$cmd_desc unexpectedly has a --work flag"
  else
    ok "$cmd_desc has no --work flag"
  fi

  if printf '%s' "$help_out" | grep -Eq -- '--workspace([^a-zA-Z0-9_-]|$)'; then
    ok "$cmd_desc still has the --workspace flag"
  else
    bad "$cmd_desc is missing the --workspace flag (should remain)"
  fi
}

check_no_work_flag_but_workspace_kept "'devx up'" devx up
check_no_work_flag_but_workspace_kept "'devx status'" devx status
check_no_work_flag_but_workspace_kept "'devx instance up'" devx instance up

if [ -d devx/internal/server ] \
  && grep -RqE '"/api/work(/|")' devx/internal/server/ 2>/dev/null; then
  bad "found an /api/work/* route registration in devx/internal/server/"
else
  ok "no /api/work/* route registrations in devx/internal/server/"
fi

if [ -d devx/internal/server ] \
  && grep -Rq '/api/workspace/paths' devx/internal/server/ 2>/dev/null; then
  ok "/api/workspace/paths route is still registered"
else
  bad "/api/workspace/paths route is missing (should remain)"
fi

ALL_ABSENT=true
for path in \
  devx/internal/work \
  devx/internal/worksvc \
  devx/internal/worktree \
  devx/internal/ado \
  src/components/configurator/panels/work-panel.ts \
  test/ui/work-panel.spec.ts; do
  if [ -e "$path" ]; then
    bad "removed path still exists: $path"
    ALL_ABSENT=false
  fi
done
if [ "$ALL_ABSENT" = true ]; then
  ok "all removed work-feature paths are absent (work/worksvc/worktree/ado, work-panel.ts, work-panel.spec.ts)"
fi

if [ -f test/profile-regression.sh ]; then
  ok "test/profile-regression.sh still exists (needed by CI)"
else
  bad "test/profile-regression.sh is missing (CI needs it)"
fi

# ─────────────────────────────────────────────────────────────────────────
printf '\nRESULT: %d passed, %d failed\n' "$PASS_COUNT" "$FAIL_COUNT"
[ "$FAIL_COUNT" -eq 0 ]
