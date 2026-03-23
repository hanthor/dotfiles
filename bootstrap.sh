#!/usr/bin/env bash
# Bootstrap script for hanthor/dotfiles
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash
#   curl ... | bash -s -- --name karnataka
#   ./bootstrap.sh --name karnataka
set -euo pipefail

REPO_URL="https://github.com/hanthor/dotfiles.git"
DOTFILES_DIR="$HOME/.local/share/dotfiles"
MACHINE_FILE="/etc/dotfiles-machine"
MACHINE_NAME=""

# ── Parse arguments ───────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --name) MACHINE_NAME="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ── Detect OS ─────────────────────────────────────────────────────
detect_os() {
  if [ -f /usr/lib/os-release ]; then
    . /usr/lib/os-release
  elif [ -f /etc/os-release ]; then
    . /etc/os-release
  fi
  echo "${ID:-unknown}"
}

OS=$(detect_os)
echo "Detected OS: $OS"

# ── Install Python + pip ──────────────────────────────────────────
ensure_python() {
  if command -v python3 &>/dev/null; then
    echo "Python3 found."
  else
    echo "Installing Python3..."
    case "$OS" in
      fedora|rhel|centos) sudo dnf install -y python3 ;;
      debian|ubuntu)      sudo apt-get update && sudo apt-get install -y python3 ;;
      *)                  echo "ERROR: Unsupported OS '$OS'. Install python3 manually."; exit 1 ;;
    esac
  fi
}

# ── Install uv ────────────────────────────────────────────────────
ensure_uv() {
  if command -v uv &>/dev/null; then
    echo "uv found."
    return
  fi
  if [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
    echo "uv found in ~/.local/bin."
    return
  fi
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
}

# ── Install Ansible ───────────────────────────────────────────────
ensure_ansible() {
  for p in "$HOME/.local/bin" "/home/linuxbrew/.linuxbrew/bin"; do
    if [ -x "$p/ansible-playbook" ]; then
      export PATH="$p:$PATH"
      echo "Ansible found in $p."
      return
    fi
  done
  if command -v ansible-playbook &>/dev/null; then
    echo "Ansible found."
    return
  fi

  echo "Installing Ansible via uv..."
  uv tool install --with ansible ansible-core
  export PATH="$HOME/.local/bin:$PATH"
}

# ── Install git ───────────────────────────────────────────────────
ensure_git() {
  if command -v git &>/dev/null; then return; fi
  echo "Installing git..."
  case "$OS" in
    fedora|rhel|centos) sudo dnf install -y git ;;
    debian|ubuntu)      sudo apt-get update && sudo apt-get install -y git ;;
  esac
}

# ── Clone repo ────────────────────────────────────────────────────
clone_repo() {
  if [ -d "$DOTFILES_DIR/.git" ]; then
    echo "Dotfiles repo exists, pulling latest..."
    git -C "$DOTFILES_DIR" pull --ff-only
  else
    echo "Cloning dotfiles..."
    git clone "$REPO_URL" "$DOTFILES_DIR"
  fi
}

# ── Prompt for machine name ───────────────────────────────────────
get_machine_name() {
  if [ -n "$MACHINE_NAME" ]; then return; fi

  # Check if already set
  if [ -f "$MACHINE_FILE" ]; then
    MACHINE_NAME=$(cat "$MACHINE_FILE")
    echo "Machine already identified as: $MACHINE_NAME"
    return
  fi

  echo ""
  echo "Available machines: himachal karnataka dilli kanpur goa bihar matrix lkofoss"

  if [ ! -c /dev/tty ]; then
    echo "ERROR: Cannot prompt interactively (no /dev/tty)."
    echo "Re-run with: curl -fsSL $0 | bash -s -- --name <machine>"
    exit 1
  fi

  printf "Machine name: " >/dev/tty
  read -r MACHINE_NAME </dev/tty

  if [ -z "$MACHINE_NAME" ]; then
    echo "ERROR: Machine name is required. Pass --name <machine> to skip prompt."
    exit 1
  fi
}

write_machine_name() {
  if [ -f "$MACHINE_FILE" ] && [ "$(cat "$MACHINE_FILE")" = "$MACHINE_NAME" ]; then
    return
  fi
  echo "$MACHINE_NAME" | sudo tee "$MACHINE_FILE" > /dev/null
  echo "Machine name written to $MACHINE_FILE"
}

# ── Install Galaxy collections ────────────────────────────────────
install_collections() {
  echo "Installing Ansible collections..."
  ansible-galaxy collection install -r "$DOTFILES_DIR/requirements.yml" --force-with-deps 2>/dev/null || \
    ansible-galaxy collection install community.general
}

# ── Run playbook ──────────────────────────────────────────────────
run_playbook() {
  echo ""
  echo "═══════════════════════════════════════════════════"
  echo "  Running playbook for: $MACHINE_NAME"
  echo "  (skipping secrets — run 'just apply' afterwards)"
  echo "═══════════════════════════════════════════════════"
  echo ""

  cd "$DOTFILES_DIR"
  ansible-playbook \
    --connection=local \
    -l "$MACHINE_NAME" \
    -e "target=$MACHINE_NAME" \
    --skip-tags secrets \
    site.yml
}

# ── Main ──────────────────────────────────────────────────────────
main() {
  echo "╔═══════════════════════════════════════════════╗"
  echo "║  hanthor/dotfiles bootstrap                   ║"
  echo "╚═══════════════════════════════════════════════╝"
  echo ""

  ensure_python
  ensure_uv
  ensure_ansible
  ensure_git
  clone_repo
  get_machine_name
  write_machine_name
  install_collections
  run_playbook

  echo ""
  echo "✓ Bootstrap complete! Next steps:"
  echo "  1. Restart your shell:  exec zsh"
  echo "  2. Run secrets phase:   cd ~/.local/share/dotfiles && just apply"
}

main
