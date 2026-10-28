#!/usr/bin/env bash
# Firefox Accounts sign-in previously included by the Zen browser role.
set -uo pipefail
# shellcheck source=units/lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

if skipped_by_profile skip_zen_browser; then
  note "SKIPPED: Zen Browser disabled by host profile"
  exit 0
fi
# Resolve explicit host settings first; inventory parse failures are not skips.
case "${DOTFILES_IS_DESKTOP:-$(host_var is_desktop)}" in
  0|false) note "SKIPPED: not a desktop"; exit 0 ;;
  1|true) ;;
  '')
    if ! command -v yq >/dev/null 2>&1; then
      note "FAIL  desktop detection: yq is required"; exit 1
    fi
    desktop="$(MACHINE="$MACHINE" yq -r '.all.children.desktop.hosts | has(strenv(MACHINE))' "$DOTFILES_DIR/inventory.yml")" || {
      note "FAIL  desktop inventory lookup"; exit 1
    }
    case "$desktop" in
      true) ;;
      false) note "SKIPPED: not a desktop"; exit 0 ;;
      *) note "FAIL  invalid desktop inventory lookup"; exit 1 ;;
    esac ;;
  *) note "FAIL  invalid desktop override"; exit 1 ;;
esac
if ! command -v yq >/dev/null 2>&1; then
  note "FAIL  Firefox Accounts settings: yq is required"; exit 1
fi

# Read the existing variable sources in Ansible's host/group/default precedence.
setting() {
  local key="$1" file value
  for file in "$DOTFILES_DIR/host_vars/$MACHINE.yml" "$DOTFILES_DIR/group_vars/all.yml" \
              "$DOTFILES_DIR/units/browser-fxa/defaults.yml"; do
    [ -f "$file" ] || continue
    value="$(yq -r ".${key} // \"__UNSET__\"" "$file")" || return 1
    if [ "$value" != __UNSET__ ] && [ "$value" != null ]; then
      printf '%s' "$value"; return 0
    fi
  done
  return 1
}

browser="$(setting browser_fxa_browser)" || { note "FAIL  Firefox Accounts browser setting"; exit 1; }
case "$browser" in
  zen) profiles="$HOME/.var/app/app.zen_browser.zen/.zen/profiles.ini" ;;
  firefox-flatpak) profiles="$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox/profiles.ini" ;;
  firefox)
    profiles="$HOME/.var/app/org.mozilla.firefox/.mozilla/firefox/profiles.ini"
    [ -e "$profiles" ] || profiles="$HOME/.mozilla/firefox/profiles.ini"
    ;;
  *) note "FAIL  unsupported Firefox Accounts browser: $browser"; exit 1 ;;
esac
if [ ! -f "$profiles" ]; then
  if [ "${UNITS_CHECK:-0}" = 1 ] && { [ -e "$profiles" ] || [ -L "$profiles" ]; }; then
    note "FAIL  inspect Firefox Accounts profiles.ini"; exit 1
  fi
  note "SKIPPED: $browser profile not installed"; exit 0
fi
if [ "${UNITS_CHECK:-0}" = 1 ] && [ ! -r "$profiles" ]; then
  note "FAIL  inspect Firefox Accounts profiles.ini"; exit 1
fi
venv="$(setting fxa_venv_path)" || { note "FAIL  Firefox Accounts venv setting"; exit 1; }
venv="${venv//"{{ ansible_facts['env']['HOME'] }}"/$HOME}"
case "$venv" in '~/'*) venv="$HOME/${venv#\~/}" ;; esac
case "$venv" in *'{{'*|*'}}'*) note "FAIL  unsupported Firefox Accounts venv template"; exit 1 ;; esac

