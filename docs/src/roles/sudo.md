# sudo

`units/sudo.sh` installs a passwordless sudo rule for the current user, unless `skip_sudo: true` is set in host variables. It needs root or noninteractive `sudo -n`; it does not use secrets.

It validates a staged rule with `visudo -cf` before atomically installing `/etc/sudoers.d/zz-<user>` as root-owned mode 0440. Only after successful validation and installation does it remove the older `<user>` and `99-<user>` rules. The unit validates the username before using it in a path.
