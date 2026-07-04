#!/usr/bin/env bash
# shellcheck shell=bash
# shell/bashrc.sh — everything dotfiles adds to an interactive shell.
#
# install.sh appends ONE guarded source line to ~/.bashrc that loads this file,
# so pulling the repo updates every machine — no re-running install.sh needed.

# Resolve the repo root from this file's location (works wherever the repo
# was cloned: ~/dotfiles in Codespaces, /workspaces/dotfiles in a devcontainer).
DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DOTFILES_DIR

# --- PATH: personal scripts (cld, cdx, ...) and user-local installs ---------
case ":$PATH:" in
  *":$DOTFILES_DIR/scripts:"*) ;;
  *) PATH="$DOTFILES_DIR/scripts:$PATH" ;;
esac
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) PATH="$HOME/.local/bin:$PATH" ;;
esac
export PATH

# --- Agent skills ------------------------------------------------------------
# Skills live in the repo (skills/). install.sh symlinks ~/.claude/skills and
# ~/.codex/skills at this folder so Claude Code and Codex both pick them up.
# Exported here so plain bash scripts can find them too.
export DOTFILES_SKILLS_DIR="$DOTFILES_DIR/skills"

# --- Codespaces: prefer a personal PAT over the repo-scoped codespace token --
# Drop a PAT into /workspaces/.env (e.g. `GITHUB_TOKEN=ghp_...`) and every new
# shell will use it for gh/git instead of the limited GITHUB_TOKEN Codespaces
# injects. If no PAT file exists, the default token is left untouched.
if [ -f /workspaces/.env ]; then
  _dotfiles_pat="$(grep -oE 'ghp_[A-Za-z0-9]+' /workspaces/.env 2>/dev/null | head -n1)"
  if [ -n "$_dotfiles_pat" ]; then
    export GITHUB_TOKEN="$_dotfiles_pat"
    export GH_TOKEN="$_dotfiles_pat"
  fi
  unset _dotfiles_pat
fi

# --- Quality-of-life aliases -------------------------------------------------
alias ll='ls -alF'
alias gs='git status'
alias gl='git log --oneline --graph --decorate -15'

# --- Prompt: starship (installed by install.sh) ------------------------------
# Modern, fast, single-binary prompt that works in bash (Spaceship is zsh-only;
# Starship is its cross-shell successor). Config: config/starship.toml.
if command -v starship >/dev/null 2>&1; then
  eval "$(starship init bash)"
fi
