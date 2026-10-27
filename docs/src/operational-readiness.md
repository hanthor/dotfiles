# Fleet Operational Readiness

**Status:** Planning guidance, not a validated recovery guarantee. The fleet uses native units and Git configuration with Bitwarden for runtime secrets. Eligible hosts run non-secret updates on a user timer or laptop login; availability and successful convergence are not guaranteed. The home Talos cluster is temporarily offline in storage, not decommissioned.

## Common operations

- **Add a machine:** follow [Onboarding](onboarding.md), using `just onboard <name> <type>` or `just add-machine <name> <type>`. Inspect unit output and run `just doctor` on the host. A `SKIPPED` or `PARTIAL` line can mean configuration remains incomplete.
- **Rotate credentials:** update the relevant Bitwarden item securely, then run an unlocked apply on affected hosts. Consult the corresponding unit's documentation for rotation safeguards; do not put credentials in git. The [runbook](runbook.md) covers SSH key rotation.
- **Retire a machine:** review dependencies, remove its inventory and tailnet registration when appropriate, and preserve any needed data and Bitwarden items. The `just purge <name>` recipe removes inventory and host variables, but does not delete vault items.
- **Recover an auto-update:** inspect `systemctl --user status dotfiles-update.timer` (or the laptop login service), and `journalctl --user -u dotfiles-update.service`. Review git status in `~/.local/share/dotfiles`, then run `just apply-nosecrets` when appropriate.

**Retired VPS safeguard:** `matrix` and `telengana` remain powered on for burn-in. Nothing on them may be restarted. Native units' shared library skips both; follow the [cutover runbook](../matrix-cutover-runbook.md), not generic retirement or recovery instructions, for those hosts.

## Failure and recovery considerations

- Vault unavailable: secret-dependent units may skip or report partial work; existing credentials are not necessarily refreshed. Retry an unlocked apply once access is restored.
- Git unavailable: `apply-nosecrets` tolerates pull failure and runs the existing checkout. Review its age before relying on it.
- Host unreachable: check connectivity and SSH. Do not treat an offline host as successfully updated.
- Suspected secret exposure: revoke or rotate the affected credentials and investigate; public git and client-side checks do not guarantee prevention of leaks.
- Cluster loss: use the appropriate [home](servers/talos-k8s/cluster.md) or [AWS](servers/aws-k8s/cluster.md) handbook and verified backups. Persistent data recovery and failover times are not guaranteed by fleet unit applies.

## Readiness checks

Review changes on an appropriate non-production host, keep secrets out of git, inspect unit-specific gates and backups, and use the checks described in [Contributing](../../CONTRIBUTING.md). `just check` requests native inspection, but its coverage and non-mutating behavior across platforms are subject to integration verification. Record actual recovery times in drills rather than assuming RTO/RPO targets have been met.
