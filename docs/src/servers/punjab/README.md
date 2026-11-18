# Punjab

Headless agent and development box, and the fleet's Ansible host. Since
2026-10-27 it is a **KubeVirt VM on [karnataka](../karnataka.md)**. The EC2
instance it replaced (tailnet node `punjab-aws-retired`, `100.78.73.8`) was last seen on 2026-10-28.
See [EC2 history](#ec2-history-retired).

| | |
|---|---|
| Runs on | karnataka k3s, `corral-vms/punjab` (VM created 2026-10-27) |
| Resources | 12 cores, 24 Gi of RAM, 500 Gi root PVC (`punjab-root`, local-path on karnataka) |
| OS | Ubuntu 24.04 LTS |
| Tailnet | `punjab` / `100.103.187.46` |
| Access | `ssh ubuntu@punjab` (there is no `james` user). For the VM console, run `virtctl console -n corral-vms punjab` from a host that has karnataka's kubeconfig |

## Role

- Agent host: Claude Code, OMP and Codex sessions in tmux. Most git worktrees
  are in `~/dev`.
- `kubectl` against karnataka's k3s: `~/.kube/config`.
- Hive fork builds: `~/dev/hive-v6-port` (`tuna-os/hive`, deploy branches). The
  amd64 binary that bihar and karnataka run was built here. See [Hives hosting](../hives.md).
- `sccache.service` (user) is a shared compiler cache for cargo builds.
- The **Kiro Crew gateway is retired**: `kirocrew.service` is masked.

## Disk

On 2026-11-18 `/` was **96% full (19 GB free)**. `~/dev` used 156 GB. Delete
stale worktrees under `~/dev` and `~/tuna-wt` before you make the PVC larger.

## Dependencies

punjab is a VM on karnataka. When karnataka restarts or k3s restarts its VMs,
punjab also restarts, and the agent tmux sessions stop.

## Ansible notes (`host_vars/punjab.yml`)

- `skip_proxy: true`: there is no podman on stock Ubuntu, so there is no Caddy quadlet.
- Not a desktop: no GNOME, flatpak or browser roles.
- `syncthing` runs only if its brew binary exists.

## EC2 history (retired)

From 2026-08 to 2026-10, punjab was an EC2 `t3.large` in `us-east-1`, the
Ansible host of the TunaOS AWS account ([AWS account](../aws/README.md)). It had
SSM break-glass access, daily DLM snapshots and Kiro Crew. It is described in
[`aws/punjab.tf`](https://github.com/hanthor/dotfiles/blob/master/aws/punjab.tf).
Its tailnet node is now `punjab-aws-retired`. Before you delete the instance and
its snapshots, confirm that the VM has all the data.
