# apk_packages

`units/apk-packages.sh` runs only when the shared library detects a musl loader. Package lists live in `units/apk-packages.conf`. It retries `apk update`, installs missing bootstrap and ordinary packages without upgrading installed ones, and installs Bitwarden CLI globally via npm. Bootstrap includes `just` from Alpine's community repository for fleet commands and update services; an initial installation of `just` is still needed to invoke those commands before the unit has run. If a batch install fails it retries packages individually so unrelated packages can still install; optional mise and cache refresh are best effort.

Atuin uses Alpine's `atuin-sync` package, which includes login and history synchronization. The plain `atuin` package is an offline-only client; having it installed does not satisfy the sync-capable package requirement.

During the Atuin recovery on Kerala, apk-tools 3.0.8 rejected the unit's existing
`--no-upgrade` option. The sync client was installed directly with native
`apk add atuin-sync`; the complete package unit was not claimed as validated
on that apk-tools version.

The unit attempts to enable Podman and its socket and adds the current user to the `podman` group; a new login may be needed. The shared unit library skips retired `matrix` and `telengana` before package or group changes; nothing on those hosts may be restarted. Privileged operations require root or noninteractive `sudo -n`; no vault secrets are needed.
