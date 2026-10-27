# homebrew

**Unit:** `units/homebrew.sh`  
**Tags:** `packages`, `homebrew`  
**Secrets needed:** No  
**Runs on:** glibc hosts; skips Termux and musl.

The native unit installs and manages Homebrew. It defaults to `/home/linuxbrew/.linuxbrew` (`BREW_PREFIX` overrides the prefix), bootstraps Mike Farah `yq`, and reads package lists from `group_vars/all.yml` and host configuration through `units/package-config.bash`. Package units validate the `yq` implementation and can select the Homebrew binary when an incompatible `yq` precedes it on `PATH`.

It generates `~/Brewfile` with core packages and, on desktops, desktop taps, packages, extras and casks; VS Code extensions are included on Darwin. It taps repositories, attempts to trust them, runs `brew bundle install --no-upgrade`, and uninstalls `brew_blocked` formulae. If Brewfile deployment fails, bundle is skipped rather than using a stale file, but independent steps continue. A blocked package in an install list is a configuration error. `DOTFILES_UPGRADE=1` or `true` additionally requests a best-effort `brew upgrade`; installing Python `packaging` is also best effort.

Ownership repair and installing a missing Debian/Ubuntu compiler toolchain may require root or non-interactive sudo. Other systems must supply a compiler if missing. The Homebrew installer itself is downloaded and run non-interactively.
