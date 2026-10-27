# server_hardening

`units/server-hardening.sh` runs for inventory `server` or `vps` members, but explicitly skips retired `matrix` and `telengana`. It requires `yq`, Python, and root or noninteractive `sudo -n`; it uses no vault secrets. `units/server-hardening-file.py` performs the managed line edits.

The unit sets journald's maximum size to 500 MiB, restarts journald on change and vacuums old journals. It creates a 2 GiB `/swapfile` if absent, sets root ownership and mode 0600, formats and enables it if not active, and adds an fstab entry. It enables systemd-timesyncd only when present and chrony is not active. It sets SSH `MaxStartups`, `MaxSessions`, and `ClientAliveCountMax`, reloading SSH best-effort on change. It enables UFW logging only when UFW is already active, attempts Ubuntu Pro livepatch when its status indicates it is needed, and reports a pending reboot. It does not configure firewall rules or install fail2ban.
