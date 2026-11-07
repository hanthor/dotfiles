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
| Spindle | `ghcr.io/tuna-os/spindle:outbox-hotfix-arm64` (deployed 2026-11-06): production's `ops/legacy-media-compat` build plus the concurrent federation outbox from `tuna-os/spindle` PR #794 and the row-hashed transaction IDs of #762, built for arm64 from branch `ops/outbox-hotfix`. The previous image, `legacy-media-compat-arm64`, sent outbound federation one server at a time and stalled behind dead servers |
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
the standalone SFU. The separate authorizer preserves federated Matrix participants: the built-in
minter of the deployed image only supports local users (tuna-os/spindle#800 adds the others).

This is manual DNS cutover, not automatic failover. The zone is on Cloudflare Free; health-checked
Load Balancing is an add-on, and no second Matrix origin is available. A 60-second TTL only limits
resolver caching; it does not detect failures or switch records automatically.

The authorizer resolves `matrix.reilly.asia` and `call.reilly.asia` through Docker's host gateway
to avoid public-IP hairpin routing; `reilly.asia` remains on the portfolio Worker.

## 4. Consolidation: Spindle replaces MAS and lk-jwt-service (not deployed)

`consolidate.sh` and `consolidated/` move this stack to three services: Spindle, LiveKit and Caddy.
Spindle's built-in OIDC provider takes over login on the same issuer, `https://auth.reilly.asia/`.
Its built-in LiveKit minter takes over call tokens. `spindle import-mas` copies the accounts from
MAS. Postgres held only MAS's database, so it stops too. `./mas` and `./pg` stay on disk for the
rollback. Parent issue: tuna-os/spindle#796.

### Prerequisites

The Spindle image (`SPINDLE_IMAGE`, arm64) must be one build that contains all of these:

| Change | Why |
|---|---|
| tuna-os/spindle#791 (merged) | `auth.oidc_issuer`: the built-in provider on `auth.reilly.asia` |
| tuna-os/spindle#799 (merged), built with `--build-arg FEATURES=mas-import` | `spindle import-mas`. Release images do not have it; tuna-os/spindle#802 |
| tuna-os/spindle#800 (open) | the minter for other servers' users, the SFU webhook, `full_access_servers`, no `//` in its URLs |
| tuna-os/spindle#794 (merged) | the concurrent outbox that production runs now |
| tuna-os/spindle#736 (open) | the legacy media URLs that production serves now (`ops/legacy-media-compat`) |

Production must already run this image, upgraded in a change of its own. The cutover then changes
configuration only. The script stops if the running image is a different one
(`ALLOW_IMAGE_CHANGE=1` overrides this). To build the image, use a branch workflow such as
`arm64-outbox-hotfix.yml` with `docker build --build-arg FEATURES=mas-import`.

What production MAS has (read on 2026-11-07, `mas/config.yaml` and its database):

- no upstream identity providers, in the config or the database. Thus `consolidated/spindle.base.toml`
  has no `[[auth.upstream_oidc]]`. If you add a provider to MAS before the cutover, add it there
  too, with the provider's ULID as `id`.
- no `passwords:` section. Thus all passwords use MAS's default scheme: version 1, Argon2id, no
  pepper. All 5 users have such hashes. The import gets `--mas-config` anyway.
- password registration off. Spindle's registration is open by default, so the consolidated config
  sets `[registration] require_token = true`.

### What changes for users

- Each user signs in again one time. MAS sessions do not move. Old devices stay in each device
  list until the user removes them.
- The issuer, the account page (`https://auth.reilly.asia/account/`) and the reilly.asia Worker's
  `.well-known` stay the same. The Worker still names `https://call.reilly.asia` as the call
  transport. Caddy sends its `/sfu/get` and `/get_token` to the minter. Spindle's own
  `/rtc/transports` names `https://matrix.reilly.asia/_spindle/rtc/livekit`. You can change the
  Worker to that URL later.
- Sign-in with a QR code (MSC4108) stops. It needs the OAuth device-authorization grant, which
  MAS has and the built-in provider does not (tuna-os/spindle#112).
- Call tokens last 15 minutes instead of an hour (`token_ttl_seconds`). Users of other servers
  join and subscribe; only reilly.asia users publish, as before.

### Run it

```bash
./consolidate.sh --render-only /tmp/c                  # no secrets needed or read
SPINDLE_IMAGE=ghcr.io/tuna-os/spindle:<tag>-arm64 \
SMOKE_USER=<localpart> SMOKE_PASSWORD=<password> SMOKE_ROOM='!room:reilly.asia' \
  ./consolidate.sh <vps-tailnet-ip-or-host>
```

The cutover can run from any host with SSH to the VPS. It uses no cluster-state, because it reads
the two secrets it needs (the LiveKit secret, the MAS database password) on the VPS. It:

1. checks that the MAS stack runs, that `SPINDLE_IMAGE` is the running image and has
   `import-mas`, and that the disk can hold a copy of the store;
2. stages the new files in `/srv/spindle/consolidation/<timestamp>/new` and fills the LiveKit
   secret from the live `livekit.yaml`, so the SFU keeps its key;
3. copies the live `compose.yaml`, `Caddyfile`, `spindle.toml` and `livekit.yaml` to
   `…/<timestamp>/backup`, stops Spindle, MAS and lk-jwt-service (the outage starts), dumps the
   MAS database to `backup/mas.dump` and copies the store to `backup/store`;
4. runs `spindle import-mas --dry-run`, then the import. Each report goes to
   `…/<timestamp>/reports`. If something is refused, the script starts the previous stack again,
   with nothing switched;
5. switches the four files, marks `/srv/spindle/.consolidated` (after this, `deploy.sh` refuses
   to run), starts the stack with `--remove-orphans` (MAS, Postgres and lk-jwt-service go), and
   restarts LiveKit and Caddy;
6. runs the smoke checks: `/versions`, the provider's discovery and `auth_metadata` on the issuer,
   the sign-in page, password login flows, token-gated registration, the minter's routes on both
   hosts, LiveKit, and the SFU webhook from the compose network. With `SMOKE_*` it also logs in,
   checks `/rtc/transports`, gets a call token from both transport URLs (publish grant, hashed
   room) and logs out. Run them again with `./consolidate.sh --smoke <vps>`.

The LiveKit webhook goes to `http://spindle:8008/_spindle/rtc/livekit/sfu/webhook`. The minter
creates each call's room through `https://call.reilly.asia`. Compose maps that name to the host
gateway, as it did for lk-jwt-service.

### Roll back

```bash
./consolidate.sh --rollback <vps-tailnet-ip-or-host>    # ROLLBACK_FROM=<timestamp> for an older one
```

This puts back the four saved files and starts MAS, Postgres and lk-jwt-service with their data,
which the cutover did not change. Then it checks that `auth.reilly.asia` is MAS again. The import
changed nothing in MAS. The accounts that it wrote stay in the store, and delegation ignores them.
`RESTORE_STORE=1` also puts back the store copied before the import, but you lose everything
written after the cutover. Clients that signed in through Spindle's provider sign in again through
MAS: their token refresh goes to `auth.reilly.asia`, which is MAS again.

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
- `compose.yaml` here is ahead of production: Renovate moved it to MAS 1.28.0, lk-jwt-service
  0.9.0 and LiveKit v1.13.11, and production still runs 1.23.0, 0.6.0 and v1.13.5 (2026-11-07).
  From 0.7, lk-jwt-service expects to run as an appservice of the homeserver (option C in
  Spindle's `docs/matrix-rtc.md`), so `deploy.sh` as written changes call behavior. The
  consolidation rollback restores the files that production runs, not these.
