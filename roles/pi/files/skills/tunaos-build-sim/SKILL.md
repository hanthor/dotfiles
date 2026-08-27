---
name: tunaos-build-sim
description: Simulate the tunaOS container-build environment to test build scripts, branding checks, and Containerfile steps without a full multi-hour image build. Use when validating build_scripts/*.sh, verify-branding*.sh, verify-desktop-experience.sh, dconf/os-release/LOGO identity changes, or any Containerfile RUN step in tuna-os/tunaos — or when a CI LUKS/branding failure needs root-causing against the real script behavior.
---

# TunaOS build environment simulation

Run tunaOS `build_scripts/` and `checks/` scripts exactly as the Containerfiles
do — repo bind-mounted at `/run/context`, standard build env set — in a
disposable container for **any base distro**, and verify the outcome, without
building an image.

## Why this exists

Full variant builds take 30 min–6 h (kernel + dracut + desktop). Most build
scripts are plain bash that only need the context mount + a handful of env
vars. Testing them in a container gives a real answer in ~1 min. The LUKS and
branding failures we've debugged (dconf false positive, missing sudo /
fuse-overlayfs / cryptsetup, 90-image-info never running, LOGO unset) were all
reproducible this way before touching CI.

## Quick start — run a build script with the real context mount

```bash
sim-run /home/james/dev/tuna-os/tunaos build_scripts/90-image-info.sh
# another distro + env overrides:
sim-run /home/james/dev/tuna-os/tunaos build_scripts/40-services.sh --base ubuntu DESKTOP_FLAVOR=kde ENABLE_SSHD=0
# a check script (reads os-release via env; /usr/share needs the test-image pattern):
sim-run /home/james/dev/tuna-os/tunaos build_scripts/checks/verify-branding.sh
```

`sim-run` mounts the repo at `/run/context` (the Containerfile mount), sets
`BASE_IMAGE`, `IMAGE_NAME`, `IMAGE_VENDOR`, `IMAGE_REGISTRY`,
`IMAGE_NAME_VARIANT`, `DESKTOP_FLAVOR`, `ENABLE_SSHD`, `SHA_HEAD_SHORT`, and
points `TMPDIR` at a real disk (host `/var/tmp` is a tiny tmpfs).

### Distro presets (`--base`)

| base | container image | IMAGE_NAME |
|---|---|---|
| arch (default) | docker.io/archlinux/archlinux:latest | marlin |
| el10 | quay.io/centos-bootc/centos-bootc:stream10 | skipjack |
| ubuntu | docker.io/library/ubuntu:resolute | grouper |
| debian | docker.io/library/debian:trixie | flounder |
| opensuse | registry.opensuse.org/opensuse/tumbleweed:latest | sailfin |
| gentoo | docker.io/gentoo/stage3:latest | guppy |

`--image <ref>` swaps the container image without changing `BASE_IMAGE`
(use for base variants like almalinux vs centos, or distro combinations not
in the table). Override any env with trailing `KEY=val` args.

## Workflows

### Verify a script modifies the filesystem correctly
Scripts that edit image state (90-image-info.sh, 40-services.sh,
install-zirconium.sh, dconf update) mutate the disposable container's
filesystem. After running, append a verify command in the same container:

```bash
podman run --rm -v "$REPO:/run/context:z" docker.io/archlinux/archlinux:latest bash -c '
  export BASE_IMAGE=docker.io/archlinux/archlinux:latest IMAGE_NAME=marlin IMAGE_VENDOR=tuna-os \
         IMAGE_REGISTRY=ghcr.io IMAGE_NAME_VARIANT=marlin DESKTOP_FLAVOR=gnome ENABLE_SSHD=1 SHA_HEAD_SHORT=test
  bash /run/context/build_scripts/90-image-info.sh >/dev/null
  grep -E "LOGO|VARIANT|SUPPORT_URL" /usr/lib/os-release
  cat /usr/share/ublue-os/image-info.json
'
```

### Verify checks that read absolute /usr/share paths (branding)
`verify-branding*.sh` reads `/usr/share/...` and `/usr/lib/os-release`
directly — the bind-mount trick does NOT cover those. Build a test image that
copies your files into a base of the matching distro, then run the checks:

```bash
cat > /tmp/Dockerfile.brandtest <<'EOF'
FROM docker.io/archlinux/archlinux:latest      # or ubuntu:resolute etc.
COPY mockroot/usr/ /usr/
COPY mockroot/usr/lib/os-release /etc/os-release
RUN mkdir -p /usr/share/ublue-os && \
    printf '{"image-name": "marlin", "image-vendor": "tuna-os"}' > /usr/share/ublue-os/image-info.json
COPY tunaos/build_scripts/ /scripts/
EOF
podman build -t brandtest -f /tmp/Dockerfile.brandtest /tmp
podman run --rm brandtest bash -c '
  bash /scripts/checks/verify-branding.sh marlin; echo "rc=$?"
  bash /scripts/checks/verify-branding-kde.sh marlin
  bash /scripts/checks/verify-branding-niri.sh marlin
'
```

`mockroot/usr/` is a partial tree mirroring what your `system_files/` would
land (pixmaps, backgrounds, plasma look-and-feel, niri, kde-settings...).
Checks that fail due to missing *packages* (python3, greetd, swaybg,
niri.desktop) are mock artifacts, not asset bugs — check `command -v` first.

### Env-var overrides the scripts honor
- `TUNAOS_OS_RELEASE=/path` — verify-branding.sh reads a specific os-release
  file instead of /etc:/usr/lib (useful with a mockroot).
- `SIM_RUN_IMAGE`, `SIM_RUN_TMPDIR` — sim-run overrides.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `podman pull` / build fails "no space left on device" | host `/var/tmp` tmpfs is tiny; set `SIM_RUN_TMPDIR`/`TMPDIR` to a real disk (default in sim-run) |
| `lib.sh: No such file or directory` | script sources `/run/context/build_scripts/lib.sh` — the repo must be mounted at `/run/context`, not a random path |
| check reports everything missing | checks read absolute `/usr/share` — use the Dockerfile/test-image pattern, not the bind mount |
| `image-name is ''` / LOGO unset in mock | `python3` absent in the mock Arch container (real bases have it) — `command -v python3` first |
| KDE `LookAndFeelPackage` check fails | verifier greps `kde-profile/default/xdg/kdeglobals` (Aurora layout) — file must be there, not `etc/xdg/` |
| script expects dnf/apt tools on the sim base | sim bases are minimal; scripts using `pkg_install` need the matching distro image (presets pick it) |

## Cleanup

```bash
podman rmi -f brandtest 2>/dev/null  # or whatever test images you built
podman rm -f <inspector containers>
rm -rf /tmp/mockroot /tmp/tunaos /tmp/Dockerfile.brandtest /home/james/tmp-podman/*.tar
```

## See also
- [REFERENCE.md](REFERENCE.md) — Containerfile mount table, per-base env, and
  what each build script expects.
