# tailscale

**Tags:** `secrets`, `tailscale`
**Secrets needed:** Yes (only to *join* — once connected, BW is not required)
**Runs on:** All machines

Installs Tailscale, fetches a reusable auth key from BW, joins the network, configures DNS, and keeps device hostname + advertised routes in sync.

## What it does

1. Configures `systemd-resolved` so MagicDNS works (link `/etc/resolv.conf` to the stub resolver, drop in `DNSStubListenerExtra=::1` for container DNS).
2. Sets `net.ipv4.conf.{all,default}.rp_filter=2` and IP forwarding on, so exit-node and subnet-router traffic actually routes.
3. If `tailscale status` reports connected → updates hostname, prefs, operator, systray, then exits the role.
4. If not connected and the vault is unlocked → fetches `tailscale-apikey` from BW, deletes any stale device with this hostname via the Tailscale API, then `tailscale up --authkey …`.
5. If not connected and the vault is **locked** → emits a one-line warning and ends the role. Joining without a key would either fail noisily or, worse, succeed with an empty key.

## Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| Role aborts with "vault locked" warning, host is not on tailnet | First-time apply on this host without BW unlocked | Unlock BW (`bw unlock --raw | tee /tmp/bw_session > /dev/null`), then `just apply-tags tailscale` |
| Tailscale connected but MagicDNS names don't resolve | `systemd-resolved` link to `/etc/resolv.conf` was overwritten by NetworkManager / DHCP client | The role re-applies it; just re-run `dots-apply`. To make it sticky, check `network-manager` settings (Bluefin does this correctly out of the box) |
| Duplicate device entries in admin console after rebuild | API-key device cleanup didn't run (vault locked at the time) | Manually delete in [tailscale admin console](https://login.tailscale.com/admin/machines) or unlock vault and re-apply |
| Joins but no routes advertised | `tailscale_advertise_routes` not set in `host_vars` | Add it: `tailscale_advertise_routes: "192.168.0.0/24"` (or similar) |

## How to verify

```bash
tailscale status                # should show all fleet machines as peers
tailscale ip -4                 # this host's 100.x.x.x
host bihar.manatee-basking.ts.net   # MagicDNS resolves to a 100.x.x.x
```

## Notes

- All fleet machines are on the `manatee-basking.ts.net` tailnet.
- The auth key is reusable — new machines join without re-authentication.
- The Tailscale API key (`tailscale-apikey` in BW) is the same item used for joining and for device cleanup; rotate by editing the BW item and re-running this role on each host.
