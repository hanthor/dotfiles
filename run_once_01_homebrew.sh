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
BREWFILE="$(chezmoi source-path)/Brewfile"
if [ -f "$BREWFILE" ]; then
  echo "Installing packages from Brewfile (initial bootstrap)..."
  brew bundle install --file="$BREWFILE" --no-lock
  echo "Packages installed."
else
  echo "WARNING: Brewfile not found at $BREWFILE, skipping brew bundle."
fi
