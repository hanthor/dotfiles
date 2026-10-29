# syncthing

**Unit:** `units/syncthing.sh`  
**Tags:** `services`, `syncthing`  
**Secrets needed:** No  
**Runs on:** non-VPS hosts, except Termux, `matrix`, `telengana`, `skip_syncthing: true`, or `machine_profile: vm-test`. An unreadable host-variable file fails the unit rather than bypassing an opt-out.

The unit determines VPS membership from inventory with `yq` when available, or the repository's block-style inventory fallback on an unbootstrapped host. It fails closed if membership cannot be determined. If `/home/linuxbrew/.linuxbrew/bin/syncthing` exists, it installs `units/syncthing/syncthing.service` to `~/.config/systemd/user/`, reloads the user manager before enabling and starting the service, and retries the reload on subsequent applies if an earlier one failed. A destination symlink is replaced rather than followed, leaving its target untouched. It requires a working user systemd manager.

If the binary is absent, it disables and stops an existing user service, including one supplied by a system-wide user-unit directory; if neither service nor binary exists, it skips. It does not configure Syncthing devices or folders or remove their data.
