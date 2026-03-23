#!/usr/bin/env bash
set -euo pipefail

BREW_ZSH="/home/linuxbrew/.linuxbrew/bin/zsh"

if [ ! -f "$BREW_ZSH" ]; then
  echo "ERROR: zsh not found at $BREW_ZSH — run packages script first."
  exit 1
fi

# Add Homebrew zsh to /etc/shells if not already present
if ! grep -q "$BREW_ZSH" /etc/shells; then
  echo "Adding $BREW_ZSH to /etc/shells..."
  echo "$BREW_ZSH" | sudo tee -a /etc/shells
fi

# Change login shell
if [ "$SHELL" = "$BREW_ZSH" ]; then
  echo "Login shell is already $BREW_ZSH, skipping."
  exit 0
fi

echo "Changing login shell to $BREW_ZSH..."
sudo chsh -s "$BREW_ZSH" "$USER"
echo "Login shell changed. Takes effect on next login."
