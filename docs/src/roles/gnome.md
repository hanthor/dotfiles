# gnome

**Unit:** `units/gnome.sh`  
**Tags:** `desktop`, `gnome`  
**Secrets needed:** No  
**Runs on:** desktops, except `skip_gnome: true` or `machine_profile: vm-test`.

The unit installs `units/gnome/gnome-keybindings.ini` in `~/.config/dconf` and loads it into the invoking user's live session. A pending marker retains a changed load request if the session is unavailable. It configures the default Ptyxis profile for Homebrew fish and `JetBrainsMono Nerd Font 12` on a best-effort basis, and downloads the account avatar for installation by `units/gnome-avatar.py`; the avatar step requires root or non-interactive sudo.

The unit copies the bundled Copyous, PaperShell and PaperWM extensions from `units/gnome/extensions/` to the user's extension directory, without deleting unrelated files. It best-effort loads `units/gnome/gnome-extensions-dconf.dump` and sets `gnome_enabled_extensions` from host variables or `group_vars/all.yml`. Setting the enabled list does not install every listed extension or guarantee compatibility or activation in the current GNOME Shell. The separate Bluefin unit also attempts extension installation.

RDP enablement and the GNOME Remote Desktop user service are best effort. Session operations require a reachable existing user D-Bus session; the unit avoids creating an ephemeral session over SSH. Enabling RDP does not establish credentials or verify a remote login.
