# shell_atuin

**Units:** `chezmoi` (config file), `atuin` (`units/atuin.sh`; see [Units](../units.md))  
**Tags:** `dotfiles`, `shell`, `atuin`, `secrets`  
**Secrets needed:** Yes, for login (`atuin.sh` from Bitwarden)  
**Runs on:** All machines

Configures [Atuin](https://atuin.sh/) shell history and logs it in to sync.

## What It Does

1. chezmoi writes `~/.config/atuin/config.toml` from `home/dot_config/atuin/config.toml` — sync to `api.atuin.sh` every 5m, fuzzy search, `filter_mode = "global"` (including the Up-arrow binding)
2. The `atuin` unit checks `atuin status`; if it shows `[Sync]` the Bitwarden round-trip is skipped
3. Otherwise, with an unlocked vault, it reads the `atuin.sh` item (username, password, custom field `key` holding the mnemonic) and runs `atuin login -u … -p … -k …` (resetting `~/.local/share/atuin` first when no key file exists), then a best-effort `atuin sync`
4. Imports existing shell history once (`atuin import auto`, sentinel `~/.local/share/atuin/.history_imported`)

## Output lines

- `SKIPPED: atuin not installed` — install it (`core_brews`)
- `PARTIAL: atuin not logged in; vault locked` — `bw unlock`, then `just apply-tags atuin`
- `PARTIAL: Bitwarden item atuin.sh missing or incomplete` — fix the item (needs username, password, field `key`)

## Notes

- The mnemonic is passed to `atuin login -k`, never written to `~/.local/share/atuin/key` directly — atuin expects that file to be a binary key
- `atuin login` receives the password on its command line, visible to `ps` for the duration of the call
- Don't set the Up-arrow filter to `session`: it looks broken in fresh terminals
