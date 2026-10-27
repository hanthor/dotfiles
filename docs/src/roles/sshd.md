# sshd

`units/sshd.sh` skips hosts without `/etc/ssh/sshd_config.d`. Otherwise it installs `99-bw-env.conf` with `AcceptEnv BW_SESSION BW_CLIENTID BW_CLIENTSECRET` as a best-effort step. If `sshd_harden: true` is set in host variables, it also validates and installs `10-hardening.conf`: root login, password and keyboard-interactive authentication, and X11 forwarding are disabled; authentication attempts and login grace time are limited.

Files are staged and installed root-owned (0644); root or noninteractive `sudo -n` is required. After a change the unit attempts to reload `ssh` on Debian/Ubuntu and `sshd` elsewhere. The shared unit library skips retired `matrix` and `telengana` before changes; nothing on those hosts may be restarted. No vault access is required.
