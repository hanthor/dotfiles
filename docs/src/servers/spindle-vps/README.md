# Spindle VPS (Matrix and Hive)

The Oracle Cloud VPS in Frankfurt runs the Matrix homeserver that was on the AWS Talos cluster,
terminated 2026-10-25. **Spindle**, **MAS** (delegated login), **Postgres** (MAS database only),
standalone **LiveKit** and **lk-jwt-service** (MatrixRTC; no ESS chart/runtime), and **Caddy** run
as Docker Compose services under `/srv/spindle`.

The School and Reef Hives, Hub and branded hub frontend run separately under `/srv/hives`, sharing
the `spindle_default` network and Caddy ingress. The `omp-auth-broker` user service also runs on
this host. The Hive deployment's runtime configuration and data are not restored by `deploy.sh`;
preserve and back them up separately.

| Piece | Source |
|---|---|
| Host | Oracle Cloud Always Free, `VM.Standard.A1.Flex`, Ubuntu 24.04 aarch64, `eu-frankfurt-1` AD-1; public IPv4 `92.5.82.232`, Tailscale `100.113.75.88` |
| Spindle | `ghcr.io/tuna-os/spindle:perf-723-de17805-arm64`, the production commit (`main` + #723, amd64 digest `7021ada8…`) built for arm64 from `tuna-os/spindle` branch `ops/arm64-perf-723` |
| MatrixRTC | `livekit-server:v1.13.5` + `lk-jwt-service:0.6.0` as standalone containers |
| Data | `ess_ess-spindle-data.tar.gz` (the store, taken 15:33 UTC) and `postgres/2026-10-25/mas.dump` (15:22 UTC), from `~/backups/tunaos-aws-2026-10-25` on himachal-1 |
| Config | production runtime + delegated-auth block, MAS under/overrides and LiveKit template; deploy.sh renders credentials from cluster-state |

MatrixRTC is enabled by the standalone services above. `element-admin` (`matrixadmin.reilly.asia`)
remains unmigrated.

## 1. Create the instance (Oracle console)

- Shape `VM.Standard.A1.Flex`. `spindle` is in `eu-frankfurt-1`, AD-1, with 2 OCPU / 12 GB; stay
  within that Always Free ceiling. Spindle is capped at 7 GiB, LiveKit at 2 GiB / 1 OCPU.
- Image: Canonical Ubuntu 24.04 (aarch64); 100-GB boot volume.
- Assign and reserve a public IPv4. Paste [`cloud-init.yaml`](cloud-init.yaml); it installs Docker,
  opens direct host 80/443, and authorizes the punjab and himachal-1 SSH keys.
- In the OCI security list allow TCP **80, 443, 30001** and UDP **32700–32767** from
  `0.0.0.0/0`. Remove the default public SSH rule after tailnet access works.
- Oracle may reclaim idle Always Free instances. We accept that risk and will not upgrade this
  tenancy to a paid account. Cloud-init package installation failed on the existing instance and
  required manual installation; check `cloud-init status --long` and installed packages before deploy.

A1 capacity is often "out of host capacity"; retry another availability domain or region later.

## 2. Deploy (on himachal-1)

```bash
cd ~/.local/share/dotfiles/docs/src/servers/spindle-vps   # a checkout of this branch
./deploy.sh <vps-tailnet-ip-or-host>  # SSH destination; use the tailnet address after lockdown
./deploy.sh --render-only /tmp/r   # just render the configs (contains secrets; delete after)
```

It renders the secrets from `cluster-state.himachal.tar.gz.age`, copies the kit to `/srv/spindle`,
streams the store (excluding `store.pre723`), restores `mas.dump`, runs `mas database migrate` and
starts the stack. Restore markers prevent re-importing the original snapshots on a normal rerun;
do not remove those markers or restore old data over live data. The script restarts Spindle and
Caddy, causing an interruption. Nothing secret is printed or committed.

The supplied Caddyfile includes the Hive routes. Do not deploy a Matrix-only Caddyfile over the
shared live configuration: doing so removes Hive TLS sites and causes Cloudflare 525 errors.

## 2b. Join the tailnet and lock down

```bash
ssh ubuntu@<ip> 'sudo tailscale up --hostname=spindle --ssh=false'   # prints a login URL; approve it
ssh ubuntu@spindle true                                              # confirm SSH over the tailnet
scp lockdown.sh ubuntu@spindle: && ssh ubuntu@spindle 'sudo ./lockdown.sh'
```

Then delete the public SSH rule from the OCI security list. Docker publishes the listed LiveKit
ports; keep the OCI ingress list in sync with all public ports in `compose.yaml`.

## 3. DNS cutover

Cloudflare DNS-only A records for `matrix.reilly.asia`, `auth.reilly.asia`, and
`call.reilly.asia` point to the VPS at `92.5.82.232` with a 60-second TTL. `call` must remain
DNS-only: its UDP media ports do not pass through Cloudflare's HTTP proxy.

Verify the public endpoints:

```bash
curl https://matrix.reilly.asia/_matrix/client/versions
curl https://auth.reilly.asia/.well-known/openid-configuration
curl https://reilly.asia/.well-known/matrix/client
curl -i https://call.reilly.asia/sfu/get  # GET should return 405
curl https://school.tunaos.org/api/health
curl https://reef.tunaos.org/api/health
curl https://hub.tunaos.org/api/fleet-stats
```

The apex `reilly.asia` is a Cloudflare Worker custom domain (`reilly-asia`) serving the personal
portfolio and active Matrix client `.well-known` document. Keep it on the Worker; pointing the apex
at this VPS or removing the Worker domain would take the homepage offline. The Worker advertises the
same `https://call.reilly.asia` MatrixRTC service as this deployment.

`call.reilly.asia` routes JWT requests to the standalone `lk-jwt-service` and LiveKit signaling to
the standalone SFU. The separate authorizer preserves federated Matrix participants; Spindle's
built-in minter only supports local users.

This is manual DNS cutover, not automatic failover. The zone is on Cloudflare Free; health-checked
Load Balancing is an add-on, and no second Matrix origin is available. A 60-second TTL only limits
resolver caching; it does not detect failures or switch records automatically.

The authorizer resolves `matrix.reilly.asia` and `call.reilly.asia` through Docker's host gateway
to avoid public-IP hairpin routing; `reilly.asia` remains on the portfolio Worker.

## Caveats

- The MAS dump is from 15:22 UTC. The Spindle store's last write was 15:25 UTC and its archive was
  taken at 15:33 UTC; the old cluster continued until 17:16 UTC. Writes after the store archive are
  only in the encrypted cluster-state backup and are not in this VPS store. A real login and joined
  room read passed against the VPS, but that does not prove the later writes were restored.
- The AWS cluster is terminated. The S3 and himachal-1 backups are untouched, but stopping the VPS
  stack is an outage, not a rollback; recovery requires provisioning and restoring from backup.
- When `tuna-os/spindle` publishes an arm64 release containing #723, switch the image in
  `compose.yaml` and delete the `ops/arm64-perf-723` branch.
- LiveKit is capped at 2 GiB and 1 OCPU to leave room for Spindle and the Hives on this 2-OCPU host;
  suitable for light personal calls, not high-concurrency conferencing. No TURN relay is configured,
  so clients on networks that block UDP may fail to connect.
