# systemd

**Tags:** `services`, `systemd`  
**Secrets needed:** No  
**Runs on:** All machines

Deploys systemd user services and timers for background tasks.

## Services Deployed

### dotfiles-update

Keeps the dotfiles repo up to date automatically.

- **Desktops/servers:** Daily timer (`dotfiles-update.timer`)
- **Laptops:** Runs on login via `graphical-session.target` (no timer)

### phone-apply (himachal only)

Pushes non-secret Ansible configuration to `termux` and `mumbai`, then runs the non-secret units on each phone from a temporary archive of the controller's tracked revision. Each operation is attempted independently; an unreachable phone does not fail the service. SSH aliases for the two inventory hosts must be configured on himachal.

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
