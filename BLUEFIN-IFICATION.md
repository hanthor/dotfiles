# Bluefin-ification Guide 🚀

The `bluefin_common` role provides a dynamic way to bring the **Project Bluefin** experience to any standard GNOME desktop environment. Instead of hardcoding settings, it pulls the latest customizations directly from the official Bluefin OCI images.

## Features
- **Dynamic Settings Sync:** Pulls `gschema` overrides and `dconf` settings directly from `ghcr.io/projectbluefin/common`.
- **Automatic Extension Management:** Downloads and installs the Bluefin-standard GNOME extensions (Dash to Dock, Blur my Shell, AppIndicator, etc.) from the GNOME Extensions API.
- **Full Branding & Artwork:** Deploys Bluefin backgrounds and logos to your local user directories.
- **Smart Path Mapping:** Automatically rewrites background XML paths to work in your home directory without root access.

## Usage in this Playbook
The role is included by default for all desktop systems. To apply it to a specific machine (e.g., `kerala`):
```bash
just apply-remote kerala
```

To force a re-sync on a system that is already running a native Bluefin image:
```bash
ansible-playbook site.yml --tags bluefin -e force_bluefin=true
```

## Standalone Usage
Other people can use this role independently of this dotfiles repository by copying the `roles/bluefin_common` directory.

### Prerequisites
- **Ansible** installed.
- **Podman** installed (used to pull the OCI image).
- **Python 3** on the target machine.
- **GNOME Desktop** environment.

### Integration
Add the role to your own playbook:
```yaml
- hosts: localhost
  roles:
    - role: bluefin_common
      vars:
        is_desktop: true
```

## How it Works
1. **Detection:** It identifies if you are running GNOME and if the system is already a Bluefin image (via `/etc/os-release`).
2. **OCI Extraction:** It pulls the `amd64` variant of the `projectbluefin/common` image and extracts configuration files and branding assets.
3. **Python Application:** A custom script (`bluefin-sync.py`) parses the extracted `gschema` and `dconf` files and applies them using `gsettings` and `dconf load`.
4. **Extension Installer:** The `install-extensions.py` script queries the GNOME Extensions API, finds the best version for your shell, and installs it to `~/.local/share/gnome-shell/extensions`.
