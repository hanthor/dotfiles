# Operational runbook

Recipes for the questions that recur. If you find yourself answering one of
these from memory or commit logs more than twice, add it here.

---

## I rotated my SSH key on host X — how do I propagate it?

An intentional local rotation is explicit: when the local public key differs
from the Bitwarden item, the `ssh-keys` unit leaves Bitwarden unchanged and
warns. To publish an intentional rotation, on host X with BW unlocked:

```bash
SSH_KEYS_FORCE_PUSH=true just apply-tags ssh_keys
```

That updates the `james@<hostname>` item in Bitwarden and refreshes this host's
`authorized_keys` while it is at it. Then on every *other* host:

```bash
dots-apply           # picks up the fresh pubkey from BW into authorized_keys
```

If the mismatch was not intentional, do not use the force flag: move the local
key aside and re-apply so the host fetches the Bitwarden copy.

If you can't reach an "other" host because of the stale key situation, you
can also push the new key directly first:

```bash
# From a host that can still reach the broken one
ssh-copy-id <broken-host>     # adds the rotating host's pub key by hand
# then `dots-apply` on broken-host as above
```

---

## BW is locked on a remote — how do I unlock it there?

`just apply-remote` / `apply-remote-tags` try to unlock the vault on the remote
themselves (`scripts/bw-resolve.sh remote`), but that can fail — e.g. no
`bw-api-key` item, or the remote CLI was never logged in. To unlock directly on
that host:

```bash
# Resolve and apply the SSH key selection on the remote host:
just apply-remote-tags <host> ssh_keys
```

The `scripts/bw-resolve.sh remote <host>` script (invoked internally) will
SSH to the remote, ensure Bitwarden is logged in and unlocked (either via
stored API key, master password from your local vault, or interactive prompt),
and return the session token. The remote apply validates and syncs it before
secret-capable units run; if resolution fails, they run with secrets disabled.

---

## The timer apply failed last night — what do I do?

The user-level `dotfiles-update.service` runs `just apply-nosecrets` on its
configured schedule or laptop login, and records `~/.cache/dotfiles/last-apply.json`.

```bash
just doctor                 # `→ Last apply` line shows status + age
```

If `rc != 0`, see what blew up:

```bash
journalctl --user -u dotfiles-update.service -e --no-pager | tail -80
```

The most common causes:

- **git pull failure** (DNS / network blip): the recipe tolerates it with
  `git pull --ff-only || true`; native units continue with whatever is
  on disk. If the working tree drifted from main, fix manually.
- **a unit started failing after a config change**: re-run interactively
  with `just apply-nosecrets` and read the failure.
- **`mkswap: /swapfile is mounted`** (resolved): `server_hardening` now
  gates `mkswap`/`swapon` on `swapon --show`, so an already-active swapfile
  is left alone. If you still see this, the host is running an old checkout.

---

## BW master password just returned "decryption failed" — vault corrupt?

Two BW CLI processes can corrupt the local encrypted vault if they sync at the
same time. Symptom: `bw unlock --raw` returns
`Cryptography error, The decryption operation failed`.

Fix is to re-login (downloads a clean vault):

```bash
bw logout
bw login              # email + master password + 2FA
eval "$(scripts/bw-resolve.sh local)"
```

Apply recipes put a 15-second timeout on `bw sync`; this bounds a stalled sync
but is not a guarantee against concurrent Bitwarden CLI races.

---

## I want to onboard a new machine — full sequence

```bash
# 1. From an existing fleet machine (with BW unlocked):
just onboard <newhost> desktop      # or server / vps

# 2. Copy the printed bootstrap command, then on the new machine:
curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh \
  | bash -s -- --name <newhost> --type desktop

# 3. After bootstrap finishes, on the new machine, get BW into a usable state:
bw login                            # if not logged in
eval "$(scripts/bw-resolve.sh local)"  # unlocks vault

# 4. Run the full apply (this pushes the new machine's pubkey to BW):
dots-apply

# 5. Back on each existing host (no-secrets applies skip vault synchronization):
dots-apply                          # picks up the new host's pubkey
```

Inspect `just doctor` and the unit output on the new host; partial or skipped
work may need attention even when the apply exits successfully.

---

## I added a flatpak / brew package — how do I roll it out?

Edit the package list — `system_flatpaks` in `units/flatpak-packages.yml`,
or the brew lists (`core_brews`, `desktop_brews`, …) in `group_vars/all.yml`,
which render the Brewfile — then commit, push. Every host picks it up on the next
`dots-apply` or the next timer fire.

To force-apply immediately on the local machine:

```bash
just apply-tags packages
```

---

## I want to disable a unit on one host

Many units inspect `skip_*` flags in `host_vars/<name>.yml`; others use
inventory membership, `machine_profile`, platform detection or an enable flag.
Read the relevant unit and [Architecture](architecture.md#conditional-execution)
before setting a flag. Retired `matrix` and `telengana` are skipped by the shared
unit library; nothing on either host may be restarted.

---

## How do I verify a change made it to every host?

```bash
just doctor-fleet
```

Runs `just doctor` on every online host in parallel. The `→ Last apply`
line tells you which hosts have an old or failed convergence — those are
the ones that need attention.

To roll a single change out manually across online hosts instead of waiting for the timer:

```bash
# Check online tailnet hosts in fleet inventory
just online

# Apply specific tags to all online fleet machines in parallel
just apply-online-tags <tag-or-tags>

# Or perform a full apply across all online fleet machines
just apply-all
```
