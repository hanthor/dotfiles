#!/usr/bin/env bash
# Sign Beeper Desktop (com.automattic.Beeper) in and unlock encryption on desktops.
# Beeper only supports emailed one-time codes, so the unit reads the code from the
# IMAP mailbox described by the Bitwarden login item `beeper`:
#   username / password   the Beeper email address / its IMAP app password
#   field imap_host       IMAP server (required)
#   field imap_user       IMAP login if it differs from username (optional)
#   field recovery_key    Beeper Recovery Code (required)
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

APP=com.automattic.Beeper
API="${BEEPER_API:-http://127.0.0.1:23373}"
helper="$DOTFILES_DIR/units/beeper-login/beeper_login.py"

if skipped_by_profile skip_beeper; then note 'SKIPPED: Beeper disabled for this host/profile'; exit 0; fi
if ! is_desktop; then note 'SKIPPED: Beeper login is only configured on desktops'; exit 0; fi
if [ "${UNITS_NO_SECRETS:-0}" = 1 ]; then note 'SKIPPED: Beeper login needs Bitwarden secrets'; exit 0; fi
if ! flatpak info --system "$APP" >/dev/null 2>&1 && ! flatpak info --user "$APP" >/dev/null 2>&1; then
  note "SKIPPED: $APP is not installed"; exit 0
fi
if [ "${UNITS_CHECK:-0}" = 1 ]; then
  note 'PLANNED: sign Beeper in via the local Desktop API if it is logged out; current state not inspected'
  exit 0
fi
for tool in curl jq python3 bw; do
  command -v "$tool" >/dev/null 2>&1 || { note "FAIL  $tool is required"; exit 1; }
done

state() { curl -fsS -m 5 "$API/v1/app/setup" 2>/dev/null | jq -r '.state // empty'; }

# Launching Beeper opens a window, so only do it when the app has never run here
# (fresh install) or BEEPER_LOGIN_FORCE=1; an already-running app is just queried.
launch_app() {
  [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ] || { note 'SKIPPED: no graphical session to launch Beeper in'; return 2; }
  setsid nohup flatpak run "$APP" >/dev/null 2>&1 < /dev/null &
  return 0
}

cur="$(state)"
if [ -z "$cur" ]; then
  if [ -d "$HOME/.var/app/$APP/config/BeeperTexts" ] && [ "${BEEPER_LOGIN_FORCE:-0}" != 1 ]; then
    note 'SKIPPED: Beeper is not running; start it (or set BEEPER_LOGIN_FORCE=1) to check its login'
    exit 0
  fi
  launch_app; rc=$?
  [ "$rc" = 0 ] || exit 0
fi
if [ "$cur" = ready ]; then note 'ok    Beeper already signed in'; exit 0; fi

session="$(bw_session)"
if [ -z "$session" ]; then note 'PARTIAL: Bitwarden is locked; Beeper login not attempted'; exit 0; fi
item="$(BW_SESSION="$session" bw get item beeper 2>/dev/null)" || { note "FAIL  Bitwarden item 'beeper' not found"; exit 1; }
field() { jq -r --arg n "$1" '.fields[]? | select(.name == $n) | .value' <<<"$item"; }
BEEPER_EMAIL="$(jq -r '.login.username // empty' <<<"$item")"
BEEPER_IMAP_PASSWORD="$(jq -r '.login.password // empty' <<<"$item")"
BEEPER_IMAP_HOST="$(field imap_host)"
BEEPER_IMAP_USER="$(field imap_user)"; BEEPER_IMAP_USER="${BEEPER_IMAP_USER:-$BEEPER_EMAIL}"
BEEPER_RECOVERY_KEY="$(field recovery_key)"
for v in BEEPER_EMAIL BEEPER_IMAP_PASSWORD BEEPER_IMAP_HOST BEEPER_RECOVERY_KEY; do
  [ -n "${!v}" ] || { note "FAIL  Bitwarden item 'beeper' is missing ${v#BEEPER_}"; exit 1; }
done
export BEEPER_EMAIL BEEPER_IMAP_PASSWORD BEEPER_IMAP_HOST BEEPER_IMAP_USER BEEPER_RECOVERY_KEY BEEPER_API="$API"

step 'Beeper sign-in and recovery-key unlock' python3 "$helper"
finish
