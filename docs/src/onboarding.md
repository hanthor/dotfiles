# Onboarding a New Machine

## Step 0: Get on the tailnet by scanning a QR (recommended first step)

Before secrets or SSH can flow, the machine needs to be on the tailnet. Instead
of copying an auth key, join it by scanning a QR with your phone — **run this on
the new machine**:

```bash
just tailscale-qr              # uses default machine name
just tailscale-qr name=custom  # or provide a custom name
```

This runs interactive `tailscale up --qr`: it renders the login URL as a QR in
the terminal. Scan it with your phone and approve the device in the Tailscale
admin (passwordless via your IdP). No auth key, no Bitwarden, no master password.

Once the machine is on the tailnet, its **tailnet identity becomes its first
credential** — every other onboarding step (secret delivery, `apply`, SSH) flows
from there. This is Phase 0 of the [QR secret onboarding](qr-onboarding.md)
effort; the later phases replace the auth-key/master-password handshake below
entirely.

> Requires you to be a `tagOwner` of `tag:fleet` in the tailnet ACL (every fleet
> node carries this tag). Drop `--advertise-tags` in the recipe to join as a
> personal device instead.

Then continue with Path A or B below.

---

Two paths depending on whether the machine is already reachable.

## Path A: Machine Already Online (Tailscale + SSH)

```bash
# From any machine with the dotfiles repo:
just add-machine <name> <type>
```

This:
1. If the machine isn't in `inventory.yml` yet, adds it (`ansible_host: localhost`, `ansible_connection: local`) and puts it in the `<type>` group
2. Creates an empty `host_vars/<name>.yml` — add per-machine knobs there afterwards
3. Commits and pushes
4. SSHes in (`ssh -t <name>`) and runs `bootstrap.sh --name <name> --type <type>` there — the same bootstrap as Path B

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
1. Ensures Python and git, then clones the dotfiles repo from [GitHub](https://github.com/hanthor/dotfiles).
2. Registers the machine in `inventory.yml` if needed (prompts for the type when `--type` isn't given).
3. Writes `/etc/dotfiles-machine`, sets the hostname, and sets up sudo and Tailscale.
4. Runs native units with `--no-secrets` (including package installation).
5. Resolves and syncs Bitwarden, runs the `omp,secrets` unit selection, and pushes any inventory changes.

Bootstrap continues to the secret phase when possible, but reports failure if a phase or Bitwarden setup fails. Review unit output: skips and partial results are not proof that every host component is configured.

## After Bootstrap Completes

Bootstrap ends with shell environment setup instructions. The critical next step is to start a new shell and run the first full apply:

```bash
# Start a fresh shell to load updated environment (e.g., Homebrew paths)
exec zsh

# Run the first full apply (with secrets)
just apply
```

**Why this step matters:**
- Bootstrap's first phase disables secrets; the second selects secret-capable units and omp.
- `just apply` reruns the full native selection with secrets where available.
- This can distribute SSH keys, register with GitHub and Tailscale, and set up daily/on-login automation on eligible hosts.

Host-specific gates and overrides belong in `host_vars/<name>.yml`; consult [Architecture](architecture.md#conditional-execution) and the unit implementations when setting them.

The details of what happens during this first apply are covered in the [Post-Onboarding](#post-onboarding) section below.

## Machine Types

`<type>` is the inventory group to join. `bootstrap.sh` offers `desktop`, `server` and `vps`:

| Type | Group | Has Desktop? | Notes |
|------|-------|-------------|-------|
| `desktop` | desktop | Yes | Laptops are desktops too — set `is_laptop: true` in `host_vars` |
| `server` | server | No | Gets `server_hardening`; desktop units skip automatically |
| `vps` | vps | No | Also skips `syncthing`, `proxy`, `tailscale_cert` |

There is no `laptop` type — a type that doesn't match a group leaves the host in
no group. `test_fleet` and `termux_hosts` hosts are added to `inventory.yml` by
hand.

## Post-Onboarding

1. The `ssh-keys` unit restores the host's ed25519 key from Bitwarden, or generates one if a successful unlocked vault listing has no item, and syncs it as `<login>@<machine>`.
2. The unit merges available vault public keys into `~/.ssh/authorized_keys` without removing user entries. Other hosts pick up a new vault key on their next unlocked apply. The separate `ssh-mesh` unit also merges committed fleet public keys during no-secrets applies.
3. The `github` unit can register the SSH key with GitHub for authentication and signing.
4. The `tailscale` unit joins a disconnected eligible machine using its Bitwarden key.
5. The daily `dotfiles-update.timer` (servers) or on-login service (laptops) runs `just apply-nosecrets` — secrets stay on the manual `dots-apply` cadence because BW can't be unlocked non-interactively.

Run `just doctor` on the new host once it's bootstrapped — it'll tell you whether BW is unlocked, whether the timer is wired up, and the timestamp of the last successful apply.

See [Architecture](architecture.md) for native unit execution and [Secrets with Bitwarden](bitwarden.md) for the BW handshake.
