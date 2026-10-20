#!/usr/bin/bash
set -euo pipefail

# Hummingbird remains preferred. Fedora is used only for storage utilities the
# Hummingbird/factory repositories do not provide; never upgrade the base kernel.
dnf5 -y --enable-repo=utah-packages --enable-repo=fedora-storage \
    --setopt=install_weak_deps=False --exclude='kernel*' install \
    linux-firmware amd-gpu-firmware intel-gpu-firmware \
    amd-ucode-firmware microcode_ctl \
    iwlwifi-dvm-firmware iwlwifi-mvm-firmware \
    realtek-firmware mt7xxx-firmware atheros-firmware brcmfmac-firmware \
    NetworkManager-wifi wpa_supplicant tailscale iptables-nft \
    iscsi-initiator-utils nfs-client-utils policycoreutils-python-utils

curl --fail --location \
    "https://github.com/k3s-io/k3s/releases/download/${K3S_VERSION}/k3s" -o /usr/bin/k3s
printf '%s  /usr/bin/k3s\n' "$K3S_SHA256" | sha256sum --check --strict
chmod 0755 /usr/bin/k3s
curl --fail --location \
    "https://github.com/k3s-io/k3s-selinux/releases/download/${K3S_SELINUX_VERSION}/k3s-selinux-1.6-1.coreos.noarch.rpm" \
    -o /tmp/k3s-selinux.rpm
printf '%s  /tmp/k3s-selinux.rpm\n' "$K3S_SELINUX_SHA256" | sha256sum --check --strict
# The SHA256 above authenticates this exact release RPM independently of rpm's
# keyring. Do not disable GPG verification for repository packages.
dnf5 -y --setopt=localpkg_gpgcheck=False install /tmp/k3s-selinux.rpm
# Its RPM scriptlet ignores errors; policy compilation must fail the build.
semodule -n -X 200 -i /usr/share/selinux/packages/k3s.pp
# Home workload volume paths are outside K3s's default SELinux mapping.
# Hummingbird's policy maps /var/mnt to /mnt before matching file contexts.
semanage fcontext -a -t container_file_t '/mnt/storage(/.*)?'
semanage fcontext -a -t container_file_t '/var/lib/lemonade-cache(/.*)?'
semanage fcontext -a -t container_file_t '/var/lib/lemonade-models(/.*)?'
# Device cgroups still restrict access to devices assigned by Kubernetes.
setsebool -P container_use_devices on

/usr/bin/k3s --version
firewall-offline-cmd --check-config
systemctl enable NetworkManager.service NetworkManager-wait-online.service sshd.service firewalld.service tailscaled.service iscsi-init.service iscsid.service
# Reboots of the only control plane must be deliberate and preceded by backups.
systemctl mask bootc-fetch-apply-updates.timer bootc-fetch-apply-updates.service

kernel=$(basename /usr/lib/modules/*)
for module in overlay br_netfilter vxlan iscsi_tcp nfs \
    amdgpu i915 xe kvm_intel kvm_amd vhost_net tun \
    iwlwifi mt7925e mt7921e rtw89_8852be rtw89_8922ae r8169 \
    ath9k ath10k_pci ath11k_pci ath12k brcmfmac; do
    modinfo -k "$kernel" "$module" >/dev/null
done
# Firmware subpackages are weak dependencies; verify the explicitly selected
# hardware families rather than relying on linux-firmware's meta-package.
python3 - <<'PY'
from pathlib import Path

root = Path("/usr/lib/firmware")
families = {
    "Strix Halo graphics": ("amdgpu/gc_11_5_1*",),
    "Intel Raptor Lake graphics": ("i915/adlp*", "i915/tgl*"),
    "Intel Xe graphics": ("xe/**/*",),
    "Intel Wi-Fi": ("iwlwifi-*.ucode*", "intel/iwlwifi/*.ucode*"),
    "MediaTek MT7925 Wi-Fi": ("mediatek/mt7925/WIFI*bin*",),
    "Intel CPU microcode": ("intel-ucode/*",),
}
for family, patterns in families.items():
    if not any(path.is_file() for pattern in patterns for path in root.glob(pattern)):
        raise SystemExit(f"Missing required firmware: {family}")
PY
# Include installed firmware and boot/storage drivers, not this builder's devices.
dracut --force --no-hostonly --kver "$kernel" "/usr/lib/modules/$kernel/initramfs.img"

mkdir -p /usr/share/home-k8s
rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' | sort > /usr/share/home-k8s/packages.tsv
# Each physical host must generate its own iSCSI initiator identity at boot.
rm -f /etc/iscsi/initiatorname.iscsi
# The installer/operator assigns a hostname; specializations may provide one.
rm -f /etc/hostname
: > /etc/machine-id
: > /etc/crypttab
dnf5 clean all
rm -f /usr/lib/sysimage/libdnf5/transaction_history.sqlite*
# Follow Utah's bootc hygiene: /var is runtime state, never image payload.
find /var -mindepth 1 -maxdepth 1 -exec rm -rf {} +
mkdir -p /var/home
find /run /tmp -mindepth 1 -maxdepth 1 ! -name .containerenv -exec rm -rf {} +
bootc container lint --fatal-warnings --skip nonempty-boot
