# Fleet Operational Readiness

**Status**: Planning phase  
**Updated**: October 2026  
**Horizon**: Pre-scaled operations

This document outlines operational procedures, failure modes, disaster recovery, and scaling strategy for the dotfiles fleet.

## Overview

The dotfiles fleet consists of 14+ machines across desktop, server, VPS, and test environments, managed by Ansible with centralized configuration in git and secrets in Bitwarden. Non-laptop machines apply changes from a daily systemd user timer (`dotfiles-update.timer`); laptops run `dotfiles-update.service` on login instead of a timer.

**RTO/RPO targets** (provisional):
- Desktop machines: RTO 4 hours (manual reimaging), RPO 1 day (daily sync)
- Server/cluster: RTO 2 hours (orchestrated failover), RPO 15 min (distributed state)

## Common Operations

### Add a New Machine

1. Register the machine and bootstrap it. `just add-machine <name> [desktop|server|vps]` adds the inventory entry and `host_vars/<name>.yml`, pushes them, then runs `bootstrap.sh` on the host over SSH. Use it when the host is already reachable by SSH.
2. For a fresh install that is not yet reachable, run `just onboard <name> [desktop|server|vps]` instead. It registers and pushes the machine, then prints the `bootstrap.sh` command to run on the new host.
3. On the new machine, run `just apply` to apply the full configuration, then `just doctor` to verify it is healthy.

**Expected time**: 20 minutes (automated bootstrap included)

### Rotate Bitwarden Credentials

1. Rotate the credentials in Bitwarden itself (master password or API key, as appropriate). No repository file stores the token.
2. On each machine, unlock with `bw unlock`; the `bitwarden` role resolves the session from `BW_SESSION`, then `/tmp/bw_session`, then an interactive unlock (see [Secrets with Bitwarden](bitwarden.md)).
3. Dry-run to confirm secrets resolve: `just check` (a local `--check --diff` run, no host argument).
4. Apply: `just apply` on a single machine, or `just apply-all` to apply to every online fleet machine.

**Frequency**: Quarterly or after security incident  
**Expected time**: 15 minutes

### Retire a Machine

1. Comment out entry in `inventory.yml`
2. Remove `host_vars/<name>.yml`
3. Remove from Tailscale admin console
4. Power down machine (do not destroy hardware yet for 30 days)

**Verification**: Machine no longer appears in `ansible-inventory`

### Recover from Failed Auto-Update

If a machine fails daily sync:

1. SSH to machine: `ssh <name>`
2. Check the update unit: `systemctl --user status dotfiles-update.timer` (laptops have no timer; check `dotfiles-update.service`)
3. Trigger manual apply: `just apply-nosecrets`
4. Check for git merge conflicts: `cd ~/.local/share/dotfiles && git status`
5. If conflicts exist, resolve manually in `host_vars/<name>.yml` then `git pull`

**Recovery time**: 5 minutes (usually just a git pull)

## Failure Modes

| Failure | Detection | Recovery |
|---------|-----------|----------|
| **Machine offline** | Ansible host unreachable | SSH to machine, check network; if unrecoverable, re-bootstrap |
| **Bitwarden down** | Secret resolution fails on apply | Retry on next scheduled update (daily timer, or next login on laptops); run `just apply` after `bw unlock` if urgent |
| **Git repository unavailable** | Clone/pull fails | Machine continues with cached config; retry on next scheduled update (DNS/network usually recovers in <10 min) |
| **SSH key compromised** | Detected by audit | Regenerate key, update `authorized_keys` on all machines, audit git signing keys |
| **Secrets leaked to git** | Pre-commit hook catches; never committed by design | N/A — design prevents this |
| **Cluster node failure** (Talos) | Kubernetes node status | Automated failover; if persistent, reimage node via `talosctl` |

## Disaster Recovery

### Total Machine Loss (Hardware Failure)

1. Identify replacement hardware or cloud instance
2. Create new `host_vars/<name>.yml` for the replacement
3. Run `just add-machine <replacement-name>` if the host is reachable over SSH, or `just onboard <replacement-name>` and then the printed `bootstrap.sh` command on fresh hardware (same logical name, new hardware)
4. Machine re-joins fleet with same Tailscale identity (rotated keys, same node ID)
5. Services resume from last synced state (1-day RPO for desktops, 15-min for servers)

**Time to recovery**: 30 minutes + application startup time

### Talos Cluster Node Loss

1. Mark node as drained: `kubectl drain <node>`
2. Reimage node: `talosctl reset <node>`
3. Rejoin cluster: `talosctl apply-config -n <node> --file controlplane.yaml`
4. Verify node rejoined: `kubectl get nodes`

**Time to recovery**: 10 minutes

### Total Cluster Loss

Not currently addressed. Clusters are rebuilt from infrastructure-as-code (Talos patches, deployments in git), but persistent volumes require separate backup.

**Action items**: Define backup strategy for etcd and persistent volumes (outside current scope).

## Scaling Strategy

### Machines < 20

Current model is sustainable. All machines apply daily; no coordination needed. Bitwarden unlocked once per administrator per day.

### Machines 20–50

Projected state: Cost/complexity still manageable.  
**Action items**:
- Distribute daily apply times to avoid thundering herd (the timer already adds a 30 minute randomized delay)
- Consider adding a batched apply recipe for staged rollouts (none exists today; `just apply-all` applies to every online host in parallel)
- Monitor Bitwarden API rate limits (currently unused)

### Machines > 50

Requires architectural change (not in current scope):
- Centralized state server (e.g., Vault instead of Bitwarden)
- Event-driven apply (git webhook → targeted machines)
- Observability layer (currently none)

## Testing and Validation

### Pre-Deployment Checklist

- [ ] Changes tested on `vm` machine first (VM group)
- [ ] No secrets in git: `git diff --cached | grep -i secret`
- [ ] Lint passes: `ansible-lint`
- [ ] All machines in `inventory.yml` have corresponding `host_vars`
- [ ] SSH keys present for all new machines

### Annual Disaster Recovery Drill

- [ ] Reimage one desktop machine from scratch
- [ ] Verify Talos cluster node can rejoin
- [ ] Measure actual RTO and compare against targets

## Known Limitations

1. **Single Bitwarden vault** — no redundancy. If vault is inaccessible, no new secrets can be resolved (existing cached credentials continue to work for ~24 hours).
2. **Centralized git control** — all machines pull from one repository. If repo is unavailable, machines continue with cached config until next sync succeeds.
3. **No cross-region** — all machines are on one Tailscale network and in same cloud regions. No active-active failover.
4. **Test fleet not automated** — `test_fleet` machines are manual-apply only, not on auto-update timer.

## Next Steps

1. **Validate RTO/RPO** — run annual drill and measure actual times
2. **Document cluster recovery** — add procedures for Talos/Kubernetes emergencies
3. **Backup strategy** — design and test etcd/persistent volume backups
4. **Scaling model** — decide on 20–50 machine architecture before reaching that scale
