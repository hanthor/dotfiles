#!/usr/bin/env bash
set -euo pipefail

ALL_VARS="group_vars/all.yml"
echo "Fetching current Homebrew state..."
/home/linuxbrew/.linuxbrew/bin/brew bundle dump --file=/tmp/Brewfile.sync --force
REALITY=$(grep "^brew " /tmp/Brewfile.sync | cut -d'"' -f2 | sort)

# Get current core and desktop lists
CORE=$(yq '.core_brews[]' "$ALL_VARS")
DESKTOP=$(yq '.desktop_brews[]' "$ALL_VARS")

for pkg in $REALITY; do
  # If it's already in core or desktop, skip
  if echo "$CORE" | grep -q "^$pkg$"; then
    continue
  fi
  if echo "$DESKTOP" | grep -q "^$pkg$"; then
    continue
  fi
  
  echo "Adding new package to desktop_brews: $pkg"
  yq -i ".desktop_brews += [\"$pkg\"]" "$ALL_VARS"
done

echo "Done! $ALL_VARS updated surgically."
