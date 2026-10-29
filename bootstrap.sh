#!/usr/bin/env bash
# Bootstrap script for hanthor/dotfiles
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh | bash
#   curl ... | bash -s -- --name kanpur --type desktop
#   ./bootstrap.sh --name kanpur --type desktop
set -euo pipefail
if [ -d /data/data/com.termux/files/usr ] && { [ -z "${HOME:-}" ] || [ "$HOME" = /data ]; }; then
  export HOME=/data/data/com.termux/files/home
fi

REPO_URL="https://github.com/hanthor/dotfiles.git"
DOTFILES_DIR="$HOME/.local/share/dotfiles"
MACHINE_FILE="/etc/dotfiles-machine"
MACHINE_NAME=""
MACHINE_TYPE=""   # desktop | server | vps | termux_hosts

# ── Parse arguments ───────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --name) MACHINE_NAME="$2"; shift 2 ;;
    --type) MACHINE_TYPE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

is_termux() { [ -d /data/data/com.termux/files/usr ]; }
if is_termux; then export TMPDIR="${TMPDIR:-/data/data/com.termux/files/usr/tmp}"; fi

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
  if is_termux; then pkg install -y python; return $?; fi
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
  if is_termux; then pkg install -y git; return $?; fi
  case "$OS" in
    fedora|rhel|centos)    sudo dnf install -y git ;;
    debian|ubuntu)         sudo apt-get update && sudo apt-get install -y git ;;
    alpine|postmarketos)   sudo apk add --no-cache git ;;
    arch|manjaro|endeavouros) sudo pacman -Sy --noconfirm git ;;
    opensuse*|suse*)       sudo zypper install -y git ;;
  esac
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
      sh "$tmp_ts"
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
  if [ -e "$DOTFILES_DIR/.git" ]; then
    echo "Existing dotfiles checkout left unchanged; update it manually after registration is merged."
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

  # Detect an existing host's type without depending on where its group appears.
  local detected
  detected=$(python3 - "$DOTFILES_DIR/scripts" "$DOTFILES_DIR/inventory.yml" "$MACHINE_NAME" <<'PYEOF'
import sys
sys.path.insert(0, sys.argv[1])
from inventory_parser import host_groups
with open(sys.argv[2], encoding='utf-8') as source:
    groups = host_groups(source.read(), sys.argv[3]) & {'desktop', 'server', 'vps', 'termux_hosts'}
if len(groups) > 1:
    print('Machine belongs to multiple type groups; pass --type explicitly.', file=sys.stderr)
    sys.exit(1)
print(next(iter(groups), ''))
PYEOF
  ) || return 1
  if [ -n "$detected" ]; then
    MACHINE_TYPE=$detected
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

# ── Require reviewed registration before changing the machine ────
register_in_inventory() {
  local rc=0 reviewed
  python3 "$DOTFILES_DIR/scripts/register-machine.py" --check "$MACHINE_NAME" "$MACHINE_TYPE" "$DOTFILES_DIR/inventory.yml" || rc=$?
  case "$rc" in
    0) ;;
    3)
      echo "Machine is not registered in this checkout. Registration must be reviewed and merged before bootstrap." >&2
      echo "On an authenticated fleet checkout run: just onboard $MACHINE_NAME $MACHINE_TYPE" >&2
      echo "After merging, update this checkout and rerun bootstrap." >&2
      return 1 ;;
    *) return "$rc" ;;
  esac
  git -C "$DOTFILES_DIR" fetch origin '+refs/heads/master:refs/remotes/origin/master' || return $?
  reviewed=$(mktemp) || return $?
  if ! git -C "$DOTFILES_DIR" show refs/remotes/origin/master:inventory.yml > "$reviewed"; then
    rm -f -- "$reviewed"; return 1
  fi
  rc=0
  python3 "$DOTFILES_DIR/scripts/register-machine.py" --check "$MACHINE_NAME" "$MACHINE_TYPE" "$reviewed" || rc=$?
  rm -f -- "$reviewed"
  if [ "$rc" -ne 0 ]; then
    echo "Registration is not present in the requested group on origin/master; review and merge it before bootstrap." >&2
    return 1
  fi
  echo "Machine registration is present on origin/master."
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


# ── Phase 1: system + packages + dotfiles (no secrets) ───────────
run_phase1() {
  local is_desktop="false"
  [ "$MACHINE_TYPE" = "desktop" ] && is_desktop="true"
  echo "Phase 1: system, packages and dotfiles (no secrets)"
  cd "$DOTFILES_DIR" || return 1
  DOTFILES_MACHINE="$MACHINE_NAME" DOTFILES_IS_DESKTOP="$is_desktop" \
    scripts/run-units.sh --no-secrets
}

