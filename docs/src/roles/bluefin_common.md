# bluefin_common

**Tags:** `desktop`, `bluefin`  
**Secrets needed:** No  
**Runs on:** Desktop group only (skipped on Bluefin hosts unless `force_bluefin: true`)

Syncs [Bluefin](https://projectbluefin.io/) branding, fonts, wallpapers, and GNOME extensions from the Project Bluefin OCI image.

## What It Does

1. Pulls the `ghcr.io/projectbluefin/common:latest` container image
2. Extracts Bluefin gsettings/dconf overrides, backgrounds, icons, and logos
3. Installs branding assets to `~/.local/share/`
4. Fixes XML background paths to point to home directory
5. Applies dconf settings via a Python script
6. Installs Bluefin-standard fonts (Inter, JetBrains Mono)
7. Installs Bluefin-recommended GNOME extensions
8. Deploys a wallpaper rotation service and timer
9. Deploys the `tailvm` and `tailvm-go` utilities

## Fonts

- **[Inter](https://rsms.me/inter/)** — UI font (from [GitHub releases](https://github.com/rsms/inter))
- **[JetBrains Mono](https://www.jetbrains.com/lp/mono/)** — monospace font for terminals and editors

## Wallpaper Rotation

A systemd timer (`bluefin-wallpaper-rotate.timer`) cycles through Bluefin backgrounds daily. The Python script applies the wallpaper via D-Bus.

## TailVM

Deploys both a Python (`tailvm`) and Go (`tailvm-go`) utility for managing VMs reachable over Tailscale.

## Notes

- Skips by default on actual Bluefin hosts (they already have this)
- Set `force_bluefin: true` to apply on Bluefin (e.g., after an image reset)
- Set `skip_bluefin: true` in `host_vars` to skip entirely
