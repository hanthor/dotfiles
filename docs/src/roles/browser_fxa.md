# browser_fxa

**Unit:** `units/browser-fxa.sh`  
**Tags:** `desktop`, `browser`, `zen_browser`, `secrets`  
**Secrets needed:** Firefox Account credentials in Bitwarden  
**Runs on:** desktops, except `skip_zen_browser: true` or `machine_profile: vm-test`.

This separate unit attempts Firefox Account sign-in for the selected existing browser profile. It reads `browser_fxa_browser`, `fxa_venv_path`, `fxa_bw_item`, and `fxa_bw_username` from host variables, then `group_vars/all.yml`, then `units/browser-fxa/defaults.yml`. The default browser is `zen`; `firefox` checks Flatpak first, then native Firefox, while `firefox-flatpak` checks only Flatpak. Missing `profiles.ini` skips the unit.

It creates a Python venv, installs PyFxA if needed, and deploys `units/browser-fxa/fxa_signin.py` to `~/.local/bin/fxa_signin.py`. With an unlocked Bitwarden session, it searches the configured item (default `accounts.firefox.com`), selects an exact configured username match when supplied, and obtains credentials and an optional TOTP. Existing `signedInUser.json` is chmod 0600; new token files are created with a restrictive umask. Credentials are not printed.

A locked vault or `--no-secrets` leaves sign-in untouched and reports `PARTIAL`; a missing, incomplete or mismatched item also reports `PARTIAL`. Sign-in failure is best effort and may require manual login. The unit attempts sign-in but does not prove browser login or full Sync operation.
