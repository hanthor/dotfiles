# syncthing

**Unit:** `units/syncthing.sh`  
**Tags:** `services`, `syncthing`  
**Secrets needed:** No  
**Runs on:** non-VPS hosts, except Termux, `matrix`, `telengana`, `skip_syncthing: true`, or `machine_profile: vm-test`.

The unit requires `yq` to determine VPS membership. If `/home/linuxbrew/.linuxbrew/bin/syncthing` exists, it installs `units/syncthing/syncthing.service` to `~/.config/systemd/user/`, reloads the user manager when the file changes, and enables and starts the service. It requires a working user systemd manager.

If the binary is absent, it disables and stops an existing user service, including one supplied by a system-wide user-unit directory; if neither service nor binary exists, it skips. It does not configure Syncthing devices or folders or remove their data.
