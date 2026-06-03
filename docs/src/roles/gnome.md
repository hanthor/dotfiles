# gnome

**Tags:** `desktop`, `gnome`  
**Secrets needed:** No  
**Runs on:** Desktop group only

Configures GNOME desktop environment: keybindings, terminal, avatar, extensions, and remote desktop.

## What It Does

### Keybindings

Deploys custom keyboard shortcuts via dconf:
- Custom keybindings for terminal, browser, file manager
- Workspace navigation and window management shortcuts

### Ptyxis Terminal

Sets the default Ptyxis profile to use `fish` from Homebrew with JetBrains Mono Nerd Font at 12pt.

### User Avatar

- Downloads avatar from `https://reilly.asia/profile.png`
- Installs to both AccountsService and GDM cache
- Shows on login screen and user menu

### GNOME Extensions

Deploys and enables extensions from `group_vars/all.yml`:

| Extension | Purpose |
|-----------|---------|
| Caffeine | Disable screen blanking |
| AppIndicator | System tray icons |
| Blur My Shell | Blur effects |
| Dash to Dock | macOS-style dock |
| GSConnect | Phone integration |
| PaperWM | Tiling window manager |
| PaperShell | PaperWM companion |
| Search Light | Spotlight-style search |

### Remote Desktop

Enables GNOME Remote Desktop (RDP) via `grdctl` and starts the systemd user service.

## Extension Sync

Extensions are synced omnidirectionally — the `gnome_enabled_extensions` list in `group_vars/all.yml` is the canonical list. To update it from a running desktop:

```bash
gsettings get org.gnome.shell enabled-extensions
```
