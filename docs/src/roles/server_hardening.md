# server_hardening

`units/server-hardening.sh` runs for inventory `server` or `vps` members, but explicitly skips retired `matrix` and `telengana`. It requires `yq`, Python, `findmnt`, and root or noninteractive `sudo -n`; it uses no vault secrets. `units/server-hardening-file.py` performs the managed line edits.

The unit sets journald's maximum size to 500 MiB, restarts journald on change and vacuums old journals. On writable roots it creates a 2 GiB `/swapfile` if absent, sets root ownership and mode 0600, formats and enables it if not active, and adds an fstab entry. On read-only roots it preserves existing active swap (including zram) without changing `/swapfile` or fstab; if no swap is active, it reports failure. Apply and check modes both report failures when root mount options or the required active-swap status cannot be inspected, and continue the other hardening steps.

It enables systemd-timesyncd only when present and chrony is not active. It sets SSH `MaxStartups`, `MaxSessions`, and `ClientAliveCountMax`, reloading SSH best-effort on change. It enables UFW logging only when UFW is already active, attempts Ubuntu Pro livepatch when its status indicates it is needed, and reports a pending reboot. It does not configure firewall rules or install fail2ban.
