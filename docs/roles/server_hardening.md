# server_hardening

**Tags:** `system`, `hardening`, `security`  
**Secrets needed:** No  
**Runs on:** Servers and VPS only (`is_desktop: false`)

Applies security and reliability hardening for long-running server hosts.

## What It Does

- Hardens SSH configuration (disable password auth, restrict ciphers)
- Configures automatic security updates
- Sets kernel hardening parameters via sysctl
- Configures log rotation and journald limits
- Installs and configures fail2ban for SSH brute-force protection

## Notes

- Skips desktops — keyboard-interactive machines have different security needs
- Designed for unattended servers that may run for months between reboots
