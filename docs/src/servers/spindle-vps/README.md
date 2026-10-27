# Spindle VPS (matrix.reilly.asia)

Runs the Matrix homeserver that was on the AWS Talos cluster (terminated 2026-10-25) on one small
host: **Spindle** (the homeserver, embedded store), **MAS** (login; Spindle delegates auth to it),
**Postgres** (MAS's database only) and **Caddy** (TLS). Everything is `docker compose` under
`/srv/spindle`.

| Piece | Source |
|---|---|
| Host | Oracle Cloud Always Free, `VM.Standard.A1.Flex`, Ubuntu 24.04 aarch64 (see below) |
| Spindle | `ghcr.io/tuna-os/spindle:perf-723-de17805-arm64`, the production commit (`main` + #723, amd64 digest `7021ada8…`) built for arm64 from `tuna-os/spindle` branch `ops/arm64-perf-723` |
| Data | `ess_ess-spindle-data.tar.gz` (the store, taken 15:33 UTC) and `postgres/2026-10-25/mas.dump` (15:22 UTC), from `~/backups/tunaos-aws-2026-10-25` on himachal-1 |
| Config | production `runtime-base.toml` + the delegated-auth block, MAS under/overrides, all read from `cluster-state` by `deploy.sh` |

Not migrated: MatrixRTC/LiveKit (`call.reilly.asia`; no `rtc_foci` is advertised, so Element Call is
off) and element-admin (`matrixadmin.reilly.asia`).

## 1. Create the instance (Oracle console)

- Shape `VM.Standard.A1.Flex`. This tenancy (`trogdor3000`, home region `ap-sydney-1`) is limited to
  2 OCPU / 12 GB (`oci limits resource-availability get`), so that is what the instance uses; other
  tenancies may get 4 / 24. Spindle had an 11 GiB ceiling in the cluster; here it is capped at 7 GiB.
  Always Free compute must be in the home region.
- Image: Canonical Ubuntu 24.04 (aarch64). Boot volume 100 GB (free limit is 200 GB total).
- Assign a public IPv4 and **reserve** it so it survives stop/start.
- Under *Advanced options -> Cloud-init script* paste [`cloud-init.yaml`](cloud-init.yaml). It installs
  Docker, opens the host firewall for 80/443 and authorises the punjab and himachal-1 SSH keys.
- In the subnet's security list (or an NSG) allow ingress TCP **80** and **443** from `0.0.0.0/0`
  (22 is open by default).
- Idle Always Free instances can be reclaimed by Oracle. Upgrading the account to pay-as-you-go keeps
  usage inside the free limits at $0 and removes that risk.

A1 capacity is often "out of host capacity"; retry another availability domain or region later.

## 2. Deploy (on himachal-1)

```bash
cd ~/.local/share/dotfiles/docs/src/servers/spindle-vps   # a checkout of this branch
./deploy.sh <vps-ip>            # idempotent; re-run after fixing anything
./deploy.sh --render-only /tmp/r   # just render the configs (contains secrets; delete after)
```

It renders the secrets from `cluster-state.himachal.tar.gz.age`, copies the kit to `/srv/spindle`,
streams the store (excluding `store.pre723`), restores `mas.dump`, runs `mas database migrate` and
starts the stack. Nothing secret is printed or committed.

## 2b. Join the tailnet and lock down

```bash
ssh ubuntu@<ip> 'sudo tailscale up --hostname=spindle --ssh=false'   # prints a login URL; approve it
ssh ubuntu@spindle true                                              # confirm SSH over the tailnet
scp lockdown.sh ubuntu@spindle: && ssh ubuntu@spindle 'sudo ./lockdown.sh'
```

Then delete the public SSH rule from the OCI security list. Only 80/443 stay public.

## 3. Cut DNS over

Point `reilly.asia`, `matrix.reilly.asia` and `auth.reilly.asia` A records at the VPS (Cloudflare
DNS-only is simplest for the first certificate). Caddy fetches Let's Encrypt certificates on first
request.

```bash
curl https://matrix.reilly.asia/_matrix/client/versions
curl https://reilly.asia/.well-known/matrix/client
curl https://auth.reilly.asia/.well-known/openid-configuration
```

## Caveats

- The two data sets are three minutes apart (MAS 15:22, Spindle's last write 15:25 UTC): an account
  created in that window could exist in Spindle but not in MAS.
- The store was tarred after Spindle had stopped writing, but that is inferred from file times;
  do a login and a room read before pointing everyone at it.
- The AWS backup (S3 bucket and himachal-1) is untouched; rollback is "stop the VPS stack".
- When `tuna-os/spindle` publishes a release with an arm64 image that contains #723, switch the image
  in `compose.yaml` and delete the `ops/arm64-perf-723` branch.
