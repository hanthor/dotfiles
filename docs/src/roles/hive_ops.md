# hive_ops

**Tags:** `hive`, `hive_ops`  
**Default:** `hive_ops_enabled: false`  
**Credentials:** no Bitwarden lookup in this role; its Kubernetes kubeconfig contains credentials.

> **Retired AWS-cluster integration, not the current Hive operations guide.**
> The AWS Talos cluster was terminated on 2026-10-25. The current school and
> reef spokes and hub run as Docker Compose services on the
> [Spindle VPS](../cluster/hive.md#current-deployment-spindle-vps). Do not
> enable this role or run its old Kubernetes helpers against that deployment.

The role still exists in the repository. When enabled it installs host user
units and scripts that use `kubectl` against `~/.kube/config-aws-migration` by
default; they do not manage the Compose services. Historically these units ran
on telengana against its local k3s, then on himachal against AWS. The cluster
CronJobs and operator controllers that later replaced parts of this work are
also historical: the AWS cluster no longer exists.

## Observed and configured state

`host_vars/himachal.yml` sets `hive_ops_enabled: false`. On 2026-10-27,
read-only SSH to `james@himachal-1` found all seven role timer units
`not-found` and inactive. This observation is not a fleet-wide timer audit;
a host-vars value alone does not establish a host's live state.

When disabled, the role's cleanup runs only if
`~/.config/systemd/user/hive-watchdog.timer` exists. In that case it attempts
to stop/disable the seven timers and remove their units, drop-ins and helper
scripts. If the sentinel is absent, the cleanup block does not run; do not
assume that it removed every possible leftover. The role was not applied as
part of this documentation update.

## Historical unit inventory

The checked-in unit files describe the old DeepSeek-era setup, not the current
`omp` seed configuration on Spindle. Their schedules are:

| Timer | Checked-in schedule | Historical purpose |
|---|---|---|
| `hive-rotate` | 10 min after boot, then 20 min after activation | Rotate backends based on provider headroom |
| `hive-watchdog` | 3 min after boot, then every 5 min | Probe and heal agents |
| `hive-tiers` | Monday 04:30 UTC, up to 30 min random delay | Refresh model tiers |
| `hive-peak-pause` / `hive-peak-resume` | Weekdays 01:00 and 06:00 / 04:00 and 10:00 UTC | Pause/resume around DeepSeek peak windows |
| `pi-peak-stop` / `pi-peak-start` | Weekdays 01:00 and 06:00 / 04:00 and 10:00 UTC | Stop/start local `pi.service` around those windows |

When enabled, the role installs `hive-peak.sh`, `hive-rotate.sh`, and
`hive-tiers.sh` and writes service drop-ins for `KUBECONFIG` and `PATH`.
The drop-ins made Kubernetes and Homebrew tools available to the systemd user
manager; they do not make the legacy scripts suitable for the VPS.

## Variables retained in the role

| Variable | Default | Historical purpose |
|---|---|---|
| `hive_ops_enabled` | `false` | Opt a host in; multiple operators could conflict |
| `hive_ops_kubeconfig` | `~/.kube/config-aws-migration` | AWS cluster credentials |
| `hive_ops_path` | Homebrew plus system paths | Find `kubectl` and `jq` in user services |
| `hive_ops_timers` | Seven timers above | Units deployed or cleaned up |