if [ "${UNITS_CHECK:-0}" = 1 ]; then
  check_browser_fxa() {
    local src="$DOTFILES_DIR/units/browser-fxa/fxa_signin.py" dest="$HOME/.local/bin/fxa_signin.py"
    local rc mode profile account_state
    [ -r "$src" ] || { note "FAIL  read Firefox Accounts sign-in script"; return 1; }
    if [ -e "$dest" ]; then
      cmp -s "$src" "$dest"; rc=$?
      [ "$rc" -le 1 ] || { note "FAIL  compare Firefox Accounts sign-in script"; return 1; }
      mode="$(stat -Lc %a "$dest")" || { note "FAIL  inspect Firefox Accounts sign-in script mode"; return 1; }
      if [ "$rc" = 1 ] || [ "$mode" != 700 ]; then
        note "WOULD install Firefox Accounts sign-in script"
      fi
    else
      note "WOULD install Firefox Accounts sign-in script"
    fi
    if [ ! -x "$venv/bin/python" ]; then
      note "WOULD create Firefox Accounts venv and install PyFxA"
    else
      account_state="$(PYTHONDONTWRITEBYTECODE=1 "$venv/bin/python" -B -c '
import importlib.machinery, sys
package = importlib.machinery.PathFinder.find_spec("fxa", sys.path)
module = None if package is None or package.submodule_search_locations is None else (
    importlib.machinery.PathFinder.find_spec("fxa.core", package.submodule_search_locations)
)
print("installed" if module is not None else "missing")
' 2>/dev/null)" || { note "FAIL  inspect Firefox Accounts PyFxA"; return 1; }
      case "$account_state" in
        installed) ;;
        missing) note "WOULD install Firefox Accounts PyFxA" ;;
        *) note "FAIL  inspect Firefox Accounts PyFxA"; return 1 ;;
      esac
    fi
    # Use the shipped resolver, without importing the installed (possibly stale) copy.
    profile="$(env -u PROFILE_DIR -u ZEN_PROFILE_DIR BROWSER_TYPE="$browser" PYTHONDONTWRITEBYTECODE=1 python3 -B -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location("fxa_signin", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.resolve_profile_dir())
' "$src" 2>/dev/null)" || { note "FAIL  inspect Firefox Accounts default profile"; return 1; }
    [ -d "$profile" ] || { note "FAIL  Firefox Accounts default profile does not exist"; return 1; }
    if [ -L "$profile/signedInUser.json" ]; then
      note "FAIL  Firefox Accounts token is a symlink"; return 1
    elif [ -e "$profile/signedInUser.json" ]; then
      mode="$(stat -Lc %a "$profile/signedInUser.json")" || { note "FAIL  inspect Firefox Accounts token mode"; return 1; }
      [ "$mode" = 600 ] || note "WOULD restrict Firefox Accounts token permissions"
      account_state="$(python3 -B -c '
import json, sys
try:
    with open(sys.argv[1]) as f:
        data = json.load(f)
    account = data.get("accountData") if isinstance(data, dict) else None
    print("verified" if isinstance(account, dict) and account.get("verified") else "existing")
except (json.JSONDecodeError, UnicodeDecodeError):
    print("existing")
' "$profile/signedInUser.json" 2>/dev/null)" || { note "FAIL  inspect Firefox Accounts token"; return 1; }
    else
      account_state=absent
    fi
    case "$account_state" in
      verified) note "Firefox Accounts profile is verified" ;;
      existing) note "Firefox Accounts data exists but is not verified; it will be left untouched" ;;
      absent) note "WOULD attempt Firefox Accounts sign-in if credentials are available" ;;
      *) note "FAIL  inspect Firefox Accounts token"; return 1 ;;
    esac
    note "Firefox Accounts credentials were not inspected"
  }
  step "check Firefox Accounts" check_browser_fxa
  finish
fi

create_venv() {
  [ -x "$venv/bin/python" ] || { mkdir -p "$(dirname "$venv")" && python3 -m venv "$venv"; }
}
install_pyfxa() {
  [ -x "$venv/bin/python" ] || return 1
  "$venv/bin/python" -c 'import fxa.core' >/dev/null 2>&1 || "$venv/bin/python" -m pip install PyFxA
}
step "Firefox Accounts venv" create_venv
step "Firefox Accounts PyFxA" install_pyfxa
helper_installed=0
install_helper() {
  install_if_changed "$DOTFILES_DIR/units/browser-fxa/fxa_signin.py" "$HOME/.local/bin/fxa_signin.py" 0700 || return 1
  helper_installed=1
}
step "Firefox Accounts sign-in script" install_helper
if [ "$helper_installed" != 1 ]; then
  note "Firefox Accounts sign-in skipped: helper installation failed"
  finish
