# hanthor.browser_fxa

Ansible role that signs in to [Firefox Accounts](https://accounts.firefox.com) (FxA) for Zen Browser and/or Firefox, enabling automatic browser sync without manual sign-in.

Uses [PyFxA](https://github.com/mozilla/PyFxA) for the SRP authentication flow and supports TOTP via Bitwarden lookup.

## Requirements

- Bitwarden CLI (`bw`) installed and vault unlocked (session passed as `bw_session`)
- Python 3 on the target host

## Role Variables

```yaml
# Browsers to sign in to. Skips any that aren't installed on the host.
# Options: "zen", "firefox", "firefox-flatpak"
fxa_browsers:
  - zen

# Bitwarden item name to search for FxA credentials
fxa_bw_item: "accounts.firefox.com"

# Filter by this login.username when multiple items match the search term
fxa_bw_username: "you@example.com"

# Path to the Python venv where PyFxA is installed
fxa_venv_path: "{{ ansible_facts['env']['HOME'] }}/.local/venvs/fxa"
```

You must also pass `bw_session` as an extra var (or inventory var) — the unlocked Bitwarden session token used to fetch credentials.

## Browser profile paths

| `fxa_browsers` value | Profile root |
|---|---|
| `zen` | `~/.var/app/app.zen_browser.zen/.zen/` |
| `firefox` | `~/.mozilla/firefox/` |
| `firefox-flatpak` | `~/.var/app/org.mozilla.firefox/.mozilla/firefox/` |

The role reads `profiles.ini` from the profile root, finds the default profile, and writes `signedInUser.json` there. Browsers regenerate OAuth tokens on first launch.

## Example Playbook

```yaml
- hosts: desktops
  roles:
    - role: hanthor.browser_fxa
      vars:
        fxa_browsers:
          - zen
          - firefox
        fxa_bw_item: "accounts.firefox.com"
        fxa_bw_username: "you@example.com"
```

## Bitwarden item setup

The role expects a Bitwarden login item with:
- **Username**: your Firefox Accounts email
- **Password**: your Firefox Accounts password
- **TOTP**: your FxA authenticator seed (so `bw get totp` works)

## Idempotency

The sign-in script skips any profile that already has a valid `signedInUser.json` with `verified: true`. Re-running the role is safe.

## Galaxy publishing

Releases are automatically published to [Ansible Galaxy](https://galaxy.ansible.com/ui/standalone/roles/hanthor/browser_fxa/) via GitHub Actions on every GitHub release.

## License

GPL-3.0-or-later
