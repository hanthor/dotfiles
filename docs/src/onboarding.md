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
# From an authenticated checkout with git and gh:
just add-machine <name> <type>
```

For a new machine this proposes an inventory-only PR from `origin/master` in a
temporary worktree and stops without connecting to the host. Review the group,
connection details and `host_vars`, wait for required checks and owner approval,
and merge the PR. Then rerun `just add-machine <name> <type>`; it verifies the
registration on `origin/master` and SSHes in to run bootstrap. An already
registered host skips the PR step. The caller's checkout, index and existing
branches are not changed. The new machine must already be reachable over SSH.

## Path B: Fresh Install

```bash
# From an authenticated checkout with git and gh:
just onboard <name> <type>
```

Review and merge the registration PR before using the printed command **on the
new machine**. The registration helper uses a temporary worktree and does not
pull, switch branches, stage or commit the caller's work. If a registration PR
already exists, it prints its URL; an existing remote onboarding branch without
an open PR is left untouched for manual inspection.

```bash
# On the new machine:
curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh \
  | bash -s -- --name <name> --type <type>
```

Bootstrap first ensures Python and git, then verifies that its local inventory
and the current `origin/master` contain the machine in the requested group
before changing identity, sudo or Tailscale, or running units. If registration is
missing, run `just onboard` from an authenticated fleet checkout, review and
merge the PR, then rerun it.
An existing checkout is never pulled or overwritten by bootstrap: update it
yourself after the merge and rerun. A fresh machine clones `master`.

After that gate, Linux bootstrap writes `/etc/dotfiles-machine`, sets hostname,
sudo and Tailscale, then runs the native no-secrets and secrets phases. Termux
uses the unprivileged path described below. Bootstrap reports failure if a phase
or Bitwarden setup fails. Review unit output: skips and partial results are not
proof that every host component is configured.

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

`<type>` is the inventory group to join. Bootstrap supports these groups:

| Type | Group | Has Desktop? | Notes |
|------|-------|-------------|-------|
| `desktop` | desktop | Yes | Laptops are desktops too — set `is_laptop: true` in `host_vars` |
| `server` | server | No | Gets `server_hardening`; desktop units skip automatically |
| `vps` | vps | No | Also skips `syncthing`, `proxy`, `tailscale_cert` |
| `termux_hosts` | termux_hosts | No | Existing reviewed raw Termux identity; Android manages Tailscale |

There is no `laptop` type. Unknown types and invalid hostnames are rejected.
New `test_fleet` and `termux_hosts` identities require a manually reviewed
inventory PR; Termux registrations need the correct Android Tailscale name,
SSH user and port rather than the normal localhost defaults.

## Raw Termux on the phone

The existing inventory alias is `termux` (`termux_hosts`, port 8022 and
tailnet name `pixel-9a`); `mumbai` is the separate Debian VM and remains a
desktop. Join the tailnet using the Android Tailscale app. In Termux, install
the initial commands and run the already-reviewed identity locally:

```bash
pkg update && pkg install git python curl openssh
curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh \
  | bash -s -- --name termux --type termux_hosts
```

For SSH onboarding, first start `sshd` in Termux and arrange authenticated SSH
access through the fleet's existing `termux` SSH alias; then run `just
add-machine termux termux_hosts` from a fleet checkout. Bootstrap checks the
local and merged inventory, runs `pkg` and the native units without root, and
does not modify the Android hostname, Tailscale app or `/etc`. Termux:Boot and
Termux:API companion apps are needed for the boot script and scheduler.

Termux cannot persist `/etc/dotfiles-machine`; the bootstrap phases pass the
reviewed identity explicitly. For later local applies, use
`DOTFILES_MACHINE=termux BW_SESSION_CACHE="$PREFIX/tmp/bw_session" just apply`.
If Bitwarden CLI is unavailable or locked, the no-secrets phase still runs but
bootstrap reports the secrets phase incomplete; provide a usable CLI session
and rerun. Bootstrap keeps its Termux session in the process environment rather
than writing `/tmp/bw_session`; the later apply command above uses a private
cache under Termux's writable prefix. The phone push timer also supplies the
identity explicitly.

## Post-Onboarding

1. The `ssh-keys` unit restores the host's ed25519 key from Bitwarden, or generates one if a successful unlocked vault listing has no item, and syncs it as `<login>@<machine>`.
2. The unit merges available vault public keys into `~/.ssh/authorized_keys` without removing user entries. Other hosts pick up a new vault key on their next unlocked apply. The separate `ssh-mesh` unit also merges committed fleet public keys during no-secrets applies.
3. The `github` unit can register the SSH key with GitHub for authentication and signing.
4. The `tailscale` unit joins a disconnected eligible machine using its Bitwarden key.
5. The daily `dotfiles-update.timer` (servers) or on-login service (laptops) runs `just apply-nosecrets` — secrets stay on the manual `dots-apply` cadence because BW can't be unlocked non-interactively.

Run `just doctor` on the new host once it's bootstrapped — it'll tell you whether BW is unlocked, whether the timer is wired up, and the timestamp of the last successful apply.

See [Architecture](architecture.md) for native unit execution and [Secrets with Bitwarden](bitwarden.md) for the BW handshake.
