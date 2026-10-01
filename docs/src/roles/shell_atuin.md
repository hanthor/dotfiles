# shell_atuin

**Tags:** `dotfiles`, `shell`, `atuin`, `secrets`  
**Secrets needed:** Yes, for login (`atuin.sh` from Bitwarden)  
**Runs on:** All machines

Configures [Atuin](https://atuin.sh/) shell history and logs it in to sync.

## What It Does

1. Writes `~/.config/atuin/config.toml` — sync to `api.atuin.sh` every 5m,
   fuzzy search, `filter_mode = "global"` (including the Up-arrow binding)
2. Checks `atuin status`; if already logged in, skips the Bitwarden round-trip
3. Otherwise, when `bw_unlocked`, reads the `atuin.sh` item (username,
   password, and a custom field `key` holding the mnemonic) and runs
   `atuin login -u … -p … -k …`
4. Runs a best-effort `atuin sync`
5. Imports existing shell history once (`atuin import auto`, sentinel
   `~/.local/share/atuin/.history_imported`)

## Notes

- Skips login with a warning if the `atuin` binary is missing (it's in `core_brews`)
- The mnemonic is passed to `atuin login -k`, never written to `~/.local/share/atuin/key` directly — atuin expects that file to be a binary key
- Don't set the Up-arrow filter to `session`: it looks broken in fresh terminals
