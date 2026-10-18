# systemd_hive_services

**Tags:** `services`, `systemd`, `systemd_hive_services`<br>
**Secrets needed:** No<br>
**Runs on:** All machines; service tasks target `himachal`

Owns systemd user units that orchestrate fleet-specific work rather than the
common systemd services installed on every host.

## Services Deployed

### system-mitigator (`himachal` only)

Deploys and enables the Lenovo EC and journald health monitor. The daemon:

- Detects CPU cores stuck at their minimum frequency
- Watches for `systemd-journald` restart loops
- Sends desktop notifications when either condition needs attention

### phone-apply timer (`himachal` only)

Deploys a two-hourly timer that pulls the dotfiles checkout and applies the
no-secrets playbook to `termux` and `mumbai`. Those hosts are often asleep or
off the tailnet, so each remote apply is allowed to fail without failing the
local timer service.

## Relationship to `systemd`

The `systemd` role owns generic user services, the conditional Podman socket,
and automatic dotfiles updates. Both roles use the `systemd` tag and the
`skip_systemd` flag, so existing tagged and skipped applies keep the same
selection semantics while the fleet-specific units have an independent role
boundary.
