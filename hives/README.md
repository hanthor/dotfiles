# hives/ — hosting and failover for the tuna-os hives

Source for the scripts, compose host layers and systemd units that run the
School, Reef and Hub hives on **bihar** (active) with **karnataka** as a cold
standby, coordinated by a lease on **spindle**.

The runbook is [docs/src/servers/hives.md](../docs/src/servers/hives.md). It covers
the design, the install locations, daily operations, failover and the gotchas.

| File | Installed at |
|---|---|
| `hives`, `hive-reconcile`, `hive-sync` | `/var/srv/hives-host/` on bihar and karnataka |
| `compose.<host>.yaml` | `/var/srv/hives-host/` on that host |
| `hive-cleanup` | `/var/srv/hives-host/` on bihar and karnataka |
| `systemd/hive-{reconcile,sync,cleanup}.{service,timer}` | `/etc/systemd/system/` on bihar and karnataka |
| `hanthor/hive.yaml` | seed for the hanthor spoke: `/var/srv/hives/hanthor/config/hive.yaml` (synced to the standby by `hive-sync`) |
| `hanthor/compose.override.snippet.yaml` | the `hanthor` service, appended to `/var/srv/hives/compose.override.yaml` |
| `hive-failover` | `/usr/local/sbin/` on spindle |
| `systemd/hive-failover.{service,timer}` | `/etc/systemd/system/` on spindle |

There is no automated deploy. These files are copies of the deployed versions,
taken on 2026-11-18. Change both the repository and the hosts at the same time.
