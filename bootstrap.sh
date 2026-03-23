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

# ── Install Ansible ───────────────────────────────────────────────
ensure_ansible() {
  # Check common locations
  if command -v ansible-playbook &>/dev/null; then
    echo "Ansible found."
    return
  fi
  for p in "$HOME/.local/bin" "$HOME/.local/share/pipx/venvs/ansible/bin" "/home/linuxbrew/.linuxbrew/bin"; do
    if [ -x "$p/ansible-playbook" ]; then
      export PATH="$p:$PATH"
      echo "Ansible found in $p."
      return
    fi
  done

  echo "Installing Ansible..."

  # Try pipx first (clean, PEP 668 safe)
  if command -v pipx &>/dev/null; then
    pipx install --include-deps ansible
    export PATH="$HOME/.local/bin:$PATH"
    return
  fi

  # Install pipx then use it
  case "$OS" in
    debian|ubuntu)  sudo apt-get update && sudo apt-get install -y pipx ;;
    fedora|rhel|centos) sudo dnf install -y pipx ;;
  esac

  if command -v pipx &>/dev/null; then
    pipx install --include-deps ansible
    export PATH="$HOME/.local/bin:$PATH"
    return
  fi

  # Last resort: uv if available
  if command -v uv &>/dev/null; then
    uv tool install ansible
    export PATH="$HOME/.local/bin:$PATH"
    return
  fi

  echo "ERROR: Could not install Ansible. Install pipx or ansible manually."
  exit 1
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
  read -rp "Machine name: " MACHINE_NAME

  if [ -z "$MACHINE_NAME" ]; then
    echo "ERROR: Machine name is required."
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
  echo "═══════════════════════════════════════════════════"
  echo ""

  cd "$DOTFILES_DIR"
  ansible-playbook \
    --connection=local \
    -l "$MACHINE_NAME" \
    -e "target=$MACHINE_NAME" \
    site.yml
}

# ── Main ──────────────────────────────────────────────────────────
main() {
  echo "╔═══════════════════════════════════════════════╗"
  echo "║  hanthor/dotfiles bootstrap                   ║"
  echo "╚═══════════════════════════════════════════════╝"
  echo ""

  ensure_python
  ensure_ansible
  ensure_git
  clone_repo
  get_machine_name
  write_machine_name
  install_collections
  run_playbook

  echo ""
  echo "✓ Bootstrap complete! Restart your shell or run:"
  echo "  exec zsh"
}

main
