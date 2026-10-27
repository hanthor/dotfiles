# retired_services

`units/retired-services.sh` removes only the explicitly listed obsolete system and user unit files in `units/retired-services/defaults/main.yml`. It skips Termux, non-Linux or non-systemd hosts, all inventory VPSes, and retired `matrix`/`telengana`. It requires `yq`, Python and systemctl; system-scope cleanup additionally needs root or noninteractive `sudo -n`. User cleanup can still proceed when root access is unavailable.

For each listed file that exists, it stops the generated quadlet service (`.container`, `.volume`, `.network`, or `.pod`) or disables and stops a plain unit, then removes the file. A missing generated unit is acceptable; other stop errors preserve the file. It reloads each systemd scope after changes. User paths are relative to `~/.config/containers/systemd/`; system paths are absolute. `caddy.container` is not on the list.

Only unit files are removed: Podman volumes, images, configuration directories, and other user data remain untouched. Add a retired service to the canonical list when its deployed unit needs cleanup.
