# Bihar

Home server, the primary host for the hives, and the KubeStellar hub. Since
2026-11-17 it runs Bluefin, not Talos. The [Talos page](../archive/talos-home-cluster/bihar/README.md)
is archived.

| | |
|---|---|
| Hardware | ASRock B660M-STX, Intel, 24 threads, 62 GB of RAM |
| Disk | 1.9 TB NVMe (`/var`) |
| OS | Bluefin `ghcr.io/projectbluefin/utah:testing` (bootc: read-only `/usr`, writable `/etc` and `/var`) |
| Network | **WiFi** (`wlp3s0`). Not on the same LAN as karnataka. |
| Tailnet | `bihar` / `100.103.44.48` (`bihar.manatee-basking.ts.net`) |
| Access | `ssh james@bihar` (passwordless sudo through `/etc/sudoers.d/zz-james`) |
| Ansible | Yes: [`host_vars/bihar.yml`](https://github.com/hanthor/dotfiles/blob/master/host_vars/bihar.yml), `skip_pipewire_audio: true` |

## Roles

1. **Active hive host.** The hive containers (hub, hub-front, school and reef) run
   under rootful podman compose, and spindle's Caddy sends public traffic to them.
   See [Hives hosting and failover](hives.md).
2. **k3s and KubeStellar hub.** A single-node k3s runs KubeStellar 0.30.2, with
   ITS `its1` and WDS `wds1`. bihar and karnataka are both workload clusters.
   See [Home k3s and KubeStellar](home-k3s.md).

## Host settings (applied 2026-11-17)

- **No sleep:** the sleep, suspend and hibernate targets are masked, the
  `90-nosleep.conf` drop-ins are in `/etc/systemd/{sleep,logind}.conf.d/`, and
  the GDM dconf `sleep-inactive-ac-type='nothing'` is set. Before this change,
  GNOME suspended the host after 15 min idle, and the host went offline.
- **Default target is `multi-user.target`:** no graphical login. Use
  `systemctl isolate graphical.target` to start one.
- **Wake-on-LAN** is set to `magic` on `enp0s31f6`. The host uses WiFi, so
  wake-on-LAN works only if you connect a cable.
- **To do:** in the firmware, set "Restore on AC/Power Loss" to **Power On**.
  This setting is necessary because the hives depend on this host.
- Dotfiles bootstrap fixes for a new bootc host are in
  [hanthor/dotfiles#385](https://github.com/hanthor/dotfiles/pull/385).
- Bitwarden phase 2 is not done yet. Run `just apply -e skip_pipewire_audio=true` from an
  interactive terminal.

## Timers

| Unit | Purpose |
|---|---|
| `hive-reconcile.timer` | Follows the hive lease on spindle (every 1 min) |
| `hive-sync.timer` | Pushes the hive data to karnataka while bihar is active (every 15 min) |
| `fleet-osquery-report.timer` | Fleet facts |
| `tailscale-cert-renew.timer` | Tailscale TLS certificate |

## Gotchas

- Do not use `pkill -f <pattern>` over SSH if the pattern also occurs in the SSH
  command line. The command stops your own session.
- `gsettings` over SSH needs `DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`.
- `semanage` cannot write on bootc. Use `chcon` for SELinux labels.
