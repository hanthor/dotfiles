# Reference: Containerfile mounts, env, and script wiring

## How each Containerfile applies system_files (the branding layer)

| Containerfile | system_files mechanism | numbered scripts |
|---|---|---|
| `Containerfile.arch` | `COPY --from=context /files /` | runs NONE inline — must be added (90-image-info/40-services/99-cleanup were wired 2026-08-04) |
| `Containerfile.el10` | `00-copy-files.sh` (`cp /run/context/files/. /`) | 40-services.sh, 90-image-info.sh, 91-*, 99-cleanup.sh |
| `Containerfile.ubuntu` | `00-copy-files.sh` | 40-services.sh, 90-image-info.sh, 99-cleanup.sh |
| `Containerfile.opensuse` | `COPY --from=context /files /` | install-remora.sh + install-desktop.sh; runs no numbered scripts |
| `Containerfile.gentoo` | `COPY --from=context /files /` | install-desktop.sh |
| `Containerfile.debian` | `COPY --from=context /files /` | install-desktop.sh |
| `Containerfile.overlay` | builds FROM published base | install-desktop.sh (per-de) + 90-image-info.sh re-run |

## Context stage

Every Containerfile builds a `scratch`-based `context` stage:

```dockerfile
FROM scratch as context
COPY system_files /files
COPY --from=common /system_files/shared /files   # infra configs, NOT branding
COPY system_files_overrides /overrides
COPY build_scripts /build_scripts
COPY manifests /manifests
```

The desktop RUN steps mount it at `/run/context`:
`--mount=type=bind,from=context,source=/,target=/run/context`

## Env each base sets (that build scripts read)

`BASE_IMAGE`, `IMAGE_NAME`, `IMAGE_VENDOR`, `IMAGE_NAME_VARIANT`,
`IMAGE_REGISTRY`, `DESKTOP_FLAVOR`, `ENABLE_SSHD`, `SHA_HEAD_SHORT`,
`MAJOR_VERSION_NUMBER` (el10 only). `lib.sh` derives `PKG_MGR`, `IS_ARCH`,
`IS_UBUNTU`, etc. from `BASE_IMAGE` — so a sim must set `BASE_IMAGE` to a
distro-matching string (e.g. `docker.io/archlinux/archlinux:latest` →
`PKG_MGR=pacman`, `IS_ARCH=true`, `IMAGE_NAME=marlin`).

## Known script expectations

- `90-image-info.sh` — writes /usr/share/ublue-os/image-info.json + edits
  /usr/lib/os-release (LOGO, VARIANT, IMAGE_ID, IMAGE_VERSION, URLs, fish
  codename). Requires IMAGE_NAME/IMAGE_VENDOR/IMAGE_REGISTRY/DESKTOP_FLAVOR.
- `40-services.sh` — apt branch exits early; the "dnf" path also runs for
  pacman/zypper/emerge (its first `sed` on uupd.service is a no-op failure
  that does not kill it). Enables tunaos-live-ready + DM per DESKTOP_FLAVOR.
- `verify-branding.sh <variant>` — variant is the fish name (marlin), NOT the
  desktop flavor; reads /usr/share + os-release absolutely.
- `verify-branding-kde.sh` — expects `kde-profile/default/xdg/kdeglobals`
  (Aurora layout) with `LookAndFeelPackage=org.tunaos.desktop`; greeter check
  is stock-greeter-acceptable (Aurora practice).
- `verify-branding-niri.sh` — greetd config, `-C` referenced config,
  niri.desktop, a wallpaper daemon OR dms, tunaos wallpaper asset.
- `install-zirconium.sh` — curls zirconium-dev/zirconium main tarball, lays
  down mkosi.extra paths (needs network + curl).
