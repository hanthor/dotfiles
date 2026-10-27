# termux_packages

`units/termux-packages.sh` runs for inventory members of `termux_hosts`, using Termux's unprivileged `pkg` and npm rather than systemd or root. Defaults are in `units/termux-packages.conf`; `termux_pkgs`, `termux_npm_global`, and `termux_keepalive_period_ms` can be overridden in `group_vars/all.yml` and then `host_vars/<machine>.yml`. Reading overrides requires `yq`.

It retries `pkg update` three times, installs bootstrap and configured packages (falling back to individual installs after a failed batch), and installs configured npm globals. Optional mise installation is best effort. It installs `units/termux-start-sshd` as `~/.termux/boot/start-sshd`, starts sshd if absent, and schedules persisted job 1 if not already pending. Termux:Boot and Termux:API companion apps are separate prerequisites. No vault secrets are used.
