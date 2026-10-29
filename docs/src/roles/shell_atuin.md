# shell_atuin

**Units:** `chezmoi` (config file), `atuin` (`units/atuin.sh`; see [Units](../units.md))  
**Tags:** `dotfiles`, `shell`, `atuin`, `secrets`  
**Secrets needed:** Yes, for login (`atuin.sh` from Bitwarden)  
**Runs on:** All machines

Configures [Atuin](https://atuin.sh/) shell history and logs it in to sync.

## What It Does

1. chezmoi writes `~/.config/atuin/config.toml` from `home/dot_config/atuin/config.toml` — sync to `api.atuin.sh` every 5m, fuzzy search, `filter_mode = "global"` (including the Up-arrow binding)
   `just apply-tags atuin` and `just apply-tags secrets` apply only this
   chezmoi file, without unrelated dotfiles or chezmoi scripts.
2. The `atuin` unit checks `atuin status`; a successful exit skips the Bitwarden round-trip. It does not depend on a particular human-readable heading.
3. Otherwise, with an unlocked vault, it reads the `atuin.sh` item (username, password, custom field `key` holding the mnemonic). Atuin 18.24 or newer receives the password and key through its environment, not command-line arguments. The unit preserves the data directory and its history; a missing key can be written by Atuin during login. If a key already exists, the unit logs in only when `atuin key` matches the vault mnemonic, then runs a best-effort `atuin sync`.
4. Imports existing shell history once (`atuin import auto`, sentinel `~/.local/share/atuin/.history_imported`). If the version, key lookup, existing key, or login attempt requires manual attention, the unit defers importing until that situation is resolved. A failed login also fails the unit.

## Output lines

- `SKIPPED: atuin not installed` — install it (`core_brews`)
- `PARTIAL: atuin not logged in; vault locked` — `bw unlock`, then `just apply-tags atuin`
- `PARTIAL: Bitwarden item atuin.sh missing or incomplete` — fix the item (needs username, password, field `key`)
- `PARTIAL: atuin 18.24 or newer required` — upgrade Atuin or run `atuin login` interactively; older versions do not support the non-interactive environment credentials
- `PARTIAL: cannot determine the Atuin key path`, `cannot read the existing Atuin key`, or `existing Atuin key differs` — inspect the local data and resolve the key situation before logging in interactively. A vault key in a different representation can also compare unequal.

## Notes

- Existing keys are never deleted or replaced by the unit; it does not reset `~/.local/share/atuin` when the key is missing. That directory is kept mode 0700, including after a prior history import.
- Atuin 18.24 resolves its own configured key path, including the newer `~/.atuin/data` layout; the history-import sentinel remains in `~/.local/share/atuin`.
- Alpine requires the sync-enabled `atuin-sync` package selected by `units/apk-packages.conf`; the plain `atuin` package is offline-only. Versions before 18.24 require native interactive login rather than credentials in command-line arguments.
- Don't set the Up-arrow filter to `session`: it looks broken in fresh terminals

## History/key recovery (2026-10-28)

Punjab, Karnataka and Kerala were reconciled under the existing Bitwarden
`atuin.sh` item's `key`, which decrypted the readable cloud history. Prior
Punjab and Kerala keys remain in hidden fields
`recovery-punjab-key-2026-10-28` and `recovery-kerala-key-2026-10-28`.
Do not overwrite a mismatched client key or discard its database before recovery.

The clean history contains 23,760 recovered entries plus one real sync
verification command. Original readable cloud, Punjab and Kerala history IDs
were preserved; additional raw shell history was imported, without broadly
deleting repeated commands. Undated Bash imports identify their timestamp as
import time in their intent metadata. SQLite integrity, record encryption and
an independent full cloud download passed. All three reachable clients then
synced using the canonical key; Himachal was offline and was not modified.

The owner approved replacing the mixed-key cloud store. Its 245 records under
11 unavailable keys were preserved as ciphertext, not claimed as decrypted or
silently discarded. Original databases and keys are private under
`~/backups/atuin-recovery-20261028T195643Z/` on Punjab. The verified age-encrypted
original snapshot archive is also at
`ubuntu@spindle:~/backups/atuin-recovery-20261028T195643Z/`.
Retain these archives: keys recovered from an old/offline host may unlock more
history later. The original live directory is retained as `live-data-before-switch/`.

Before resuming sync on an old/offline client, back up its databases and key,
recover any unsynced history into the canonical store, then give that client a
fresh verified store. Do not let an old cached mixed-key store upload again:
even a client with the correct account key may carry other hosts' opaque records.

Back up live SQLite databases with SQLite's backup API, not by copying only
their `.db` files while WAL files exist. Test recovery on copies; `store rebuild
history` merges rather than clears its target, and `store verify` can print
failure while returning exit zero. Require explicit verification success.
`store push --force` replaces the entire remote store and requires a verified
recovery archive and an explicit replacement decision; it is not a routine sync.
