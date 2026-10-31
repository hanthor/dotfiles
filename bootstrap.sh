#!/usr/bin/env bash
# Bootstrap script for hanthor/dotfiles
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash
#   curl ... | bash -s -- --name kanpur --type desktop
#   ./bootstrap.sh --name kanpur --type desktop
set -euo pipefail

REPO_URL="https://github.com/hanthor/dotfiles.git"
DOTFILES_DIR="$HOME/.local/share/dotfiles"
MACHINE_FILE="/etc/dotfiles-machine"
MACHINE_NAME=""
MACHINE_TYPE=""   # desktop | server | vps
INVENTORY_MODIFIED=false

# ── Installation script checksums (SHA256) ────────────────────────
# These checksums should be verified and updated whenever upstream
# installation scripts change. Users can verify independently:
#   curl -fsSL <url> | sha256sum
#
# Last verified: 2026-10-16
UV_INSTALL_SHA256="01f1d303aef86ba9f59cbe7b4ac06ff2ce05318b21edf0a94f9f29b61a8b3a5f"
TAILSCALE_INSTALL_SHA256="a54e3d92c29019cccb26e7c937a51d16e7be3c30e3ca5dde92d5f87d22c18fa4"

# ── Parse arguments ───────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --name) MACHINE_NAME="$2"; shift 2 ;;
    --type) MACHINE_TYPE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

# ── Verify script checksum ────────────────────────────────────────
verify_checksum() {
  local file="$1"
  local expected_hash="$2"
  local script_name="$3"
  
  if [ ! -f "$file" ]; then
    echo "ERROR: File not found: $file" >&2
    return 1
  fi
  
  local actual_hash
  actual_hash=$(sha256sum "$file" | awk '{print $1}')
  
  if [ "$actual_hash" != "$expected_hash" ]; then
    echo "ERROR: Checksum mismatch for $script_name" >&2
    echo "  Expected: $expected_hash" >&2
    echo "  Got:      $actual_hash" >&2
    echo "  File:     $file" >&2
    echo "  This could indicate tampering or network corruption." >&2
    return 1
  fi
  
  return 0
}

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

# ── Install Python ────────────────────────────────────────────────
ensure_python() {
  if command -v python3 &>/dev/null; then
    echo "Python3 found."
    return
  fi
  echo "Installing Python3..."
  case "$OS" in
    fedora|rhel|centos)    sudo dnf install -y python3 ;;
    debian|ubuntu)         sudo apt-get update && sudo apt-get install -y python3 ;;
    alpine|postmarketos)   sudo apk add --no-cache python3 ;;
    arch|manjaro|endeavouros) sudo pacman -Sy --noconfirm python ;;
    opensuse*|suse*)       sudo zypper install -y python3 ;;
    *)                     echo "ERROR: Unsupported OS '$OS'. Install python3 manually."; exit 1 ;;
  esac
}

# ── Install git ───────────────────────────────────────────────────
ensure_git() {
  if command -v git &>/dev/null; then return; fi
  echo "Installing git..."
  case "$OS" in
    fedora|rhel|centos)    sudo dnf install -y git ;;
    debian|ubuntu)         sudo apt-get update && sudo apt-get install -y git ;;
    alpine|postmarketos)   sudo apk add --no-cache git ;;
    arch|manjaro|endeavouros) sudo pacman -Sy --noconfirm git ;;
    opensuse*|suse*)       sudo zypper install -y git ;;
  esac
}

