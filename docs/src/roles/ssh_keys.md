# ssh_keys

`units/ssh-keys.sh` invokes the locked shared implementation `units/ssh-fleet.py`. It manages the local ed25519 identity, fleet SSH config, known hosts, Git allowed signers, and Bitwarden-backed authorization. Fleet names and login data come from `inventory.yml`, group and host variables. Nested group membership and effective connection variables are resolved by `units/osquery_native_inventory.py`; YAML parsing needs `yq` or Python PyYAML.

If the private key is absent, the unit requires an unlocked vault and a successful item listing before restoring the complete `<login>@<machine>` SSH item or generating a new pair when no item exists. It checks restored and local key pairs and refuses conflicting keys. An existing local key is retained; if its public key differs from the vault item, the vault is left unchanged unless `SSH_KEYS_FORCE_PUSH=true` or `ssh_keys_force_push: true` in host or group variables explicitly permits rotation.

Passphrase-protected OpenSSH identities are not prompted for. Existing identities and vault restores are retained when the public key matches the encrypted key's public envelope, but the private contents cannot be verified without the passphrase. The envelope is unauthenticated, so the unit will not create or replace a Bitwarden key from that unverified identity, even with forced rotation. A missing, invalid or mismatched public key remains an error.

The unit preserves user entries outside its marked SSH config and `authorized_keys` blocks. Vault public keys and `extra_authorized_keys` are merged into the Bitwarden block; committed keys are managed separately by [ssh_mesh](ssh_mesh.md). Previous managed entries remain by default. `SSH_KEYS_FORCE_AUTHORIZED=true` (or `ssh_keys_force_authorized: true` in host or group variables) permits removing obsolete entries in each managed block when that unit runs; a locked vault or an empty vault key list leaves the Bitwarden block unchanged. Existing signers are retained.

## Host trust

The unit never scans or changes `known_hosts`; a network keyscan cannot authenticate a host. Managed SSH config uses `StrictHostKeyChecking yes`, and mesh probes enforce it explicitly. Before connecting to a new host, obtain its host-key fingerprint over an independent authenticated channel (such as its console), compare it with the candidate key, and add only the verified key to `~/.ssh/known_hosts` under the actual hostname and port (`[host]:port` for a non-default port). If a key changes, do not overwrite the old pin until the change has been independently verified; then replace it explicitly. User-supplied SSH settings can override the managed default.

## Revoking access

Remove the key from every source that should no longer authorize it, including `machine_pubkeys`, the corresponding Bitwarden SSH item and `extra_authorized_keys`. With an unlocked vault and a nonempty fleet key list, run both SSH units with `SSH_KEYS_FORCE_AUTHORIZED=true`; `just apply-tags ssh_keys` selects both. Inspect `authorized_keys` afterwards: old unmarked entries, including entries written by earlier versions, are deliberately never attributed or deleted automatically. If the verified obsolete key also appears outside the marked blocks, manually remove each such line after confirming it is not independently required. Keep other user-managed lines unchanged.

`--no-secrets` skips vault access; a missing identity is deferred rather than generated. Config and other independent steps still run. The separate [ssh_mesh](ssh_mesh.md) unit adds committed fleet public keys and checks connectivity.
