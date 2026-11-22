# systemd

**Tags:** `services`, `systemd`  
**Secrets needed:** Optional (`ntfy-topic`, for failure alerts)  
**Runs on:** All machines

Deploys systemd user services and timers for background tasks.

## Services Deployed

### dotfiles-update

Keeps the dotfiles repo up to date automatically.

- **Desktops/servers:** Daily timer (`dotfiles-update.timer`)
- **Laptops:** Runs on login via `graphical-session.target` (no timer)

The service runs `just apply-nosecrets`. That recipe runs `git pull --ff-only`
and then applies the current checkout even if the pull failed. A failed pull
is not hidden: the recipe records it in `~/.cache/dotfiles/last-apply.json`
(label `apply-nosecrets+pull-failed`, field `pull_exit_code`) and exits
non-zero. `just doctor` then reports it and the unit's failure notifier fires.

**Nightly package upgrade.** On the daily timer (non-laptops),
`dotfiles_update_upgrade: true` (the default) adds `brew update` before the
apply and `-e upgrade=true` to it. With that variable set, the homebrew role
runs `brew upgrade` and the flatpak role runs `flatpak update --system`. The
flatpak update needs passwordless sudo; without it the task fails and the
apply ignores the failure. The laptop login run never upgrades. To opt a host
out, set `dotfiles_update_upgrade: false` in its `host_vars`. `just update-all`
is the manual equivalent.

### notify-failure@ (failure alerts)

Every unit this role deploys (`dotfiles-update`, `atuin-daemon`,
`phone-apply`, `system-mitigator`, `disk-usage-check`) has
`OnFailure=notify-failure@%n.service`. The template unit runs
`~/.local/bin/notify-failure <unit>`, which posts
`<host>: <unit> failed (result: …)` to ntfy. The message does not include
journal lines, because ntfy topics are guessable. To read the details, run
`journalctl --user -u <unit>`.

The topic comes from `~/.config/notify-failure.env` (mode 0600), which holds
`NTFY_TOPIC` and `NTFY_SERVER`:

- The role writes this file only on an apply with an unlocked vault (not the
  nightly `--skip-tags secrets` run). It takes the topic from the
  **password** field of the Bitwarden Login item `ntfy-topic`
  (`notify_failure_bw_item`). The server is `notify_failure_ntfy_server`
  (default `https://ntfy.sh`).
- If the item is missing or empty, an existing file is left as it is.
- If there is no file, the notifier writes the failure to the journal and
  exits 0. It also exits 0 when the post fails, so the notifier never becomes a
  second failed unit.

To test the notifier, run `systemctl --user start notify-failure@test.service`.

### disk-usage-check

A timer that runs every 6 hours. It runs
`~/.local/bin/disk-usage-check.py <threshold> <paths>`, which exits 1 when a
filesystem in `disk_check_paths` (default `/`, `/var`, `/home`) is more than
`disk_check_threshold` percent full (default 90). Exit 1 triggers
notify-failure. Read-only mounts are skipped (on bootc hosts the composefs
root always reads 100%), and so is a second path on a filesystem that was
already checked. To remove the timer, set `disk_check_enabled: false`.

### atuin-daemon

Keeps [Atuin](https://atuin.sh/) shell history synced in the background.

### Podman socket (conditional)

If podman is installed:
- Creates the `podman` group
- Adds the user to the group
- Configures the podman socket for group access (mode 0660)
- Enables and starts `podman.socket`

### system-mitigator (himachal only)

A Python daemon that monitors for Lenovo EC firmware bugs:
- Detects false `BD_PROCHOT` signals that lock CPU cores to 400 MHz
- Watches for `systemd-journald` watchdog loops
- Sends desktop notifications when issues are detected

## Notes

- The `dotfiles-update.timer` on laptops is removed during the laptop-specific path
- All services run as user-level systemd units (no root needed)

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `dotfiles_update_upgrade` | `true` | Nightly run upgrades brew + flatpak packages |
| `notify_failure_bw_item` | `ntfy-topic` | Bitwarden Login item whose password is the ntfy topic |
| `notify_failure_ntfy_server` | `https://ntfy.sh` | ntfy server |
| `disk_check_enabled` | `true` | Deploy the disk-usage-check timer |
| `disk_check_threshold` | `90` | Alert above this percent used |
| `disk_check_paths` | `/`, `/var`, `/home` | Filesystems to check |