# ── Install uv ────────────────────────────────────────────────────
ensure_uv() {
  if command -v uv &>/dev/null || [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
    echo "uv found."
    return
  fi
  echo "Installing uv..."
  # Retry up to 3 times — DNS may not be ready immediately on fresh installs
  local attempts=0
  local tmp_install
  tmp_install=$(mktemp)
  while [ $attempts -lt 3 ]; do
    if curl -LsSf --max-time 30 https://astral.sh/uv/install.sh -o "$tmp_install" && [ -s "$tmp_install" ]; then
      if verify_checksum "$tmp_install" "$UV_INSTALL_SHA256" "astral.sh/uv/install.sh"; then
        if sh "$tmp_install"; then
          rm -f "$tmp_install"
          export PATH="$HOME/.local/bin:$PATH"
          return
        fi
      else
        echo "Checksum verification failed, retrying in 5s..." >&2
      fi
    fi
    attempts=$((attempts + 1))
    echo "uv install attempt $attempts failed, retrying in 5s..."
    sleep 5
  done
  rm -f "$tmp_install"
  # Fallback: install via pip3
  echo "astral.sh unreachable, falling back to pip3 install uv..."
  pip3 install --user uv
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

# ── Install Tailscale + join Tailnet ──────────────────────────────
ensure_tailscale() {
  # Already connected?
  if tailscale status &>/dev/null 2>&1; then
    echo "✓ Already connected to Tailnet."
    return
  fi

  # Install if missing
  if ! command -v tailscale &>/dev/null; then
    echo "Installing Tailscale..."
    local tmp_ts
    tmp_ts=$(mktemp)
    if curl -fsSL --max-time 30 https://tailscale.com/install.sh -o "$tmp_ts" && [ -s "$tmp_ts" ]; then
      if verify_checksum "$tmp_ts" "$TAILSCALE_INSTALL_SHA256" "tailscale.com/install.sh"; then
        sh "$tmp_ts"
      else
        echo "WARNING: Tailscale checksum verification failed, skipping install." >&2
      fi
    fi
    rm -f "$tmp_ts"
  fi

  echo ""
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "  Scan the QR code with your phone to join Tailnet"
  echo "  (or approve the device in the admin console)"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  sudo tailscale up --qr --hostname "${MACHINE_NAME:-$(hostname)}"

  echo "Waiting for Tailscale connection..."
  for _ in $(seq 1 30); do
    if tailscale status &>/dev/null 2>&1; then
      echo "✓ Connected to Tailnet!"
      return
    fi
    sleep 2
  done
  echo "WARNING: Tailscale connection timed out. Continuing anyway..."
}

# ── Clone dotfiles ────────────────────────────────────────────────
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

  if [ -f "$MACHINE_FILE" ]; then
    MACHINE_NAME=$(cat "$MACHINE_FILE")
    echo "Machine already identified as: $MACHINE_NAME"
    return
  fi

  if [ ! -c /dev/tty ]; then
    echo "ERROR: Cannot prompt interactively (no /dev/tty)."
    echo "Re-run with: curl -fsSL <url> | bash -s -- --name <machine>"
    exit 1
  fi

  echo ""
  echo "Known machines: himachal karnataka dilli kanpur goa bihar matrix lkofoss"
  echo "Enter a name from the list above, or a new machine name:"
  printf "Machine name: " >/dev/tty
  read -r MACHINE_NAME </dev/tty

  if [ -z "$MACHINE_NAME" ]; then
    echo "ERROR: Machine name is required."
    exit 1
  fi
}

# ── Prompt for machine type ───────────────────────────────────────
get_machine_type() {
  # Already set via --type flag
  if [ -n "$MACHINE_TYPE" ]; then return; fi

  # Detect from inventory if machine is already registered
  if grep -q "^    $MACHINE_NAME:" "$DOTFILES_DIR/inventory.yml" 2>/dev/null; then
    MACHINE_TYPE=$(python3 - <<PYEOF
import sys
name = "$MACHINE_NAME"
content = open("$DOTFILES_DIR/inventory.yml").read()
for group in ("desktop", "server", "vps", "llm"):
    marker = f"    {group}:\n      hosts:"
    if marker in content:
        idx = content.index(marker)
        block = content[idx:idx+300]
        if f"        {name}:" in block:
            print(group)
            sys.exit(0)
print("desktop")
PYEOF
)
    echo "Detected machine type from inventory: $MACHINE_TYPE"
    return
  fi

  # Interactive prompt for new machines
  if [ ! -c /dev/tty ]; then
    echo "WARNING: No /dev/tty — defaulting to 'desktop'. Pass --type to override."
    MACHINE_TYPE="desktop"
    return
  fi

  echo ""
  echo "Machine type:"
  echo "  1) desktop  — GNOME, Flatpaks, Zen Browser, syncthing"
  echo "  2) server   — headless, no desktop apps"
  echo "  3) vps      — remote server, no syncthing"
  printf "Type [1]: " >/dev/tty
  read -r _choice </dev/tty

  case "${_choice:-1}" in
    1|desktop) MACHINE_TYPE="desktop" ;;
    2|server)  MACHINE_TYPE="server" ;;
    3|vps)     MACHINE_TYPE="vps" ;;
    *)         MACHINE_TYPE="desktop" ;;
  esac
}

