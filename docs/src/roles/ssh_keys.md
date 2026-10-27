# ssh_keys

`units/ssh-keys.sh` invokes the locked shared implementation `units/ssh-fleet.py`. It manages the local ed25519 identity, fleet SSH config, known hosts, Git allowed signers, and Bitwarden-backed authorization. Fleet names and login data come from `group_vars/all.yml`, `inventory.yml`, and host variables; YAML parsing needs `yq` or Python PyYAML.

If the private key is absent, the unit requires an unlocked vault and a successful item listing before restoring the complete `<login>@<machine>` SSH item or generating a new pair when no item exists. It checks restored and local key pairs and refuses conflicting keys. An existing local key is retained; if its public key differs from the vault item, the vault is left unchanged unless `SSH_KEYS_FORCE_PUSH=true` or `ssh_keys_force_push: true` explicitly permits rotation.

The unit preserves user entries outside its marked SSH config and `authorized_keys` blocks. Vault public keys and `extra_authorized_keys` are merged into the authorization block; previous managed entries remain by default. `SSH_KEYS_FORCE_AUTHORIZED=true` (or the corresponding host variable) permits removing obsolete entries only within that block. A locked vault, disabled secrets, or an empty vault key list leaves vault authorization unchanged. Host-key scans only replace an entry after a usable scan; failed scans leave existing entries intact. Existing signers are retained.

`--no-secrets` skips vault access; a missing identity is deferred rather than generated. Config and other independent steps still run. The separate [ssh_mesh](ssh_mesh.md) unit adds committed fleet public keys and checks connectivity.
