# hive_ops

**Tags:** `hive`, `hive_ops`
**Secrets needed:** No (uses the AWS cluster kubeconfig from the `kube` role)
**Runs on:** Opt-in — exactly one host (`hive_ops_enabled: true`)

Drives the [tuna-os Hive](https://hive.tunaos.org) running on the
[AWS Talos cluster](../servers/aws-k8s/cluster.md): backend rotation, a
watchdog, capability tiers, and peak/off-peak scheduling.

These previously lived as hand-managed user units on `telengana`, talking to a
local k3s via `sudo -n k3s kubectl`. When telengana was retired they were moved
into this role and retargeted at plain `kubectl` against the AWS cluster.

## What It Does

Deploys three scripts to `~/.local/bin/` and seven user timer/service pairs:

| Timer | Schedule | Does |
|---|---|---|
| `hive-rotate` | every 5 min | Capability-preserving backend rotation — fails agents over between providers on headroom |
| `hive-watchdog` | every 5 min | Health check / unwedge |
| `hive-tiers` | weekly | Refresh capability tiers |
| `hive-peak-pause` / `hive-peak-resume` | 01:00 / 04:00 | Pause agents during the provider's peak-price window |
| `pi-peak-start` / `pi-peak-stop` | 04:00 / 01:00 | Start/stop the local `pi.service` around DeepSeek off-peak pricing |

Peak windows default to `01:00-04:00,06:00-10:00` for `deepseek` and are
overridable via `HIVE_PEAK_WINDOWS` / `HIVE_PEAK_PROVIDERS`.

## Why the drop-in exists

The scripts reach the hive through `kubectl exec` into the pod. Two things
break that under systemd that don't break it interactively:

1. **`KUBECONFIG` is unset** — there is no shell rc file to source.
2. **The systemd *user* manager's PATH is `/usr/local/bin:/usr/bin:/snap/bin`**,
   which excludes Homebrew — where `kubectl` and `jq` actually live.

Both fail *opaquely*: the scripts capture `kubectl` output with `2>/dev/null`,
so a missing binary surfaces as `ERROR: no hive pod found` rather than
"command not found". The role writes a `.service.d/kubeconfig.conf` drop-in
pinning `KUBECONFIG` and `PATH` for every unit.

This is why it worked on telengana without a drop-in: `k3s` sits on the
standard PATH, Homebrew does not.

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `hive_ops_enabled` | `false` | Opt a host in. Two hosts both rotating would fight each other. |
| `hive_ops_kubeconfig` | `~/.kube/config-aws-migration` | Cluster to drive |
| `hive_ops_path` | `/home/linuxbrew/.linuxbrew/bin:…` | PATH for the units |
| `hive_ops_timers` | 7 timers | Which units to deploy/enable |

## Notes

- Prefer `hive-peak.sh status|pause|resume` over hand-rolled curl — the
  authentication path is subtle (see the `tunaos-hive-checkin` skill).
- `hive-rotate.sh apply` takes **~2 minutes** — it makes many `kubectl exec`
  round-trips. Don't mistake a short timeout for a failure.
- Currently enabled on `himachal`, a desktop. That is a **reliability
  downgrade** from the always-on VPS it came from: if himachal is off or
  asleep, rotation and peak windows silently don't fire. The robust home for
  these is Kubernetes `CronJob`s on the cluster itself.