# ── Bitwarden login ───────────────────────────────────────────────
setup_bitwarden() {
  export PATH="/home/linuxbrew/.linuxbrew/bin:$HOME/.local/bin:$PATH"

  if ! command -v bw &>/dev/null; then
    echo ""
    echo "NOTE: Bitwarden CLI not yet available."
    if is_termux; then
      echo "      Run 'DOTFILES_MACHINE=$MACHINE_NAME BW_SESSION_CACHE=\$PREFIX/tmp/bw_session just apply' after setup."
    else
      echo "      Run 'just apply' after setup to complete secrets."
    fi
    return 1
  fi

  local bw_status
  # Prefer a usable session, including the cached session from a previous run.
  if [ -n "${BW_SESSION:-}" ] && ! bw unlock --check >/dev/null 2>&1; then
    unset BW_SESSION
  fi
  if ! is_termux && [ -z "${BW_SESSION:-}" ] && [ -s /tmp/bw_session ]; then
    local cached_session
    cached_session=$(cat /tmp/bw_session)
    if BW_SESSION="$cached_session" bw unlock --check >/dev/null 2>&1; then
      export BW_SESSION="$cached_session"
    fi
  fi
  bw_status=$(bw status 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])" 2>/dev/null || echo "unauthenticated")

  echo ""
  echo "═══════════════════════════════════════════════════"
  echo "  Phase 2: secrets (SSH keys, GitHub, Tailscale,"
  echo "           atuin sync)"
  echo "  Bitwarden status: $bw_status"
  echo "═══════════════════════════════════════════════════"
  echo ""

  if [ -z "${BW_SESSION:-}" ]; then
    if [ "$bw_status" = "unauthenticated" ]; then
      echo "Log in to Bitwarden to complete setup:"
      bw login || return 1
    fi
    echo "Unlocking Bitwarden..."
    BW_SESSION=$(bw unlock --raw) || return 1
    export BW_SESSION
  fi
  if [ -z "$BW_SESSION" ] || ! bw unlock --check >/dev/null 2>&1; then
    echo "Bitwarden session is invalid; secrets setup skipped." >&2
    return 1
  fi
  if ! timeout 15 bw sync >/dev/null; then
    echo "Bitwarden sync failed; secrets setup skipped." >&2
    return 1
  fi
  # Termux has no writable /tmp; units inherit BW_SESSION for this run.
  if is_termux; then return 0; fi
  python3 -c '
import os, tempfile
path = "/tmp/bw_session"
fd, temp = tempfile.mkstemp(prefix=".bw_session.", dir="/tmp")
try:
    with os.fdopen(fd, "w") as f:
        f.write(os.environ["BW_SESSION"])
    os.replace(temp, path)
finally:
    if os.path.exists(temp):
        os.unlink(temp)
' || return 1
  return 0
}

# ── Phase 2: secrets ──────────────────────────────────────────────
run_phase2() {
  local is_desktop="false"
  [ "$MACHINE_TYPE" = "desktop" ] && is_desktop="true"
  cd "$DOTFILES_DIR" || return 1
  DOTFILES_MACHINE="$MACHINE_NAME" DOTFILES_IS_DESKTOP="$is_desktop" \
    scripts/run-units.sh --tags omp,secrets
}


# ── Main ──────────────────────────────────────────────────────────
main() {
  echo "╔═══════════════════════════════════════════════╗"
  echo "║  hanthor/dotfiles bootstrap                   ║"
  echo "╚═══════════════════════════════════════════════╝"
  echo ""

  get_machine_name || return $?
  case "$MACHINE_NAME" in matrix|telengana) echo "Retired VPSes must not be modified." >&2; return 1 ;; esac
  if [[ ! "$MACHINE_NAME" =~ ^[a-z0-9]([a-z0-9-]*[a-z0-9])?$ ]] || [ "${#MACHINE_NAME}" -gt 63 ]; then
    echo "Machine name must be a lowercase DNS hostname." >&2; return 1
  fi
  ensure_python || return $?
  ensure_git || return $?
  clone_repo || return $?
  get_machine_type || return $?
  if is_termux; then
    [ "$MACHINE_TYPE" = termux_hosts ] || { echo "Termux requires a reviewed termux_hosts identity." >&2; return 1; }
  elif [ "$MACHINE_TYPE" = termux_hosts ]; then
    echo "termux_hosts identity requires the Termux environment." >&2; return 1
  fi
  register_in_inventory || return $?
  if is_termux; then
    echo "Termux: leaving Android hostname, Tailscale and system privileges unchanged."
  else
    write_machine_name
    set_hostname
    ensure_sudo
    ensure_tailscale
  fi
  local rc=0 phase_rc=0
  run_phase1 || rc=$?

  # Phase 2 still runs after a Phase 1 failure, if the vault is available.
  if setup_bitwarden; then
    run_phase2 || phase_rc=$?
    [ "$rc" -ne 0 ] || rc=$phase_rc
  else
    echo "Bitwarden setup failed; Phase 2 was not run." >&2
    [ "$rc" -ne 0 ] || rc=1
  fi
  if [ "$rc" -ne 0 ]; then
    echo "Bootstrap failed (exit $rc); address the errors and re-run." >&2
    return "$rc"
  fi

  echo ""
  echo "╔═══════════════════════════════════════════════╗"
  echo "║  Bootstrap complete!                          ║"
  echo "╚═══════════════════════════════════════════════╝"
  echo ""
  echo "  Start a new login shell to load your configuration."
  echo ""
  if is_termux; then
    echo "  To re-apply: DOTFILES_MACHINE=$MACHINE_NAME BW_SESSION_CACHE=\$PREFIX/tmp/bw_session just apply"
  else
    echo "  To re-apply anytime: just apply"
  fi
}

if [[ -z "${BASH_SOURCE[0]:-}" || "${BASH_SOURCE[0]}" == "$0" ]]; then
  main
fi
