# Onboarding a New Machine

Two paths depending on whether the machine is already reachable.

## Path A: Machine Already Online (Tailscale + SSH)

```bash
# From any machine with the dotfiles repo:
just add-machine <name> <type>
```

This:
1. Adds the machine to `inventory.yml` under the right group
2. Creates `host_vars/<name>.yml` with sensible defaults
3. Commits and pushes
4. Prints the next step — run `just apply-remote <name>`

## Path B: Fresh Install

```bash
# From any machine with the dotfiles repo:
just onboard <name> <type>
```

This prints a bootstrap command to run **on the new machine**:

```bash
# On the new machine:
curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh \
  | bash -s -- --name <name> --type <type>
```

The bootstrap script:
1. Installs git and clones the dotfiles repo from [GitHub](https://github.com/hanthor/dotfiles)
2. Installs [Homebrew](https://brew.sh/) (Linux) and core packages
3. Writes `/etc/dotfiles-machine` so the playbook can self-identify
4. Runs `just apply` for the first time

## Machine Types

| Type | Group | Has Desktop? | Example Host Vars |
|------|-------|-------------|-------------------|
| `desktop` | desktop | Yes | `is_laptop: false`, web services |
| `laptop` | desktop | Yes | `is_laptop: true` |
| `server` | server | No | `skip_flatpak: true`, `skip_gnome: true` |
| `vps` | vps | No | `skip_*: true`, uses `group_vars/vps.yml` |

## Post-Onboarding

1. The `ssh_keys` role generates a fresh ed25519 key on the new host, then pushes the pub key up to Bitwarden as `james@<hostname>`.
2. The new host now needs to **trust the rest of the fleet, and the rest of the fleet needs to trust it**. The first apply on the new host downloads every other host's pub key into `~/.ssh/authorized_keys`. The other hosts will pick up the new host's pub key on *their* next apply (manually run `dots-apply` on each, or wait for the timer).
3. The `github` role registers the SSH key with GitHub for both auth and commit signing.
4. The `tailscale` role joins the machine to the [Tailscale](https://tailscale.com/) network using the auth key in BW.
5. The daily `dotfiles-update.timer` (servers) or on-login service (laptops) runs `just apply-nosecrets` — secrets stay on the manual `dots-apply` cadence because BW can't be unlocked non-interactively.

Run `just doctor` on the new host once it's bootstrapped — it'll tell you whether BW is unlocked, whether the timer is wired up, and the timestamp of the last successful apply.

See [Architecture](architecture.md) for how the playbook runs on each machine and [Secrets with Bitwarden](bitwarden.md) for the details of the BW handshake.
