# Operational runbook

Recipes for the questions that recur. If you find yourself answering one of
these from memory or commit logs more than twice, add it here.

---

## I rotated my SSH key on host X — how do I propagate it?

The `ssh_keys` role now syncs **on mismatch** (not just on missing), so:

```bash
# On host X (with BW unlocked locally, just unlocked with bw unlock --raw):
dots-apply
```

That detects the local pub key differs from the BW entry, calls
`bw edit item` to replace it, and rewrites this host's `authorized_keys` while
it's at it. Then on every *other* host:

```bash
dots-apply           # picks up the fresh pubkey from BW into authorized_keys
```

If you can't reach an "other" host because of the stale key situation, you
can also push the new key directly first:

```bash
# From a host that can still reach the broken one
ssh-copy-id <broken-host>     # adds the rotating host's pub key by hand
# then `dots-apply` on broken-host as above
```

---

## BW is locked on a remote — how do I unlock it there?

`just apply-remote-tags <host> ...` forwards your local `BW_SESSION`, but the
remote host's vault can still report `locked` because the token isn't always
portable across vaults. To unlock directly on that host:

```bash
ssh <host>
bw unlock --raw | tee /tmp/bw_session > /dev/null
chmod 600 /tmp/bw_session
exit

# Then from your laptop:
just apply-remote-tags <host> bitwarden,ssh_keys
```

The `bitwarden` role on `<host>` will read `/tmp/bw_session`, confirm the
vault is unlocked, and downstream secrets roles will run.

---

## The timer apply failed last night — what do I do?

The user-level `dotfiles-update.service` runs `just apply-nosecrets` daily,
which now writes `~/.cache/dotfiles/last-apply.json`. Quickest signal:

```bash
just doctor                 # `→ Last apply` line shows status + age
```

If `rc != 0`, see what blew up:

```bash
journalctl --user -u dotfiles-update.service -e --no-pager | tail -80
```

The most common causes:

- **git pull failure** (DNS / network blip): the recipe tolerates it with
  `git pull --ff-only || true`; the ansible run continues with whatever's
  on disk. If the working tree drifted from main, fix manually.
- **a role started failing after a config change**: re-run interactively
  with `just apply-nosecrets` and read the failure.
- **`mkswap: /swapfile is mounted`**: pre-existing bug in
  `roles/server_hardening`; the swapfile is already active and the
  idempotency check is wrong. Set `skip_server_hardening: true` in that
  host's `host_vars/` as a workaround.

---

## BW master password just returned "decryption failed" — vault corrupt?

Two BW CLI processes can corrupt the local encrypted vault if they sync at the
same time. Symptom: `bw unlock --raw` returns
`Cryptography error, The decryption operation failed`.

Fix is to re-login (downloads a clean vault):

```bash
bw logout
bw login              # email + master password + 2FA
export BW_SESSION=$(bw unlock --raw)
printf '%s' "$BW_SESSION" > /tmp/bw_session
chmod 600 /tmp/bw_session
```

The `bitwarden` role now has a 15 s timeout on `bw sync`, which prevents the
race in most cases going forward.

---

## I want to onboard a new machine — full sequence

```bash
# 1. From an existing fleet machine (with BW unlocked):
just onboard <newhost> desktop      # or server / vps / llm

# 2. Copy the printed bootstrap command, then on the new machine:
curl -fsSL https://raw.githubusercontent.com/hanthor/dotfiles/master/bootstrap.sh \
  | bash -s -- --name <newhost> --type desktop

# 3. After bootstrap finishes, on the new machine, get BW into a usable state:
bw login                            # if not logged in
bw unlock --raw | tee /tmp/bw_session > /dev/null

# 4. Run the full apply (this pushes the new machine's pubkey to BW):
dots-apply

# 5. Back on each existing host (one at a time, or wait for the timer):
dots-apply                          # picks up the new host's pubkey
```

Verify with `just doctor` on the new host — should be all green and report
"last apply <minutes> ago".

---

## I added a flatpak / brew package — how do I roll it out?

Edit the relevant role's package list (`roles/flatpak/files/...` or the
homebrew Brewfile), commit, push. Every host picks it up on the next
`dots-apply` or the next timer fire.

To force-apply immediately on the local machine:

```bash
just apply-tags packages
```

---

## I want to disable a role on one host

In that host's `host_vars/<name>.yml`, add a `skip_<role>: true` line. The
roles that respect this convention:

`skip_kube`, `skip_flatpak`, `skip_bluefin`, `skip_gnome`, `skip_proxy`,
`skip_homepage`, `skip_lima`, `skip_zen_browser`, `skip_monitoring`,
`skip_syncthing`, `skip_tailscale_cert`, `skip_cockpit`,
`skip_server_hardening` (not all may be wired yet — grep `site.yml` to
confirm).

---

## How do I verify a change made it to every host?

```bash
just doctor-fleet
```

Runs `just doctor` on every online host in parallel. The `→ Last apply`
line tells you which hosts have an old or failed convergence — those are
the ones that need attention.

To roll a single change out manually instead of waiting for the timer:

```bash
for h in $(scripts/nmap-inventory.sh | awk '/ON / {print $3}'); do
  just apply-remote-tags "$h" <tag-or-tags> &
done
wait
```
