# hive_ops

**Unit:** `hive-ops` (`units/hive-ops.sh`)  
**Tags:** `hive`, `hive_ops`  
**Default:** `hive_ops_enabled: false`  
**Credentials:** no Bitwarden lookup; the configured Kubernetes kubeconfig contains credentials and must already exist for the helpers to access the cluster.

The unit requires `yq` and a working user systemd manager when it performs work. It skips Termux, inventory VPSes, and retired `matrix`/`telengana`.

> **Retired AWS-cluster integration, not the current Hive operations guide.**
> The AWS Talos cluster was terminated on 2026-10-25. The current school and
> reef spokes and hub run as Docker Compose services on the
> [Spindle VPS](../cluster/hive.md#current-deployment-spindle-vps). Do not
> enable this unit or run its old Kubernetes helpers against that deployment.

When enabled, the unit installs three helpers from `units/hive-ops/bin/` and service/timer pairs from `units/hive-ops/systemd/`. The default list in `units/hive-ops/defaults.yml` includes rotation, watchdog, tiers, Hive peak pause/resume, and pi peak start/stop. A host may override `hive_ops_timers`, `hive_ops_kubeconfig` (default `~/.kube/config-aws-migration`) and `hive_ops_path`. A drop-in pins KUBECONFIG and PATH for each service. Only enable one controller so timers do not compete.

The helpers use `kubectl` against the terminated AWS cluster by default; they do not manage the Compose services. Historically they ran on telengana against its local k3s, then on himachal against AWS. The cluster CronJobs and operator controllers that later replaced parts of this work are also historical.

## Observed and configured state

`host_vars/himachal.yml` sets `hive_ops_enabled: false`. On 2026-10-27, read-only SSH to `james@himachal-1` found all seven timer units `not-found` and inactive. This observation is not a fleet-wide timer audit; a host-vars value alone does not establish a host's live state.

When disabled, cleanup is attempted only if `~/.config/systemd/user/hive-watchdog.timer` exists. The unit attempts to stop/disable the listed timers and remove their units and kubeconfig drop-ins, and removes the three helpers if cleanup succeeded. If the sentinel is absent, cleanup does not run; do not assume that it removed every possible leftover. Retired hosts and inventory VPSes are excluded even from cleanup. Existing kubeconfigs and cluster data are not removed. The role was not applied as part of the 2026-10-27 documentation update.

## Historical unit inventory

The checked-in unit files describe the old DeepSeek-era setup, not the current `omp` seed configuration on Spindle. Their schedules are:

| Timer | Checked-in schedule | Historical purpose |
|---|---|---|
| `hive-rotate` | 10 min after boot, then 20 min after activation | Rotate backends based on provider headroom |
| `hive-watchdog` | 3 min after boot, then every 5 min | Probe and heal agents |
| `hive-tiers` | Monday 04:30 UTC, up to 30 min random delay | Refresh model tiers |
| `hive-peak-pause` / `hive-peak-resume` | Weekdays 01:00 and 06:00 / 04:00 and 10:00 UTC | Pause/resume around DeepSeek peak windows |
| `pi-peak-stop` / `pi-peak-start` | Weekdays 01:00 and 06:00 / 04:00 and 10:00 UTC | Stop/start local `pi.service` around those windows |

When enabled, the unit installs `hive-peak.sh`, `hive-rotate.sh`, and `hive-tiers.sh` and writes service drop-ins for `KUBECONFIG` and `PATH`. The drop-ins made Kubernetes and Homebrew tools available to the systemd user manager; they do not make the legacy scripts suitable for the VPS.

## Variables retained by the unit

| Variable | Default | Historical purpose |
|---|---|---|
| `hive_ops_enabled` | `false` | Opt a host in; multiple operators could conflict |
| `hive_ops_kubeconfig` | `~/.kube/config-aws-migration` | AWS cluster credentials |
| `hive_ops_path` | Homebrew plus system paths | Find `kubectl` and `jq` in user services |
| `hive_ops_timers` | Seven timers above | Units deployed or cleaned up |
