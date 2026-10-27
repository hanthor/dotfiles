# apk_packages

`units/apk-packages.sh` runs only when the shared library detects a musl loader. Package lists live in `units/apk-packages.conf`. It retries `apk update`, installs missing bootstrap and ordinary packages without upgrading installed ones, and installs Bitwarden CLI globally via npm. If a batch install fails it retries packages individually so unrelated packages can still install; optional mise and cache refresh are best effort.

The unit attempts to enable Podman and its socket and adds the current user to the `podman` group; a new login may be needed. The shared unit library skips retired `matrix` and `telengana` before package or group changes; nothing on those hosts may be restarted. Privileged operations require root or noninteractive `sudo -n`; no vault secrets are needed.
