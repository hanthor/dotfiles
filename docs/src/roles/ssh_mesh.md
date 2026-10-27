# ssh_mesh

`units/ssh-mesh.sh` invokes `units/ssh-fleet.py` under the same SSH lock as [ssh_keys](ssh_keys.md). It skips `machine_profile: vm-test` and `skip_ssh_mesh: true`. It merges valid `machine_pubkeys` from `group_vars/all.yml` into `~/.ssh/authorized_keys` without removing existing user or vault entries, and warns if the local public key is missing or stale in git.

The unit probes online tailnet peers selected by `scripts/online_hosts.py --peers`, intersected with `machines` and excluding the local host, `ssh_mesh_exclude`, and inventory VPSes. It uses inventory port and login overrides, bypasses connection multiplexing, and on failure closes an existing mux, attempts a fresh ed25519 host-key scan, and retries. Existing known-host entries are not removed unless the scan succeeds. Persistent failures fail the unit and name the peers.

Normally no vault is needed. If the local identity is missing, the shared implementation consults Bitwarden before restoring or creating it; locked vault or `--no-secrets` defers the identity and probes instead of generating an unmirrored key. Add new public keys to `machine_pubkeys` and host entries to `machines`; configure `tailnet_name` and exclusions where needed.
