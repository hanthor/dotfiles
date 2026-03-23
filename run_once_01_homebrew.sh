#!/usr/bin/env bash
set -euo pipefail

if command -v brew &>/dev/null; then
  echo "Homebrew already installed, skipping."
  exit 0
fi

echo "Installing Homebrew..."
NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Add brew to PATH for remainder of this script
eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"
echo "Homebrew installed."
