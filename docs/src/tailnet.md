# Tailnet hygiene

`scripts/tailnet.py` keeps the tailnet and `inventory.yml` in agreement. Everything is a dry run unless `--apply` is given.

| Command | What it does |
|---|---|
| `just tailnet-audit` | Read-only report; exit 1 when anything needs doing |
| `just tailnet-sync [--apply]` | GC, then rename, then inventory alignment, planned as one sequence |
| `scripts/tailnet.py gc [--apply] [--days N] [--k8s-days N]` | Delete duplicate devices and stale test VMs |
| `scripts/tailnet.py rename [--apply]` | Rename live devices to their intended name |
| `scripts/tailnet.py fix-inventory [--apply]` | Make `ansible_host` IPs and `tailnet_name` overrides follow the live devices |
| `scripts/tailnet.py release NAME` | Delete offline devices called `NAME` or `NAME-<n>`; the `tailscale` role runs it before joining |

## Rules

- A device's tailnet name is the first MagicDNS label. An inventory host's **intended** name is its `tailnet_name` var, else the inventory name. A `tailnet_name` of the form `<host>-<n>` is the auto-suffix Tailscale adds when a stale device still holds `<host>`, so it means "wants `<host>`" and is removed once the rename has happened.
- **Duplicates:** several devices named `<intended>` / `<intended>-<n>`: the live (else most recently seen) one is kept; older offline ones are deleted.
- **Test VMs:** offline longer than `--days` (default 14), named `gate-*`, `repro-*`, `tuna-v1-preflight-*` or `*-vm`, and not an inventory host.
- **k8s proxies** (`tag:k8s*`) are only deleted with `--k8s-days`. The home cluster is powered down and expected back, so its proxies are deliberately kept by default.
- Never touched: devices that are online, this machine, devices shared in from other tailnets, and the retired `vps` group.
- `fix-inventory` run alone reflects the live state, so it will not drop a `tailnet_name` override before the rename has actually happened.

## Credential

Reads fall back to the local `tailscale status --json`; writes need the API. The credential is a Tailscale **OAuth client** (scopes `devices:core` write and `auth_keys` write, tag `tag:fleet`) created at <https://login.tailscale.com/admin/settings/oauth>. Store it with `just seed-tailnet-oauth`: the secret is verified against Tailscale before it is written to Bitwarden item `tailscale-apikey`. `TS_OAUTH_CLIENT_SECRET` overrides the Bitwarden lookup.

The same secret is the join auth key used by the [`tailscale`](roles/tailscale.md) role. The previous cleanup in that role treated it as a classic API key, got a 401 that `failed_when: false` hid, and never deleted anything; that is why re-joined machines came back as `himachal-1` and `kerala-1`.

## Caveat when renaming

After `rename --apply`, `himachal-1` stops resolving; use the new name. Do not rename while something is using the old MagicDNS name (an rsync or ssh session, for example).
