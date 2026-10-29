# sudo

`units/sudo.sh` installs a passwordless sudo rule for the current user, unless `skip_sudo: true` is set in host variables. If a host-variable file exists but cannot be read, it fails rather than ignoring an opt-out. It needs root or noninteractive `sudo -n`; it does not use secrets.

It validates a staged rule with `visudo -cf` before atomically installing `/etc/sudoers.d/zz-<user>` as root-owned mode 0440. Existing policy is inspected with root privileges, so a private sudoers directory or file does not cause a needless rewrite. An inspection failure preserves the current and legacy rules. Only after successful validation and installation does it remove the older `<user>` and `99-<user>` rules. The unit validates the username before using it in a path.
