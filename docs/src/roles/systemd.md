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

### atuin-daemon

Keeps [Atuin](https://atuin.sh/) shell history synced in the background.

### Podman socket (conditional)

If podman is installed:
- Creates the `podman` group
- Adds the user to the group
- Configures the podman socket for group access (mode 0660)
- Enables and starts `podman.socket`

The host-specific fleet services run in `systemd_hive_services`, keeping
machine-specific monitoring and phone orchestration separate from the generic
systemd user services and conditional Podman socket setup.

## Notes

- The `dotfiles-update.timer` on laptops is removed during the laptop-specific path
- All services run as user-level systemd units (no root needed)
