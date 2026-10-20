#!/usr/bin/env bash
# Called inside podman unshare; follows Utah's dracut/squashfs UEFI media layout.
set -euo pipefail
image=$1
output=$2
node=$3
work=$4
utah_src=$5
mount=$(podman image mount "$image")
trap 'podman image unmount "$image" >/dev/null' EXIT
kernel=$(basename "$mount"/usr/lib/modules/*)
vmlinuz=$(python3 "$utah_src/iso/scripts/live-kernel.py" "$mount" "$kernel")
initrd="$mount/usr/lib/modules/$kernel/initramfs.img"
efi="$mount/usr/lib/systemd/boot/efi/systemd-bootx64.efi"
test -f "$initrd"
test -f "$efi"
mkdir -p "$work/live-root" "$work/iso-root/EFI/BOOT" "$work/iso-root/LiveOS" "$work/iso-root/images/pxeboot"
cp -a "$mount/." "$work/live-root/"
mksquashfs "$work/live-root" "$work/iso-root/LiveOS/squashfs.img" \
    -noappend -comp zstd -Xcompression-level 3 -b 131072 -processors 4 \
    -wildcards -e 'proc/*' 'sys/*' 'dev/*' run tmp
esp="$work/iso-root/EFI/efi.img"
# Include enough space for both boot files plus FAT overhead.
esp_mb=$(( $(stat -c %s "$initrd") / 1048576 + $(stat -c %s "$vmlinuz") / 1048576 + 64 ))
truncate -s "${esp_mb}M" "$esp"
mkfs.fat -F 32 -n ESP "$esp" >/dev/null
export MTOOLS_SKIP_CHECK=1
mmd -i "$esp" ::/EFI ::/EFI/BOOT ::/loader ::/loader/entries ::/images ::/images/pxeboot
mcopy -i "$esp" "$efi" ::/EFI/BOOT/BOOTX64.EFI
mcopy -i "$esp" "$vmlinuz" ::/images/pxeboot/vmlinuz
mcopy -i "$esp" "$initrd" ::/images/pxeboot/initrd.img
# As in Utah, rootless squashfs assembly cannot retain SELinux labels. Only
# LIVE media is permissive; the separate, unmodified payload keeps enforcement.
cat > "$work/home-k8s.conf" <<EOF
title Home Kubernetes installer: $node (bootc-installer-tui)
linux /images/pxeboot/vmlinuz
initrd /images/pxeboot/initrd.img
options root=live:LABEL=HOME_K8S_LIVE rd.live.image rd.live.overlay.overlayfs=1 enforcing=0 console=tty0 console=ttyS0,115200n8
EOF
printf 'timeout 3\ndefault home-k8s.conf\n' > "$work/loader.conf"
mcopy -i "$esp" "$work/home-k8s.conf" ::/loader/entries/home-k8s.conf
mcopy -i "$esp" "$work/loader.conf" ::/loader/loader.conf
cp "$efi" "$work/iso-root/EFI/BOOT/BOOTX64.EFI"
cp "$vmlinuz" "$work/iso-root/images/pxeboot/vmlinuz"
cp "$initrd" "$work/iso-root/images/pxeboot/initrd.img"
xorriso -as mkisofs -iso-level 3 -r -J --joliet-long -V HOME_K8S_LIVE \
    --efi-boot EFI/efi.img -efi-boot-part --efi-boot-image \
    -o "$output" "$work/iso-root"
