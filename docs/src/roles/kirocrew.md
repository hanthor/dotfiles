# kirocrew

`units/kirocrew.sh` manages an existing [Kiro Crew](https://github.com/kirodotdev/KiroCrew) installation only when `kirocrew_enabled: true` is set in host variables. It skips retired `matrix` and `telengana`. If `~/.local/bin/kirocrew` or `/etc/systemd/system/kirocrew.service` is missing, it skips and prints upstream installation guidance; it does not install either.

With root or noninteractive `sudo -n`, it makes `/etc/kirocrew/kirocrew.env` root-owned mode 0600, then enables and starts the service only if those permissions succeeded. It checks listeners using `ss` and `units/kirocrew-sockets.py`, failing the unit if the check fails. The existing environment file contains credentials; this unit neither fetches nor rewrites them.
