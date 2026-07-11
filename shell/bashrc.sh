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
# Skills come from the optional workspace-wide collection and this repo.
# install.sh child-links both roots into the Codex, Claude, and Copilot global
# skill directories.
# These exports let shell scripts locate either source directly.
export DOTFILES_SKILLS_DIR="$DOTFILES_DIR/skills"
export DOTFILES_WORKSPACE_SKILLS_DIR="${DOTFILES_SHARED_SKILLS_DIR:-/workspaces/.ai/skills}"
export DOTFILES_SKILLS_DIRS="$DOTFILES_WORKSPACE_SKILLS_DIR:$DOTFILES_SKILLS_DIR"

# --- GitHub auth: use the broadest token available ---------------------------
# Priority: explicit PAT in /workspaces/.env  >  `gh auth login` token  >  the
# repo-scoped GITHUB_TOKEN Codespaces injects by default. The default token can
# only reach the current repo; a `gh auth login` (or PAT) lets git/gh clone any
# repo you have access to.
_dotfiles_set_token() { export GITHUB_TOKEN="$1"; export GH_TOKEN="$1"; }

_dotfiles_pat=""
if [ -f /workspaces/.env ]; then
  _dotfiles_pat="$(grep -oE '(ghp_[A-Za-z0-9]+|github_pat_[A-Za-z0-9_]+)' /workspaces/.env 2>/dev/null | head -n1)"
fi
if [ -n "$_dotfiles_pat" ]; then
  _dotfiles_set_token "$_dotfiles_pat"
elif [ -f "$HOME/.config/gh/hosts.yml" ] && command -v gh >/dev/null 2>&1; then
  # Read the token stored by `gh auth login` (env unset so gh ignores the
  # injected codespace token and returns its own).
  _dotfiles_gh_tok="$(env -u GITHUB_TOKEN -u GH_TOKEN gh auth token 2>/dev/null || true)"
  [ -n "$_dotfiles_gh_tok" ] && _dotfiles_set_token "$_dotfiles_gh_tok"
  unset _dotfiles_gh_tok
fi
unset _dotfiles_pat

# --- First-run: sign in to GitHub once, so you can clone any repo ------------
# Interactive TTY only, once per box (sentinel). Disable with DOTFILES_NO_GH_LOGIN=1.
_dotfiles_gh_first_login() {
  case $- in *i*) ;; *) return 0 ;; esac          # interactive shells only
  { [ -t 0 ] && [ -t 1 ]; } || return 0           # real terminal only
  [ "${DOTFILES_NO_GH_LOGIN:-0}" = "1" ] && return 0
  command -v gh >/dev/null 2>&1 || return 0
  local sentinel="$HOME/.config/dotfiles/gh-login-prompted"
  [ -f "$sentinel" ] && return 0
  mkdir -p "$(dirname "$sentinel")"
  # Already signed in with a stored (non-env) token? record and skip.
  if env -u GITHUB_TOKEN -u GH_TOKEN gh auth status >/dev/null 2>&1; then
    touch "$sentinel"; return 0
  fi
  # Dev-container already configured gh via an exported token (devcontainer
  # feature or an env-injected GH_TOKEN/GITHUB_TOKEN)? gh works as-is, so don't
  # nag. Skipped inside Codespaces, whose auto-injected token is repo-scoped
  # only — there we still offer the broader login below.
  if [ "${CODESPACES:-}" != "true" ] && gh auth status >/dev/null 2>&1; then
    touch "$sentinel"; return 0
  fi
  printf '\n\033[1;34m[dotfiles]\033[0m First-time setup: sign in to GitHub so you can clone any repo you have access to.\n'
  printf '           Follow the prompt below, or press \033[1mCtrl-C\033[0m to skip (run \033[1mgh auth login\033[0m later).\n\n'
  if env -u GITHUB_TOKEN -u GH_TOKEN gh auth login --hostname github.com --git-protocol https --web; then
    env -u GITHUB_TOKEN -u GH_TOKEN gh auth setup-git >/dev/null 2>&1 || true
    local tok; tok="$(env -u GITHUB_TOKEN -u GH_TOKEN gh auth token 2>/dev/null || true)"
    [ -n "$tok" ] && _dotfiles_set_token "$tok"
    printf '\n\033[1;32m[dotfiles]\033[0m Signed in — git and gh now use your account token.\n'
  else
    printf '\n\033[1;33m[dotfiles]\033[0m Skipped. Run \033[1mgh auth login\033[0m anytime to enable cloning private repos.\n'
  fi
  touch "$sentinel"
}
_dotfiles_gh_first_login
unset -f _dotfiles_gh_first_login _dotfiles_set_token

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
