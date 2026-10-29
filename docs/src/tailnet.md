# Tailnet hygiene

`scripts/tailnet.py` keeps the tailnet and `inventory.yml` in agreement. Commands are dry runs unless `--apply` is given, except `release`, which deletes matching devices immediately.

| Command | What it does |
|---|---|
| `just tailnet-audit` | Read-only report; exit 1 when anything needs doing |
| `just tailnet-sync [--apply]` | GC, then rename, then inventory alignment, planned as one sequence |
| `scripts/tailnet.py gc [--apply] [--days N] [--k8s-days N]` | Delete duplicate devices and stale test VMs; optionally report stale k8s proxies |
| `scripts/tailnet.py rename [--apply]` | Rename live devices to their intended name |
| `scripts/tailnet.py fix-inventory [--apply]` | Make `ansible_host` IPs and `tailnet_name` overrides follow the live devices |
| `scripts/tailnet.py release NAME` | Delete offline devices called `NAME` or `NAME-<n>` before joining; refuses retired VPS names and aliases |

## Rules

- A device's tailnet name is the first MagicDNS label. An inventory host's **intended** name is its `tailnet_name` var, else the inventory name. A `tailnet_name` of the form `<host>-<n>` is the auto-suffix Tailscale adds when a stale device still holds `<host>`, so it means "wants `<host>`" and is removed once the rename has happened.
- **Duplicates:** several devices named `<intended>` / `<intended>-<n>`: the live (else most recently seen) one is kept; older offline ones are deleted.
- **Test VMs:** offline longer than `--days` (default 14), named `gate-*`, `repro-*`, `tuna-v1-preflight-*` or `*-vm`, and not an inventory host.
- **k8s proxies** (`tag:k8s*`) cannot be distinguished reliably by cluster ownership. `--k8s-days` reports stale proxies but never deletes them; an apply that encounters one refuses all changes. Proxies matching the test-VM or duplicate rules are likewise protected, as are proxies passed to `release`. Retained home-cluster state remains recovery material.
- Never deleted: devices that are online, this machine, devices shared in from other tailnets, protected `bihar` and `karnataka` device names, and the retired `vps` group. Karnataka is now a managed Utah host; protection retains its former cluster identity without excluding it from inventory. Both VPS inventory names and `tailnet_name` aliases are protected, including numbered suffixes; `release` refuses these names without contacting the API. Rename can change an online device's MagicDNS name.
- `fix-inventory` run alone reflects the live state, so it will not drop a `tailnet_name` override before the rename has actually happened.
- Before planning or writing, every device must have a valid ID and name and an explicitly boolean presence state. Missing or non-boolean `connectedToControl`, invalid or duplicate IDs, and invalid names make the whole snapshot unverifiable: the command reports the problem and makes no plan or changes. Read-only audit reports the problem rather than claiming agreement. A fresh snapshot is checked again before the inventory is updated after `sync`.

## Credential

Reads fall back to the local `tailscale status --json`; writes need the API. The credential is a Tailscale **OAuth client** (scopes `devices:core` write and `auth_keys` write, tag `tag:fleet`) created at <https://login.tailscale.com/admin/settings/oauth>. Store it with `just seed-tailnet-oauth`: the secret is verified against Tailscale before it is written to Bitwarden item `tailscale-apikey`. `TS_OAUTH_CLIENT_SECRET` overrides the Bitwarden lookup. An invalid or expired secret cannot authorize cleanup; replace it before attempting any tailnet changes.

The same secret is the join auth key used by the [`tailscale` unit](roles/tailscale.md). The previous cleanup in the Ansible role treated it as a classic API key, got a 401 that `failed_when: false` hid, and never deleted anything; that is why re-joined machines came back as `himachal-1` and `kerala-1`.

## Caveat when renaming

After `rename --apply`, `himachal-1` stops resolving; use the new name. Do not rename while something is using the old MagicDNS name (an rsync or ssh session, for example).
