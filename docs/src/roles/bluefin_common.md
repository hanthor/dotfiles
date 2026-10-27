# bluefin

**Unit:** `units/bluefin.sh`  
**Tags:** `desktop`, `bluefin`  
**Secrets needed:** No  
**Runs on:** desktops, except `skip_bluefin: true` or `machine_profile: vm-test`.

With a GNOME session, on non-Bluefin systems or when `force_bluefin: true`, the unit pulls the amd64 `ghcr.io/projectbluefin/common:latest` image with Podman, extracts available branding into `~/.local/share`, adjusts wallpaper XML paths and runs `units/bluefin/files/bluefin-sync.py`. Missing individual image assets are reported as partial. It installs Inter and JetBrains Mono fonts and attempts the Bluefin extension installer; extension installation is best effort, not a guarantee that every extension works in the running GNOME version.

On eligible desktops, including Bluefin itself, it deploys `units/bluefin/files/bluefin-wallpaper-rotate.py` and user systemd service/timer templates, enables the timer and runs a rotation. It downloads the current architecture's corral binary and verifies its SHA256 against the release checksum, removes retired tailvm executables and completions, and configures `/etc/sysctl.d/99-zram.conf` with `vm.swappiness = 150`. The sysctl step requires root or non-interactive sudo; wallpaper and GNOME actions need the invoking user's live D-Bus/systemd session. Bluefin hosts skip only the branding, fonts and extension steps unless forced, not the whole unit.
