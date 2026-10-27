#!/usr/bin/env bash
# Run as root on Karnataka. Leaves Utah, host firewall and Tailscale identity intact.
# K3s state stays in its default writable /var/lib/rancher/k3s. The upstream
# SELinux module cannot be added to Utah's read-only policy store at runtime;
# K3s SELinux container labeling is not enabled. Host SELinux stays enforcing.
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(hostname -s)" = karnataka ] || { echo 'Wrong host' >&2; exit 1; }
ip -4 addr show dev tailscale0 | grep -q '100\.66\.158\.127/32' || { echo 'Expected Tailscale address is absent' >&2; exit 1; }
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
curl -fL --retry 3 'https://github.com/k3s-io/k3s/releases/download/v1.36.5%2Bk3s1/k3s' -o "$tmp"
printf '%s  %s\n' d73847bcd3c5fccef0115b372e2f9a91f3032dc84bbf71518a4617565294d313 "$tmp" | sha256sum -c -
install -D -m 0755 "$tmp" /var/usrlocal/bin/k3s
install -D -m 0755 wait-tailnet.sh /var/usrlocal/libexec/k3s-wait-tailnet
install -D -m 0600 config.yaml /etc/rancher/k3s/config.yaml
install -D -m 0644 k3s.service /etc/systemd/system/k3s.service
install -D -m 0644 resolv.conf /etc/rancher/k3s/resolv.conf
systemctl daemon-reload
systemctl enable --now k3s.service
