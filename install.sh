#!/usr/bin/env bash
set -e

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPTS_DIR="$DOTFILES_DIR/scripts"

# Make all scripts executable
chmod +x "$SCRIPTS_DIR"/*

# Add scripts dir to PATH in .bashrc if not already there
BASHRC="$HOME/.bashrc"
PATH_LINE="export PATH=\"$SCRIPTS_DIR:\$PATH\""

if ! grep -qF "$SCRIPTS_DIR" "$BASHRC" 2>/dev/null; then
    echo "" >> "$BASHRC"
    echo "# dotfiles: personal scripts" >> "$BASHRC"
    echo "$PATH_LINE" >> "$BASHRC"
    echo "Added scripts dir to PATH in $BASHRC"
else
    echo "scripts dir already in PATH, skipping"
fi

# Use personal PAT if present, falling back to codespace token
ENV_FILE="/workspaces/.env"
GITHUB_TOKEN_LINE='export GITHUB_TOKEN=$(grep -oP '"'"'ghp_\S+'"'"' '"$ENV_FILE"' 2>/dev/null || echo "$GITHUB_TOKEN")'

if [ -f "$ENV_FILE" ] && ! grep -qF "dotfiles: github token" "$BASHRC" 2>/dev/null; then
    echo "" >> "$BASHRC"
    echo "# dotfiles: github token" >> "$BASHRC"
    echo "unset GITHUB_TOKEN" >> "$BASHRC"
    echo "$GITHUB_TOKEN_LINE" >> "$BASHRC"
    echo "Configured GITHUB_TOKEN from $ENV_FILE"
fi

echo "dotfiles install complete"
