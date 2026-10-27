#!/usr/bin/bash
set -euo pipefail
# Hummingbird's dracut-live requires fuse, parted and ntfs-3g from signed Fedora.
# The repository stays disabled by default, and these tools never enter the payload.
dnf5 -y --enablerepo=fedora-storage --setopt=install_weak_deps=False \
    install dracut-live systemd-boot-unsigned
# These masks belong to live media only, never to the embedded server payload.
systemctl mask k3s@server.service k3s@agent.service
# The Utah base masks serial-getty; live media needs both consoles for installation.
systemctl unmask getty@tty1.service serial-getty@ttyS0.service
systemctl enable getty@tty1.service serial-getty@ttyS0.service
mkdir -p /var/roothome
kernel=$(basename /usr/lib/modules/*)
dracut --force --reproducible --no-hostonly --add dmsquash-live     --omit 'tpm2-tss pcsc'     --add-drivers 'squashfs overlay loop iso9660 sr_mod cdrom'     "/usr/lib/modules/$kernel/initramfs.img" "$kernel" 2>&1 | tee /tmp/dracut-installer.log
if grep -q 'dracut\[E\]: FAILED' /tmp/dracut-installer.log; then
    echo 'Live initramfs construction failed' >&2
    exit 1
fi
dnf5 clean all
rm -rf /var/cache/dnf /var/cache/libdnf5
rm -f /tmp/configure-installer.sh /tmp/dracut-installer.log