# ── Register machine in inventory (local) ────────────────────────
register_in_inventory() {
  if grep -q "^    $MACHINE_NAME:" "$DOTFILES_DIR/inventory.yml" 2>/dev/null; then
    echo "Machine already in inventory."
    return
  fi

  echo "Adding $MACHINE_NAME to inventory as $MACHINE_TYPE..."
  python3 - <<PYEOF
name = "$MACHINE_NAME"
mtype = "$MACHINE_TYPE"
path = "$DOTFILES_DIR/inventory.yml"
content = open(path).read()

host_entry = f"    {name}:\n      ansible_host: localhost\n      ansible_connection: local\n"
content = content.replace("all:\n  hosts:\n", f"all:\n  hosts:\n{host_entry}", 1)

group_marker = f"    {mtype}:\n      hosts:\n"
if group_marker in content:
    content = content.replace(group_marker, f"{group_marker}        {name}:\n", 1)

open(path, "w").write(content)
PYEOF

  if [ ! -f "$DOTFILES_DIR/host_vars/$MACHINE_NAME.yml" ]; then
    echo "---" > "$DOTFILES_DIR/host_vars/$MACHINE_NAME.yml"
  fi

  INVENTORY_MODIFIED=true
  echo "✓ Registered in inventory (will be pushed after GitHub auth)."
}

write_machine_name() {
  if [ -f "$MACHINE_FILE" ] && [ "$(cat "$MACHINE_FILE")" = "$MACHINE_NAME" ]; then
    return
  fi
  echo "$MACHINE_NAME" | sudo tee "$MACHINE_FILE" > /dev/null
  echo "Machine name written to $MACHINE_FILE"
}

# ── Set system hostname ───────────────────────────────────────────
set_hostname() {
  local current
  current=$(hostname)
  if [ "$current" = "$MACHINE_NAME" ]; then
    echo "✓ Hostname already set to: $MACHINE_NAME"
    return
  fi
  echo "Setting hostname: $current → $MACHINE_NAME"
  sudo hostnamectl set-hostname "$MACHINE_NAME"
  echo "✓ Hostname set to: $MACHINE_NAME"
}

# ── Ensure passwordless sudo ──────────────────────────────────────
ensure_sudo() {
  local sudo_file="/etc/sudoers.d/zz-$USER"
  if [ -f "$sudo_file" ]; then
    echo "✓ Passwordless sudo already configured for $USER."
    return
  fi

  echo "Configuring passwordless sudo for $USER..."
  echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee "$sudo_file" > /dev/null
  sudo chmod 0440 "$sudo_file"
}

# ── Install Galaxy collections ────────────────────────────────────
install_collections() {
  echo "Installing Ansible collections..."
  ansible-galaxy collection install -r "$DOTFILES_DIR/requirements.yml" --force-with-deps 2>/dev/null || \
    ansible-galaxy collection install community.general
}

# ── Phase 1: system + packages + dotfiles (no secrets) ───────────
run_phase1() {
  local is_desktop="false"
  [ "$MACHINE_TYPE" = "desktop" ] && is_desktop="true"

  echo ""
  echo "═══════════════════════════════════════════════════"
  echo "  Phase 1: system, packages, dotfiles"
  echo "  Machine: $MACHINE_NAME ($MACHINE_TYPE)"
  echo "═══════════════════════════════════════════════════"
  echo ""

  cd "$DOTFILES_DIR"
  ansible-playbook \
    --connection=local \
    -l "$MACHINE_NAME" \
    -e "target=$MACHINE_NAME" \
    -e ansible_connection=local \
    -e ansible_host=127.0.0.1 \
    -e "is_desktop=$is_desktop" \
    --skip-tags secrets \
    site.yml
}

