# termux_packages

**Tags:** `system`, `packages`, `termux`  
**Secrets needed:** No  
**Runs on:** `termux_hosts` group only (the raw Termux/Android layer on the phone)

Package and sshd management for Termux, which has no root, no systemd, no Homebrew and bionic libc.

## What It Does

1. `pkg update -y` (retried 3×), then `pkg install -y` the `termux_pkgs` list
2. `npm install -g` the `termux_npm_global` list (the pi coding agent)
3. Deploys `~/.termux/boot/start-sshd` (`termux-wake-lock` + `sshd`) for Termux:Boot
4. Starts `sshd` if it isn't running
5. Schedules the same script as a persisted periodic job via
   `termux-job-scheduler` (job id 1), so sshd comes back after Android kills Termux

## Configuration

`roles/termux_packages/defaults/main.yml`:

- `termux_pkgs` — openssh, git, python, nodejs, fish, vim, nano, termux-api, curl, unzip, plus `file` and `e2fsprogs` (Ansible's stat/copy modules need them)
- `termux_npm_global` — `@earendil-works/pi-coding-agent`
- `termux_keepalive_period_ms` — `1800000` (30 min; Android's floor is 15)

## Notes

- Requires the Termux:Boot and Termux:API companion apps, installed separately (F-Droid/GitHub)
- Claude Code, Codex etc. ship no android-arm64 binary — they live on the `mumbai` phone VM instead
- Connection quirks (remote tmp, scp, bash as shell executable) are pinned in `host_vars/termux.yml`
