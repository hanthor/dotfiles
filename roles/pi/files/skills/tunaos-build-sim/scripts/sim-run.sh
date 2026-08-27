#!/usr/bin/env bash
# sim-run — run a tunaos build script inside a disposable container with the
# repo mounted at /run/context (the exact mount the Containerfiles use), so
# scripts that source /run/context/build_scripts/lib.sh actually work.
#
# Usage:
#   sim-run <repo-root> <script-path> [--base distro|--image OCI_REF] [ENV=val ...]
#
# Distros (--base): arch el10 ubuntu debian opensuse gentoo
#   Each sets the container image + BASE_IMAGE + a default IMAGE_NAME:
#     arch     docker.io/archlinux/archlinux:latest            -> marlin
#     el10     quay.io/centos-bootc/centos-bootc:stream10      -> skipjack
#     ubuntu   docker.io/library/ubuntu:resolute               -> grouper
#     debian   docker.io/library/debian:trixie                 -> flounder
#     opensuse registry.opensuse.org/opensuse/tumbleweed:latest -> sailfin
#     gentoo   docker.io/gentoo/stage3:latest                  -> guppy
#   --image overrides the container image without touching BASE_IMAGE, for
#   base-image combinations the preset doesn't cover.
#
# Examples:
#   sim-run /home/james/dev/tuna-os/tunaos build_scripts/90-image-info.sh
#   sim-run /home/james/dev/tuna-os/tunaos build_scripts/40-services.sh --base ubuntu DESKTOP_FLAVOR=kde ENABLE_SSHD=0
#   sim-run /home/james/dev/tuna-os/tunaos build_scripts/checks/verify-branding.sh
#
# TMPDIR is pointed at a real disk because /var/tmp on this host is a tiny
# tmpfs (podman image pulls fail with "no space left on device").
set -euo pipefail

REPO="${1:?usage: sim-run <repo-root> <script> [--base d|--image ref] [ENV=val ...]}"
SCRIPT="${2:?usage: sim-run <repo-root> <script> [--base d|--image ref] [ENV=val ...]}"
shift 2 || true

TMPDIR="${SIM_RUN_TMPDIR:-/home/james/tmp-podman}"
BASE=arch
IMAGE_OVERRIDE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE="${2:?--base needs a value}"; shift 2 ;;
    --image) IMAGE_OVERRIDE="${2:?--image needs a value}"; shift 2 ;;
    *) break ;;
  esac
done

declare -A PRESETS=(
  [arch]="docker.io/archlinux/archlinux:latest|docker.io/archlinux/archlinux:latest|marlin"
  [el10]="quay.io/centos-bootc/centos-bootc:stream10|quay.io/almalinuxorg/almalinux-bootc:10|skipjack"
  [ubuntu]="docker.io/library/ubuntu:resolute|docker.io/library/ubuntu:resolute|grouper"
  [debian]="docker.io/library/debian:trixie|docker.io/library/debian:trixie|flounder"
  [opensuse]="registry.opensuse.org/opensuse/tumbleweed:latest|registry.opensuse.org/opensuse/tumbleweed:latest|sailfin"
  [gentoo]="docker.io/gentoo/stage3:latest|docker.io/gentoo/stage3:latest|guppy"
)
[[ -n "${PRESETS[$BASE]:-}" ]] || { echo "ERROR: unknown --base '$BASE' (arch el10 ubuntu debian opensuse gentoo)" >&2; exit 1; }
IFS='|' read -r CT_IMAGE BASE_IMAGE IMG_NAME <<< "${PRESETS[$BASE]}"
CT_IMAGE="${IMAGE_OVERRIDE:-$CT_IMAGE}"

[[ -f "$REPO/$SCRIPT" ]] || { echo "ERROR: $REPO/$SCRIPT not found" >&2; exit 1; }
mkdir -p "$TMPDIR"

declare -A ENV=(
  [BASE_IMAGE]="$BASE_IMAGE"
  [IMAGE_NAME]="$IMG_NAME"
  [IMAGE_VENDOR]=tuna-os
  [IMAGE_REGISTRY]=ghcr.io
  [IMAGE_NAME_VARIANT]="$IMG_NAME"
  [DESKTOP_FLAVOR]=gnome
  [ENABLE_SSHD]=1
  [SHA_HEAD_SHORT]=simtest
)
for extra in "$@"; do
  key="${extra%%=*}"
  val="${extra#*=}"
  [[ -n "$key" ]] && ENV["$key"]="$val"
done

E_ARGS=()
for k in "${!ENV[@]}"; do
  E_ARGS+=(-e "$k=${ENV[$k]}")
done

echo "==> sim-run: base=$BASE image=$CT_IMAGE script=$SCRIPT" >&2
exec podman run --rm \
  -v "$REPO:/run/context:z" \
  -v "$TMPDIR:/scratch:z" \
  -e TMPDIR=/scratch \
  "${E_ARGS[@]}" \
  "$CT_IMAGE" \
  bash "/run/context/$SCRIPT"
