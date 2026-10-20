#!/usr/bin/env bash
# Build per-node UEFI media around the real local Fisherman TUI and backend.
set -euo pipefail
node=${1:?expected bihar or karnataka}
target_ref=${2:?expected the canonical registry reference for installed-system updates}
output=${3:?expected an output ISO path}
tag=${4:-testing}
source_image="localhost/home-k8s-$node:$tag"
case "$node" in bihar|karnataka) ;; *) echo 'Expected bihar or karnataka' >&2; exit 2 ;; esac
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
fisherman_src=${FISHERMAN_SRC:-$HOME/dev/tuna-os/fisherman}
utah_src=${UTAH_SRC:-$HOME/dev/utah}
for cmd in podman go python3 mksquashfs mkfs.fat mmd mcopy xorriso; do
    command -v "$cmd" >/dev/null || { echo "Missing build tool: $cmd" >&2; exit 1; }
done
for file in "$fisherman_src/fisherman/go.mod" "$fisherman_src/tui/go.mod" "$utah_src/iso/scripts/live-kernel.py"; do
    test -f "$file" || { echo "Missing local source: $file" >&2; exit 1; }
done
mkdir -p -- "$(dirname -- "$output")"
output=$(realpath -- "$output")
work=$(mktemp -d /var/tmp/home-k8s-installer.XXXXXX)
cleanup() { podman unshare rm -rf -- "$work"; }
trap cleanup EXIT
cp -a "$here/installer/." "$work/"
CGO_ENABLED=0 go -C "$fisherman_src/fisherman" build -mod=readonly -trimpath -o "$work/fisherman" ./cmd/fisherman
CGO_ENABLED=0 go -C "$fisherman_src/tui" build -mod=readonly -trimpath -o "$work/bootc-installer-tui" ./cmd/bootc-installer-tui
{
    git -C "$fisherman_src" describe --always --dirty
    sha256sum "$work/fisherman" "$work/bootc-installer-tui"
} > "$work/source.txt"
# An OCI layout avoids mutable/offline containers-storage discovery entirely.
podman save --format oci-dir --output "$work/payload" "$source_image"
python3 - "$work" "$target_ref" <<'PY'
import json
from pathlib import Path
import sys
work = Path(sys.argv[1])
index = json.loads((work / 'payload/index.json').read_text())
manifest, = index['manifests']
contract = {
    'schemaVersion': 1,
    'kind': 'home-k8s-live',
    'image': 'oci:/usr/share/home-k8s/payload',
    'platformManifestDigest': manifest['digest'],
    'ociLayoutPath': '/usr/share/home-k8s/payload',
    'targetImgref': sys.argv[2],
    'platform': 'linux/amd64',
}
(work / 'media-input.json').write_text(json.dumps(contract, indent=2) + '\n')
PY
live_image="localhost/home-k8s-$node-installer:$tag"
podman build --build-arg "SOURCE_IMAGE=$source_image" \
    --tag "$live_image" --file "$work/Containerfile" "$work"
podman unshare bash "$here/assemble-installer.sh" "$live_image" "$output" "$node" "$work" "$utah_src"
printf 'Installer: %s\nCustom image URL: oci:/usr/share/home-k8s/payload\nHostname: %s\n' "$output" "$node"
printf 'UEFI only; Secure Boot must be disabled. Live media is SELinux permissive; installed nodes remain enforcing.\n'
