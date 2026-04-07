# hanthor.browser_fxa

Sign in to **Firefox Accounts** for [Zen Browser](https://zen-browser.app) or Firefox using [PyFxA](https://github.com/mozilla/PyFxA), with optional [Bitwarden](https://bitwarden.com) credential and TOTP lookup.

## What it does

1. Detects the browser profile directory (`profiles.ini` → Install section default)
2. Skips gracefully if the browser is not installed
3. Creates a venv and installs PyFxA
4. Fetches credentials (email, password, TOTP) from Bitwarden (optional)
5. Calls `fxa_signin.py` to authenticate and write `signedInUser.json`
6. Idempotent — skips if already signed in and verified

## Requirements

- Python 3.8+ on the target host
- Bitwarden CLI (`bw`) in PATH if using the Bitwarden credential lookup
- `bw_session` variable or `BW_SESSION` set and vault unlocked

## Role variables

| Variable | Default | Description |
|---|---|---|
| `browser_fxa_browser` | `"zen"` | Browser to sign in to: `zen`, `firefox`, or `firefox-flatpak` |
| `fxa_bw_item` | `"accounts.firefox.com"` | Bitwarden search term for the FxA item |
| `fxa_bw_username` | `""` | Filter BW results by login.username (useful when multiple items match) |
| `fxa_venv_path` | `~/.local/venvs/fxa` | Path where the PyFxA venv is created |

## Usage

### Zen Browser (default)

```yaml
- hosts: workstations
  roles:
    - role: hanthor.browser_fxa
      vars:
        fxa_bw_item: "accounts.firefox.com"
        fxa_bw_username: "you@example.com"
```

### Firefox

```yaml
- hosts: workstations
  roles:
    - role: hanthor.browser_fxa
      vars:
        browser_fxa_browser: firefox
        fxa_bw_item: "accounts.firefox.com"
        fxa_bw_username: "you@example.com"
```

### Without Bitwarden (supply credentials directly)

Set `_fxa_email`, `_fxa_password`, and `_fxa_totp` as variables before including the role,
or supply them via `FXA_EMAIL` / `FXA_PASSWORD` / `FXA_TOTP` environment variables and call
`fxa_signin.py` directly.

## `fxa_signin.py` standalone usage

The script is also useful outside Ansible:

```bash
FXA_EMAIL=you@example.com \
FXA_PASSWORD=hunter2 \
FXA_TOTP=123456 \
BROWSER_TYPE=zen \
python3 fxa_signin.py
```

`BROWSER_TYPE` accepts: `zen`, `firefox`, `firefox-flatpak`.
`PROFILE_DIR` overrides auto-detection entirely.

## License

GPL-3.0-or-later
