# fleet_facts

Publishes each machine's **public** device facts for the live fleet view at
[reilly.asia/infra](https://reilly.asia/infra/#fleet).

- **Runs on:** every host (opt out with `fleet_facts_publish: false`), last in
  the play, including the no-secrets daily timer
- **Tags:** `facts`, `fleet_facts`
- **Needs:** a logged-in `gh` CLI (skipped quietly otherwise)

Each run writes `facts/<host>.json` to the **`fleet-facts`** branch of this
repo through the GitHub contents API. There's no clone and no merge, and
`master` isn't touched. The Worker behind reilly.asia/infra reads those files.

| Field | Source |
|---|---|
| `os.{name,version,codename,kernel}` | Ansible distribution facts |
| `hardware.model` | Android `getprop`, else device-tree model (Pi), else DMI product name (placeholders like "System Product Name" dropped) |
| `hardware.{vendor,form_factor,arch,cpu,cpu_threads,memory_gb}` | Ansible hardware facts |
| `hardware.gpus` | `lspci -mm` display devices (unnamed virtual adapters dropped) |
| `virtualization`, `uptime_days`, `last_apply` | Ansible facts, `~/.cache/dotfiles/last-apply.json` |

**Never published:** IP/MAC addresses, serial numbers, usernames, anything
from Bitwarden.

## Private drift monitoring (`osquery`)

The separate `osquery` role watches changes that must **not** go to the public
`fleet-facts` branch. It installs checksum-pinned upstream osquery 5.23.1 under
`/opt`, including on immutable desktops: no package layering, writable `/usr`,
reboot, Fleet server, enrollment token, or new network listener.

**Tags:** `osquery`, `services`, `security`. Requires root, glibc Linux, systemd,
and x86_64 or aarch64. Nura/Alpine musl (Kerala) and unrooted Android/Termux are
unsupported; `osquery_supported: false` records that exclusion. Offline hosts
install on their next successful normal apply. `skip_osquery: true` skips the
role; it does not uninstall an already-running daemon. The retired VPS group is
never modified, and Talos nodes are not Ansible-managed.

### What's watched

- TCP listeners and bound UDP ports: address, port, protocol, executable path.
  PIDs are excluded so a process restart alone does not create drift. UDP client
  sockets and temporary development listeners can legitimately change.
- Enabled system startup triggers: service, timer, socket and path symlinks in
  `/etc/systemd/system/*.wants`, `*.requires` and their `/run` equivalents.
  This includes enabled-but-not-started units, without mistaking ordinary
  active/inactive transitions for startup changes. User units and vendor
  dependencies compiled into unit files are outside this query.
- Kernel, OS and osquery versions.

`osqueryd.service` samples every five minutes, writing differential JSON logs
only under `/var/log/osquery` (10 MiB rotation, three retained archives).
`fleet-osquery-report.timer` refreshes a private baseline comparison every
15 minutes. Both have bounded CPU/memory use; audit/event capture and distributed
queries are disabled. Sampling is not real-time intrusion detection or unit-file
content integrity checking.

### Review the fleet

From an updated checkout:

```sh
just apply-tags osquery
just osquery-fleet
just osquery-fleet --host punjab --host dilli
just osquery-fleet --json
```

The controller uses effective Ansible inventory, Tailscale online status and
existing authenticated SSH plus noninteractive sudo. Host-key verification stays
enabled. It shows `ok`, `drift`, `offline`, `unsupported`, `excluded`, `stale` or
`error`; missing/bad reports and failed reads never become `ok`. Reports older
than 30 minutes are stale. Stale/errors return nonzero; ordinary drift and offline
coverage do not. Each result shows its collection time, not a claim of live state.
`--inventory PATH` (or `DOTFILES_INVENTORY`) selects another inventory.

### Always-on poller: Punjab

Punjab has `osquery_poller_enabled: true`. Its system-level
`fleet-osquery-poll.timer` runs every 15 minutes at :02/:17/:32/:47, after the
hosts' report-refresh window, and two minutes after boot. It runs as `ubuntu`,
using that account's existing SSH keys, known hosts and noninteractive sudo.
It does not depend on an interactive SSH agent or copy credentials into Kubernetes.

The role installs a root-managed collector and a minimal inventory under
`/opt/fleet-osquery` and `/etc/fleet-osquery/inventory.yml`. Only connection and
exclusion metadata is copied—not the full effective inventory or Bitwarden facts.
Apply the `osquery` role on Punjab after changing fleet membership or connection
details to refresh this inventory snapshot.

Each poll atomically replaces **one** aggregate:
`/home/ubuntu/.local/state/fleet-osquery/latest.json` (0600, inside a 0700 directory,
owned by `ubuntu`). No unbounded history is kept. Journald gets coverage counts,
not raw addresses or executable paths. Polling never accepts host baselines.

```sh
ssh ubuntu@punjab 'cat ~/.local/state/fleet-osquery/latest.json'
ssh ubuntu@punjab 'systemctl status fleet-osquery-poll.timer --no-pager'
ssh ubuntu@punjab 'sudo -n systemctl start fleet-osquery-poll.service'
```

Offline machines remain explicitly offline. Failed reads/stale reports are saved
as degraded coverage and fail the service; an unusable or empty inventory saves
a timestamped error instead of retaining a supposedly healthy snapshot. If the
process itself cannot run or write, check the service journal and the snapshot's
collection time—an old file is not current health.

`osquery_poller_enabled` defaults to false on other hosts. Setting it false on a
previous poller and applying the role stops its timer and in-flight service;
the last private snapshot remains for inspection. The manual fleet CLI still works
from other machines and supports `--output PATH` for explicit private snapshots.

### Baseline and local investigation

First apply records the machine's **existing** state, not an audited known-safe
state. Later applies never accept new drift automatically. Changes remain pending
against that baseline until reviewed and explicitly accepted:

```sh
sudo systemctl start fleet-osquery-report.service
sudo /opt/fleet-osquery/fleet-osquery report
sudo journalctl -u fleet-osquery-report.service
# Only after reviewing the changes:
sudo /opt/fleet-osquery/fleet-osquery baseline --accept
sudo systemctl start fleet-osquery-report.service
```

Baseline/report/lock files are root-owned mode 0600 in
`/var/lib/fleet-osquery` (0700). Failed collection does not replace the last
successful report or baseline; inspect the failed service and its journal, and
treat an aging cached sample accordingly. Manual CLI runs do not save fetched
reports unless `--output` is supplied; Punjab's scheduled aggregate is described
above. **Keep all report output private:** addresses and executable paths are
sensitive; do not attach raw JSON to public issues or publish it through `fleet_facts`.
No command lines, process environments, credentials or serial numbers are queried.

Check mode reports platform support only; actual installation and baseline
collection require a normal apply. CI exercises the actual role and
`sudo python3 tests/osquery_smoke.py` on x86_64 and aarch64 Ubuntu runners.
That smoke creates a temporary loopback listener and an enabled, never-started
unit, checks pending/accepted/removed drift, and compares a synthetic prior kernel
against the real current kernel. It uses isolated state and removes its fixtures;
the fleet baseline is untouched.
The native CI jobs also enable the persistent poller and run
`tests/osquery_poller_smoke.py`: a real temporary listener must appear in the
aggregate, disappear after removal, and leave the host baseline unchanged.