fi

s="$(bw_session)"
if [ -z "$s" ]; then
  note "PARTIAL: Firefox Accounts sign-in skipped (vault locked or secrets disabled)"
  finish
fi
item_name="$(setting fxa_bw_item)" || { note "FAIL  Firefox Accounts item setting"; UNIT_FAILED=1; finish; }
username="$(setting fxa_bw_username)" || { note "FAIL  Firefox Accounts username setting"; UNIT_FAILED=1; finish; }
# Only an exact username match is accepted; never leak a mismatched item's contents.
selected="$(BW_SESSION="$s" bw list items --search "$item_name" 2>/dev/null | FXA_MATCH="$username" python3 -c '
import base64, json, os, sys
try:
    items = json.load(sys.stdin)
    match = os.environ["FXA_MATCH"]
    item = next((i for i in items if not match or (i.get("login") or {}).get("username") == match), None)
    if not item:
        sys.exit(1)
    login = item.get("login") or {}
    fields = (item.get("id") or "", login.get("username") or "", login.get("password") or "")
    if not all(isinstance(v, str) and v for v in fields):
        sys.exit(1)
    for value in fields:
        print(base64.b64encode(value.encode()).decode())
except (ValueError, TypeError, AttributeError):
    sys.exit(1)
')" || {
  note "PARTIAL: Firefox Accounts item missing, incomplete, or username mismatch"
  finish
}
mapfile -t fields <<< "$selected"
if [ "${#fields[@]}" -ne 3 ]; then
  note "PARTIAL: Firefox Accounts item invalid"; finish
fi
item_id="$(printf '%s' "${fields[0]}" | base64 -d)" || { UNIT_FAILED=1; finish; }
email="$(printf '%s' "${fields[1]}" | base64 -d)" || { UNIT_FAILED=1; finish; }
password="$(printf '%s' "${fields[2]}" | base64 -d)" || { UNIT_FAILED=1; finish; }
totp="$(BW_SESSION="$s" bw get totp "$item_id" 2>/dev/null | tr -cd '0-9')" || totp=''

sign_in() {
  local profile
  [ -x "$venv/bin/python" ] && [ -f "$HOME/.local/bin/fxa_signin.py" ] || return 1
  # Resolve the selected existing profile using the same logic as the role's script.
  profile="$(env -u PROFILE_DIR -u ZEN_PROFILE_DIR BROWSER_TYPE="$browser" python3 -c '
import importlib.util, os
p = os.path.join(os.environ["HOME"], ".local/bin/fxa_signin.py")
spec = importlib.util.spec_from_file_location("fxa_signin", p)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module.resolve_profile_dir())
')" || return 1
  [ -d "$profile" ] || { note "Firefox Accounts default profile does not exist"; return 1; }
  # Never follow a token symlink, including a dangling one.
  if [ -L "$profile/signedInUser.json" ]; then
    note "Firefox Accounts token is a symlink; leaving it untouched"; return 1
  fi
  if [ -e "$profile/signedInUser.json" ]; then chmod 600 "$profile/signedInUser.json" || return 1; fi
  ( umask 077
    FXA_EMAIL="$email" FXA_PASSWORD="$password" FXA_TOTP="$totp" BROWSER_TYPE="$browser" \
      PROFILE_DIR="$profile" "$venv/bin/python" "$HOME/.local/bin/fxa_signin.py" >/dev/null 2>&1
  ) || { note "Firefox Accounts sign-in failed; sign in manually or retry after checking credentials"; return 1; }
}
# The Ansible role reported sign-in failures without failing the rest of the play.
soft "Firefox Accounts sign-in" sign_in
finish
