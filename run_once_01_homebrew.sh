#!/usr/bin/env bash
set -euo pipefail

if command -v brew &>/dev/null; then
  echo "Homebrew already installed, skipping."
else
  echo "Installing Homebrew..."
  NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"

# Run brew bundle on first init so packages (including bw, gh, etc.)
# are available for subsequent run_once_ scripts.
BREWFILE="$HOME/Brewfile"
if [ -f "$BREWFILE" ]; then
  echo "Installing packages from Brewfile (initial bootstrap)..."
  # Disable credential helper during bootstrap — gh may not be installed yet
  GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0="" \
    brew bundle install --file="$BREWFILE"
  echo "Packages installed."
else
  echo "WARNING: Brewfile not found at $BREWFILE, skipping brew bundle."
fi
