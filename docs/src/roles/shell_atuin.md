# shell_atuin

**Units:** `chezmoi` (config file), `atuin` (`units/atuin.sh`; see [Units](../units.md))  
**Tags:** `dotfiles`, `shell`, `atuin`, `secrets`  
**Secrets needed:** Yes, for login (`atuin.sh` from Bitwarden)  
**Runs on:** All machines

Configures [Atuin](https://atuin.sh/) shell history and logs it in to sync.

## What It Does

1. chezmoi writes `~/.config/atuin/config.toml` from `home/dot_config/atuin/config.toml` — sync to `api.atuin.sh` every 5m, fuzzy search, `filter_mode = "global"` (including the Up-arrow binding)
2. The `atuin` unit checks `atuin status`; if it shows `[Sync]` the Bitwarden round-trip is skipped
3. Otherwise, with an unlocked vault, it reads the `atuin.sh` item (username, password, custom field `key` holding the mnemonic). Atuin 18.24 or newer receives the password and key through its environment, not command-line arguments. The unit preserves the data directory and its history; a missing key can be written by Atuin during login. If a key already exists, the unit logs in only when `atuin key` matches the vault mnemonic, then runs a best-effort `atuin sync`.
4. Imports existing shell history once (`atuin import auto`, sentinel `~/.local/share/atuin/.history_imported`). If the version or existing key requires manual login, the unit also defers importing until that situation is resolved.

## Output lines

- `SKIPPED: atuin not installed` — install it (`core_brews`)
- `PARTIAL: atuin not logged in; vault locked` — `bw unlock`, then `just apply-tags atuin`
- `PARTIAL: Bitwarden item atuin.sh missing or incomplete` — fix the item (needs username, password, field `key`)
- `PARTIAL: atuin 18.24 or newer required` — upgrade Atuin or run `atuin login` interactively; older versions do not support the non-interactive environment credentials
- `PARTIAL: cannot determine the Atuin key path`, `cannot read the existing Atuin key`, or `existing Atuin key differs` — inspect the local data and resolve the key situation before logging in interactively. A vault key in a different representation can also compare unequal.

## Notes

- Existing keys are never deleted or replaced by the unit; it does not reset `~/.local/share/atuin` when the key is missing. That directory is kept mode 0700, including after a prior history import.
- Atuin 18.24 resolves its own configured key path, including the newer `~/.atuin/data` layout; the history-import sentinel remains in `~/.local/share/atuin`.
- Alpine's community `atuin` package may be an older offline-only build; sync requires a sync-enabled Atuin client. Check the package version and features before attempting a manual login.
- Don't set the Up-arrow filter to `session`: it looks broken in fresh terminals
