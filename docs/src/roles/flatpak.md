# flatpak

**Unit:** `units/flatpak.sh`  
**Tags:** `packages`, `desktop`, `flatpak`  
**Secrets needed:** No  
**Runs on:** desktops, except `skip_flatpak: true` or `machine_profile: vm-test`.

The unit requires Flatpak and `yq`. It reads system remotes and `system_flatpaks` from `units/flatpak-packages.yml`, repairs a dangling `/var/lib/flatpak` symlink, adds remotes, removes system Firefox and Thunderbird Flatpaks, and installs missing applications from Flathub. A failed batch is retried individually. `DOTFILES_UPGRADE=1` or `true` requests a best-effort system update. System operations require root or non-interactive sudo.

Host-specific `user_flatpak_remotes` and `user_flatpaks` in `host_vars/<machine>.yml` are applied with `--user`, separately from the system store. For `himachal`, these configure FlatPark and user Flathub, then install `org.tunaos.blueshell`, `org.tunaos.tavern`, and `org.tunaos.compass` from FlatPark. An already installed user app with a different origin is preserved rather than switched. This installation does not configure or unlock Compass's keyring or establish an application login; those depend on the user's session and app setup.

The unit also writes `chromium`, `chromium-browser`, `google-chrome`, and `google-chrome-stable` wrappers in `~/.local/bin`, invoking `org.chromium.Chromium` via Flatpak. Wrappers are attempted even if Flatpak is unavailable.
