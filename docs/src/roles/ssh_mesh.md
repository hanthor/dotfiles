# ssh_mesh

Self-healing passwordless SSH mesh across the fleet.

## What it does

1. Ensures the machine has an ed25519 keypair (generates if missing).
2. Merges all fleet public keys from `machine_pubkeys` (in
   `group_vars/all.yml`) into `~/.ssh/authorized_keys` — non-destructive
   `lineinfile`, so Bitwarden-managed keys and extras survive.
3. Warns if this machine's own public key is missing or stale in git.
4. Probes passwordless SSH to every fleet machine currently **online on
   the tailnet** (`tailscale status --json` ∩ `machines` −
   `ssh_mesh_exclude`).
5. On failure: reaps stale ControlMaster sockets, refreshes the host key
   in `known_hosts` (rebuilt machines), and retries.
6. Fails the apply if the mesh is still broken, naming the unreachable
   hosts.

## Why it's self-healing

- Public keys live **in git**, not only in Bitwarden — safe to publish,
  and every apply replants them. A machine missing a peer's key heals on
  its next `just apply` or the daily `dotfiles-update.timer`
  (`apply-nosecrets`), no vault unlock needed.
- The role is tagged `[ssh, mesh_check]` but **not** `secrets`, so the
  daily no-secrets timer runs it.
- Probes bypass SSH multiplexing (`ControlMaster=no`) so a hung mux
  socket can't fake an outage, and are capped with `timeout`.

## Usage

```bash
just mesh-check                        # verify + heal from this machine
just apply-remote-tags HOST mesh_check # verify + heal from HOST
```

## Adding a machine to the mesh

Add its public key to `machine_pubkeys` in `group_vars/all.yml` and its
entry to the `machines` dict. Machines that must not be probed (Talos
nodes, port-forwarded test VMs) go in `ssh_mesh_exclude`.

## Relationship to ssh_keys

`ssh_keys` (tag `secrets`) still round-trips **private** keys through
Bitwarden and rebuilds `authorized_keys` from the vault when unlocked.
`ssh_mesh` is the vault-free safety net + verification layer on top.
