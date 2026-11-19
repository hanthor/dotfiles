# Hives hosting and failover

> **TunaOS infrastructure.** This page describes *where and how* the hives run.
> For the hives themselves (agents, configuration, health), see the
> [Hive operations guide](../cluster/hive.md).

Last updated: 2026-11-19 (hanthor added). The source for the scripts, compose layers and systemd
units is [`hives/`](https://github.com/hanthor/dotfiles/tree/master/hives) in this
repository. Each host also has a copy of this runbook at
`/var/srv/hives-host/RUNBOOK.md` (on spindle: `/var/lib/hive-failover/RUNBOOK.md`).

## Overview

The hives run as one compose project named `hives`, with five containers:

| Service | Purpose | Public URL |
|---|---|---|
| `hub` | Hub API that all spokes report to | `https://hub.tunaos.org/api/*`, `/login/*` |
| `hub-front` | Static hub page (nginx) | `https://hub.tunaos.org/` |
| `school` | Spoke for the tuna-os org (GitHub App 3942065) | `https://school.tunaos.org` |
| `reef` | Spoke (GitHub App 5546574) | `https://reef.tunaos.org` |
| `hanthor` | Spoke for the `hanthor/*` personal repositories (App 3942065, installation 158987150). Added 2026-11-19 | `https://hive.reilly.asia` |

Until 2026-11-18 the hives ran on spindle (Oracle ARM VM, Frankfurt, 2 cores and 11 GB of RAM). They now run on **bihar** (x86, 24 cores, 62 GB of RAM). **karnataka** is a cold standby. **spindle** keeps the public IP and Caddy, and it coordinates failover.

```
Internet ─▶ Cloudflare ─▶ spindle Caddy (92.5.82.232)
                              │  tailnet, ports 3100-3104
               ┌──────────────┴──────────────┐
               ▼ (active, holds the lease)    ▼ (standby, stopped)
        bihar 100.103.44.48          karnataka 100.66.158.127
               └── hive-sync every 15 min ──▶
```

Outbound traffic from the hives (to GitHub and the model APIs) leaves through the active host's own internet connection. It does not go through spindle.

The OMP auth broker still runs on spindle at `http://100.113.75.88:8765`, reached over the tailnet.

## Host layout (bihar and karnataka are identical)

| Path | Contents |
|---|---|
| `/var/srv/hives/` | Hive data and configuration, copied from spindle's `/srv/hives`: `compose.yaml`, `compose.override.yaml`, `.env`, `{hub,school,reef,hanthor}/{config,data,secrets}`, `hub-front/`, `proxy/`, `bin/dashboard-*.html` |
| `/var/srv/hives-host/compose.<host>.yaml` | Host layer: ports, memory limits, broker URL, image digests, and the amd64 binary mount |
| `/var/srv/hives-host/bin/hive-2ef7dc7c0-amd64` | `tuna-os/hive` at `2ef7dc7c0` (branch `deploy/upstream-v6-20261113`) built with `CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -trimpath ./cmd/hive` |
| `/var/srv/hives-host/hives` | Wrapper that runs docker-compose against rootful podman with the three compose files |
| `/var/srv/hives-host/hive-reconcile` | Makes the host follow the lease (timer, every 1 min) |
| `/var/srv/hives-host/hive-sync` | Pushes the data to the peer host (timer, every 15 min) |
| `/var/srv/hives-host/keys/` | `lease` (read-only access to the lease on spindle) and `sync` (rsync to the peer host) |
| `/var/srv/hives-host/maintenance` | If this file exists, reconcile does not start the hives |

Each host publishes its ports on its own tailnet IP only:

| Port | Service |
|---|---|
| 3100 | hub-front |
| 3101 | hub |
| 3102 | school |
| 3103 | reef |
| 3104 | hanthor |

A firewalld rich rule in the `public` zone accepts these ports only from spindle (`100.113.75.88`). Inside the compose network the services reach each other by name, for example `http://hub:3001`. The podman network is named `spindle_default` so that `compose.yaml` works unchanged.

Images are pinned by digest, and the pin must match the binary:
- `ghcr.io/hivecommons/hive@sha256:d56425fb…` (school, reef and hanthor)
- `ghcr.io/hivecommons/hive-hub@sha256:3c0162eb…` (hub)

Do not change to `:v6-latest`. On 2026-11-18 a newer image made the hub log "failed to write token cache". **Upgrade the binary and the images together.**

## Daily operations (on the active host)

```bash
sudo /var/srv/hives-host/hives ps
sudo /var/srv/hives-host/hives logs -f --tail 50 school
sudo /var/srv/hives-host/hives restart reef
sudo podman stats --no-stream
```

To find the active host, run this on spindle:

```bash
sudo hive-failover status
```

The command shows the lease, the health and container count of each host, and the targets in Caddy.

### Change the hive configuration
1. Edit the files under `/var/srv/hives/` on the active host only.
2. Run `sudo /var/srv/hives-host/hives up -d`.

The next `hive-sync` copies the change to the standby.

### Change a host-specific setting
1. Edit `/var/srv/hives-host/compose.<host>.yaml` on **both** hosts. This covers ports, memory and image pins.
2. Run `sudo chcon -t container_file_t` on the file.

### Upgrade the hive binary
1. Build the amd64 binary from the fork commit.
2. Copy it to `/var/srv/hives-host/bin/` on both hosts.
3. Change the binary mount and the image digests in both host files.
4. Run `hives up -d` on the active host.

## Failover

### The lease
The file `spindle:/var/lib/hive-failover/active` contains `bihar`, `karnataka` or `none`. Only the host named in the lease may run the hives. This rule prevents two hosts from running the same GitHub Apps at once.

| Component | Where | Schedule | What it does |
|---|---|---|---|
| `hive-failover check` | spindle, `hive-failover.timer` | every 1 min | Checks the active host on ports 3101-3103. After 5 min of failures it sets the lease to `none`, stops the old host if it can, and waits. When the old host has 0 containers, or after 10 min, it starts the standby, sets the lease, changes Caddy and sends a ntfy notification on `$NTFY_TOPIC`. |
| `hive-reconcile` | both hosts, `hive-reconcile.timer` | every 1 min | If the lease names this host and fewer than 4 containers run, it starts them (unless `maintenance` exists). If the lease names a different host, it stops them. If it cannot read the lease for 8 min, it stops them (self-fence). |
| `hive-sync` | both hosts, `hive-sync.timer` | every 15 min | If the lease names this host, it uses rsync to push `/var/srv/hives` to the peer, without caches and toolchains. |
| `hive-cleanup` | both hosts, `hive-cleanup.timer` | every 1 h | On running spokes only: removes idle Claude session scratch and stale work dirs in `/tmp` inside the containers, removes dangling images and old backups, and warns when `/var` has less than 10 GB free. Ported from spindle, where the writable layers of the hive containers had reached 16.8 GB. |

Logs:

```bash
journalctl -t hive-failover                # on spindle
journalctl -u hive-reconcile -u hive-sync  # on the hosts
```

The podman containers have restart policy `unless-stopped` and `podman-restart.service` is disabled. As a result, a host that boots does not start the hives itself. Only reconcile starts them, and only when the lease names that host.

### Commands (on spindle)

```bash
sudo hive-failover status
sudo hive-failover move bihar       # planned move or failback: stop, sync, start, Caddy
sudo hive-failover move karnataka
sudo hive-failover hold on          # pause automatic failover (for example during maintenance)
sudo hive-failover hold off
```

`move` sets `hold on` while it runs, and clears it when it succeeds. If `move` fails, the lease stays at `none` and hold stays on. Correct the problem and run `move` again.

### After an automatic failover
The hives run on karnataka. Failback is manual, so that an unstable WiFi connection cannot move the hives back and forth.
1. Make sure bihar is up: `ssh james@bihar uptime`.
2. Run `sudo hive-failover move bihar` on spindle. It takes about 1 min.

### Planned maintenance on bihar
Use one of these methods:
- Run `sudo hive-failover move karnataka` first.
- Or run `sudo hive-failover hold on` on spindle, then `sudo touch /var/srv/hives-host/maintenance` and `hives stop` on bihar. When you finish, remove the file and run `hold off`.

### Limits
- The data on the standby can be up to 15 min old. Rsync copies files while they are in use, so a file that changes during the copy can arrive in an inconsistent state.
- The self-fence after 8 min without spindle was tested by hand only. A real network partition has not been tested.
- If spindle is down, there is no public access and no failover. The hosts stop the hives after 8 min, because they cannot read the lease.

### Drill on 2026-11-18
1. Hives stopped on bihar at 13:55:44Z.
2. Spindle revoked the lease at 14:01:29Z.
3. Karnataka was healthy and Caddy changed at 14:01:56Z.
4. `move bihar` completed in 50 s, including the sync back.

## Gotchas
- **SELinux (bihar and karnataka are bootc and enforcing):**
  - Files mounted into containers must have the type `container_file_t`. `semanage` cannot write on bootc, so `hive-sync` runs `chcon -R` after each copy. Do not copy SELinux attributes with rsync (`-X`).
  - systemd cannot run scripts that have the label `var_t` (the result is `203/EXEC Permission denied`). For this reason the units start the scripts as `/usr/bin/bash /var/srv/hives-host/<script>`. Do not use `chcon` on the scripts.
  - Under systemd, rsync changes to the confined `rsync_t` domain, and its ssh cannot read the key. `hive-sync.service` therefore runs as `SELinuxContext=system_u:system_r:unconfined_t:s0`. `setsebool -P` has no effect on bootc.
  - **Until 2026-11-18 18:50Z, the reconcile and sync timers did not run because of these two problems.** The failover drill passed only because spindle sent the commands directly over SSH. After you change a unit, use `systemctl show <unit> -p Result` to make sure that it ran.
- **The Caddyfile on spindle is a single-file bind mount:** `sed -i` makes a new inode, and Caddy continues to see the old file. Write in place (`cat new > Caddyfile`), or run `docker cp Caddyfile spindle-caddy-1:/tmp/Caddyfile` then `docker exec spindle-caddy-1 caddy reload --adapter caddyfile --config /tmp/Caddyfile`. `hive-failover` does both.
- **The spindle-to-host path uses a relay:** it goes through Tailscale DERP (Frankfurt), with approximately 170 ms of latency and 1 MB/s. This is sufficient for dashboard and API traffic.
- **Disk:** the caches (Go build, rustup and others) are not synced. After a move, the first builds on the new host are slower.
- **Use separate SSH keys:**
  - `spindle:/root/.ssh/hive_failover` gives access to `james@` on both hosts.
  - The `lease` key of each host gives `ubuntu@spindle` with a forced command: `cat /var/lib/hive-failover/active`.
  - The `sync` key of each host gives `james@` on the peer host.

## Install or rebuild a host

The files in [`hives/`](https://github.com/hanthor/dotfiles/tree/master/hives) go to these locations:

| Repository file | Destination |
|---|---|
| `hives`, `hive-reconcile`, `hive-sync` | `/var/srv/hives-host/` on bihar and karnataka (mode 0755) |
| `compose.<host>.yaml` | `/var/srv/hives-host/` on that host |
| `hive-cleanup` | `/var/srv/hives-host/` on bihar and karnataka (mode 0755) |
| `systemd/hive-{reconcile,sync,cleanup}.*` | `/etc/systemd/system/` on bihar and karnataka |
| `hive-failover` | `/usr/local/sbin/` on spindle |
| `systemd/hive-failover.*` | `/etc/systemd/system/` on spindle |

On a new host, also do these steps:
1. Install `docker-compose` with brew.
2. Run `systemctl enable --now podman.socket`.
3. Create the podman network `spindle_default`.
4. Pull the pinned images.
5. Copy `bin/hive-2ef7dc7c0-amd64` from the other host. If neither host has it, build it from `tuna-os/hive` at `2ef7dc7c0`.
6. Create the SSH keys in `/var/srv/hives-host/keys/`, and add the firewalld rule for ports 3100-3104 from spindle. Also install `/etc/sysctl.d/90-hives-inotify.conf` (`fs.inotify.max_user_instances = 1024`, `fs.inotify.max_user_watches = 1048576`): with five containers the per-agent permission watchers exhaust the default of 128 instances.
7. Label the data and compose files (not the scripts): `chcon -R -t container_file_t /var/srv/hives /var/srv/hives-host/compose.*.yaml /var/srv/hives-host/bin`.
8. Enable `hive-reconcile.timer`, `hive-sync.timer` and `hive-cleanup.timer`. Start each service one time and make sure that its `Result` is `success`.

## Rollback to spindle (emergency only)
On 2026-11-18 the cleanup removed the stale data copies, the arm64 binaries, and the hive containers and images on spindle. `/srv/hives` contains only the compose files, `.env`, `<svc>/config`, `<svc>/secrets` and `backups/`. karnataka is the fallback. Use spindle only if both hosts are lost:
1. On spindle, run `sudo hive-failover hold on`.
2. Build an arm64 binary from `tuna-os/hive` at `2ef7dc7c0` (`GOARCH=arm64`) and copy it to `/srv/hives/bin/`.
3. Copy the newest `/var/srv/hives` from bihar or karnataka to spindle (`<svc>/data`, without `.cache`).
4. Change the hive blocks in Caddy back to `school:3001`, `reef:3001`, `hub:3001` and `hub-front:80`.
5. Run `docker compose up -d` in `/srv/hives`. Spindle has 2 ARM cores, so reduce `HIVE_SHARED_AGENT_POOL_MAX_SESSIONS` to 2.
