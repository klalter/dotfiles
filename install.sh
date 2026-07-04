#!/usr/bin/env bash
# install.sh — set up this dotfiles repo on a new machine.
#
# GitHub Codespaces runs this automatically when the repo is configured as
# your dotfiles repo (Settings → Codespaces → dotfiles). Idempotent: safe to
# re-run any time; re-running picks up new symlinks/tools without duplicating
# anything in ~/.bashrc.
#
# What it does:
#   1. makes scripts/ executable and hooks shell/bashrc.sh into ~/.bashrc
#   2. symlinks agent skills + global memory for Claude Code AND Codex
#   3. installs the Starship prompt (modern cross-shell prompt; works in bash)
#   4. installs Claude Code (the default agent — `cld` to run it;
#      Codex is opt-in: the first `cdx` installs it on demand)
#
# Env toggles:
#   DOTFILES_NO_NETWORK=1   skip network installs (starship, Claude Code) —
#                           used by the test suite and air-gapped machines.
set -euo pipefail

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log() { printf '[dotfiles] %s\n' "$*"; }

# --- 1. scripts + shell hook -------------------------------------------------
chmod +x "$DOTFILES_DIR"/scripts/* 2>/dev/null || true

BASHRC="$HOME/.bashrc"
HOOK="[ -f \"$DOTFILES_DIR/shell/bashrc.sh\" ] && . \"$DOTFILES_DIR/shell/bashrc.sh\""
touch "$BASHRC"
if ! grep -qF "$DOTFILES_DIR/shell/bashrc.sh" "$BASHRC"; then
  {
    echo ""
    echo "# dotfiles (managed): all shell config lives in the repo"
    echo "$HOOK"
  } >>"$BASHRC"
  log "hooked shell/bashrc.sh into $BASHRC"
else
  log "shell hook already present in $BASHRC"
fi

# --- 2. symlinks: skills, agent memory, starship config ----------------------
# link TARGET LINKPATH — create/refresh a symlink, but never clobber a real
# file or directory the user put there themselves.
link() {
  local target="$1" linkpath="$2"
  mkdir -p "$(dirname "$linkpath")"
  if [ -L "$linkpath" ]; then
    ln -sfn "$target" "$linkpath"
  elif [ -e "$linkpath" ]; then
    log "SKIP: $linkpath already exists and is not a symlink (not clobbering)"
    return 0
  else
    ln -s "$target" "$linkpath"
  fi
  log "linked $linkpath -> $target"
}

# One shared skills folder for every agent (see skills/README.md).
link "$DOTFILES_DIR/skills" "$HOME/.claude/skills"
link "$DOTFILES_DIR/skills" "$HOME/.codex/skills"
# Global agent memory, versioned with the repo.
link "$DOTFILES_DIR/agent/CLAUDE.md" "$HOME/.claude/CLAUDE.md"
link "$DOTFILES_DIR/agent/AGENTS.md" "$HOME/.codex/AGENTS.md"
# Prompt config.
link "$DOTFILES_DIR/config/starship.toml" "$HOME/.config/starship.toml"

# --- 3 + 4. network installs -------------------------------------------------
if [ "${DOTFILES_NO_NETWORK:-0}" = "1" ]; then
  log "DOTFILES_NO_NETWORK=1 — skipping starship + Claude Code installs"
else
  # Starship prompt → ~/.local/bin (no sudo needed; bashrc.sh adds it to PATH).
  if command -v starship >/dev/null 2>&1 || [ -x "$HOME/.local/bin/starship" ]; then
    log "starship already installed"
  elif command -v curl >/dev/null 2>&1; then
    log "installing starship prompt..."
    mkdir -p "$HOME/.local/bin"
    if curl -fsSL https://starship.rs/install.sh | sh -s -- --yes --bin-dir "$HOME/.local/bin" >/dev/null; then
      log "starship installed"
    else
      log "WARN: starship install failed (prompt falls back to default PS1)"
    fi
  else
    log "WARN: curl not found — skipping starship install"
  fi

  # Claude Code — the default agent on every new box. `cld` also self-installs,
  # so this is just warming the cache; failure here is not fatal.
  if command -v claude >/dev/null 2>&1 || [ -x "$HOME/.local/bin/claude" ]; then
    log "Claude Code already installed"
  elif command -v npm >/dev/null 2>&1; then
    log "installing Claude Code..."
    npm install -g @anthropic-ai/claude-code \
      && log "Claude Code installed" \
      || log "WARN: npm install failed — 'cld' will retry with the native installer"
  elif command -v curl >/dev/null 2>&1; then
    log "installing Claude Code (native installer)..."
    curl -fsSL https://claude.ai/install.sh | bash \
      && log "Claude Code installed" \
      || log "WARN: Claude Code install failed — run 'cld' later to retry"
  else
    log "WARN: neither npm nor curl found — run 'cld' after installing one"
  fi
fi

# --- 5. VS Code settings -----------------------------------------------------
# Merge config/vscode-settings.json into the Codespace's remote Machine
# settings so every Codespace (any repo) inherits the same editor/terminal
# fonts and UI tweaks. We MERGE (not overwrite) so VS Code's own generated keys
# (Copilot instructions, etc.) survive. Idempotent: re-running just refreshes
# our keys. Note: font *glyphs* render on the client, so install the primary
# font locally for the full look (see config/vscode-settings.json header).
apply_vscode_settings() {
  local src="$DOTFILES_DIR/config/vscode-settings.json"
  [ -f "$src" ] || return 0

  # Merge into whichever VS Code Machine settings location exists (Codespaces
  # uses .vscode-remote; plain remote-SSH uses .vscode-server). Create the
  # Codespaces path proactively when running inside a Codespace.
  local dests=()
  [ -d "$HOME/.vscode-remote/data/Machine" ] && dests+=("$HOME/.vscode-remote/data/Machine/settings.json")
  [ -d "$HOME/.vscode-server/data/Machine" ] && dests+=("$HOME/.vscode-server/data/Machine/settings.json")
  if [ ${#dests[@]} -eq 0 ] && [ "${CODESPACES:-}" = "true" ]; then
    dests+=("$HOME/.vscode-remote/data/Machine/settings.json")
  fi
  [ ${#dests[@]} -eq 0 ] && { log "no VS Code Machine settings dir found — skipping settings merge"; return 0; }

  # merge_json SRC DEST — shallow-merge SRC's keys into DEST (creating DEST if
  # needed), preserving any keys DEST already has. Prefers node (ubiquitous in
  # Codespaces), then jq, then python3 — whichever is present.
  merge_json() {
    local src="$1" dest="$2"
    mkdir -p "$(dirname "$dest")"
    if command -v node >/dev/null 2>&1; then
      node -e '
        const fs = require("fs"), path = require("path");
        const [src, dest] = process.argv.slice(1);
        const add = JSON.parse(fs.readFileSync(src, "utf8"));
        let cur = {};
        try { cur = JSON.parse(fs.readFileSync(dest, "utf8")); } catch (e) {}
        Object.assign(cur, add);
        fs.mkdirSync(path.dirname(dest), { recursive: true });
        fs.writeFileSync(dest, JSON.stringify(cur, null, "\t") + "\n");
      ' "$src" "$dest"
    elif command -v jq >/dev/null 2>&1; then
      [ -s "$dest" ] || printf '{}\n' >"$dest"
      local tmp="$dest.dotfiles.tmp"
      if jq --tab -s '.[0] * .[1]' "$dest" "$src" >"$tmp" 2>/dev/null; then
        mv "$tmp" "$dest"
      else
        rm -f "$tmp"; return 1
      fi
    elif command -v python3 >/dev/null 2>&1; then
      python3 - "$src" "$dest" <<'PY'
import json, os, sys
src, dest = sys.argv[1], sys.argv[2]
with open(src) as f: new = json.load(f)
cur = {}
if os.path.exists(dest):
    try:
        with open(dest) as f: cur = json.load(f)
    except Exception: cur = {}
cur.update(new)
with open(dest, "w") as f:
    json.dump(cur, f, indent="\t"); f.write("\n")
PY
    else
      log "WARN: no node/jq/python3 — skipping VS Code settings merge"
      return 1
    fi
  }

  local dest
  for dest in "${dests[@]}"; do
    if merge_json "$src" "$dest"; then
      log "merged VS Code settings -> $dest"
    else
      log "WARN: could not merge VS Code settings into $dest"
    fi
  done
}
apply_vscode_settings

log "install complete — open a new shell (or 'source ~/.bashrc') to pick it up"
