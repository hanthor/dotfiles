# server_hardening

**Tags:** `system`, `hardening`, `security`  
**Secrets needed:** No  
**Runs on:** `server` and `vps` groups (`site.yml` gates on group membership)

Applies reliability and light security hardening for long-running server hosts.

## What It Does

- **journald:** sets `SystemMaxUse=500M` and vacuums journals to that size
- **swap:** creates a 2G `/swapfile` if missing, sets 0600, runs `mkswap` + `swapon` only when it isn't already active, adds it to `/etc/fstab`
- **NTP:** enables and starts `systemd-timesyncd`
- **SSH rate limits:** `MaxStartups 3:50:10`, `MaxSessions 10`, `ClientAliveCountMax 3` in `sshd_config` (reloads sshd)
- **UFW:** turns logging on if UFW is already active (doesn't enable UFW or add rules)
- **Livepatch:** runs `pro enable livepatch` if Ubuntu Pro is attached (best-effort)
- **Reboot check:** prints a warning if `/var/run/reboot-required` exists

## Notes

- Does **not** install fail2ban, change SSH auth/cipher settings, set sysctls, or configure automatic updates
- No `skip_` flag — to keep a host out, take it out of `server`/`vps`
- The retired VPSes (`matrix`, `telengana`) are still in `vps`; don't apply to them (see the cutover runbook) — this role reloads sshd and restarts journald
