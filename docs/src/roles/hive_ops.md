# hive_ops

`units/hive-ops.sh` manages optional user timers for the [Hive](https://hub.tunaos.org) on the [AWS Talos cluster](../servers/aws-k8s/cluster.md). It requires `yq` and a working user systemd manager, and skips Termux, inventory VPSes, and retired `matrix`/`telengana`. It does not read the vault; the configured kubeconfig is sensitive and must already exist for the helpers to access the cluster.

With `hive_ops_enabled: true`, it installs three helpers from `units/hive-ops/bin/` and service/timer pairs from `units/hive-ops/systemd/`. The default list in `units/hive-ops/defaults.yml` includes rotation, watchdog, tiers, Hive peak pause/resume, and pi peak start/stop. A host may override `hive_ops_timers`, `hive_ops_kubeconfig` (default `~/.kube/config-aws-migration`) and `hive_ops_path`. A drop-in pins KUBECONFIG and PATH for each service. Only enable one controller so timers do not compete.

When disabled, cleanup is attempted only if `hive-watchdog.timer` exists: listed timers are disabled, their unit files and kubeconfig drop-ins removed, and the three helpers removed if cleanup succeeded. Retired hosts and VPSes are excluded even from cleanup. Existing kubeconfigs and cluster data are not removed.
