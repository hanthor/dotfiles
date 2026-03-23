#!/usr/bin/env bash
set -euo pipefail

eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"

BREWFILE="$(chezmoi source-path)/Brewfile"

if [ ! -f "$BREWFILE" ]; then
  echo "ERROR: Brewfile not found at $BREWFILE"
  exit 1
fi

echo "Installing packages from Brewfile..."
brew bundle install --file="$BREWFILE" --no-lock
echo "Packages installed."