# ── Bitwarden login ───────────────────────────────────────────────
setup_bitwarden() {
  export PATH="/home/linuxbrew/.linuxbrew/bin:$HOME/.local/bin:$PATH"

  if ! command -v bw &>/dev/null; then
    echo ""
    echo "NOTE: Bitwarden CLI not yet available."
    echo "      Run 'just apply' after setup to complete secrets."
    return 1
  fi

  local bw_status
  bw_status=$(bw status 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "unauthenticated")

  echo ""
  echo "═══════════════════════════════════════════════════"
  echo "  Phase 2: secrets (SSH keys, GitHub, Tailscale,"
  echo "           atuin sync)"
  echo "  Bitwarden status: $bw_status"
  echo "═══════════════════════════════════════════════════"
  echo ""

  case "$bw_status" in
    unlocked)
      BW_SESSION=$(bw unlock --raw 2>/dev/null || true)
      ;;
    locked)
      echo "Unlocking Bitwarden..."
      BW_SESSION=$(bw unlock --raw)
      ;;
    unauthenticated)
      echo "Log in to Bitwarden to complete setup:"
      bw login
      BW_SESSION=$(bw unlock --raw)
      ;;
  esac

  export BW_SESSION
  rm -f /tmp/bw_session
  (umask 077 && printf '%s' "$BW_SESSION" > /tmp/bw_session)
  return 0
}

# ── Phase 2: secrets ──────────────────────────────────────────────
run_phase2() {
  local is_desktop="false"
  [ "$MACHINE_TYPE" = "desktop" ] && is_desktop="true"

  cd "$DOTFILES_DIR"
  ansible-playbook \
    --connection=local \
    -l "$MACHINE_NAME" \
    -e "target=$MACHINE_NAME" \
    -e ansible_connection=local \
    -e ansible_host=127.0.0.1 \
    -e "is_desktop=$is_desktop" \
    -e "bw_session=${BW_SESSION:-}" \
    --tags secrets \
    site.yml
}

# ── Push inventory changes (after GitHub auth is set up) ─────────
push_inventory_changes() {
  if [ "$INVENTORY_MODIFIED" != "true" ]; then return; fi

  cd "$DOTFILES_DIR"

  # Switch to SSH remote now that GitHub auth is configured
  git remote set-url origin git@github.com:hanthor/dotfiles.git

  git add inventory.yml "host_vars/$MACHINE_NAME.yml" 2>/dev/null || true
  if git diff --cached --quiet; then
    return  # Nothing to commit (already pushed from another machine)
  fi

  git commit -m "inventory: add $MACHINE_NAME ($MACHINE_TYPE)"
  git push
  echo "✓ Inventory pushed to GitHub."
}

# ── Main ──────────────────────────────────────────────────────────
main() {
  echo "╔═══════════════════════════════════════════════╗"
  echo "║  hanthor/dotfiles bootstrap                   ║"
  echo "╚═══════════════════════════════════════════════╝"
  echo ""

  ensure_python
  ensure_git
  ensure_uv
  ensure_ansible
  clone_repo
  get_machine_name
  get_machine_type
  register_in_inventory
  write_machine_name
  set_hostname
  ensure_sudo
  ensure_tailscale
  install_collections
  run_phase1

  # Phase 2 runs if Bitwarden CLI is now available (installed by Homebrew in Phase 1)
  if setup_bitwarden; then
    run_phase2
    push_inventory_changes
  fi

  echo ""
  echo "╔═══════════════════════════════════════════════╗"
  echo "║  Bootstrap complete!                          ║"
  echo "╚═══════════════════════════════════════════════╝"
  echo ""
  echo "  Start a new shell:"
  echo "    eval \"\$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)\" && exec zsh"
  echo ""
  echo "  To re-apply anytime: just apply"
}

main
