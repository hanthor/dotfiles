#!/usr/bin/env bash
# Run as root on Karnataka. Leaves Utah, host firewall and Tailscale identity intact.
# K3s state stays in its default writable /var/lib/rancher/k3s. The upstream
# SELinux module cannot be added to Utah's read-only policy store at runtime;
# K3s SELinux container labeling is not enabled. Host SELinux stays enforcing.
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(hostname -s)" = karnataka ] || { echo 'Wrong host' >&2; exit 1; }
[ "$(uname -m)" = x86_64 ] || { echo 'K3s asset requires x86_64' >&2; exit 1; }
ip -4 -o addr show dev tailscale0 | grep -Fq 'inet 100.66.158.127/32 ' || { echo 'Expected Tailscale address is absent' >&2; exit 1; }
binary=/var/usrlocal/bin/k3s
checksum=d73847bcd3c5fccef0115b372e2f9a91f3032dc84bbf71518a4617565294d313
if ! printf '%s  %s\n' "$checksum" "$binary" | sha256sum --check --status; then
  if systemctl is-active --quiet k3s.service; then
    echo 'Refusing to replace a different K3s binary while the service is running' >&2
    exit 1
  fi
  tmp=$(mktemp)
  trap 'rm -f "$tmp"' EXIT
  curl -fL --retry 3 'https://github.com/k3s-io/k3s/releases/download/v1.36.5%2Bk3s1/k3s' -o "$tmp"
  printf '%s  %s\n' "$checksum" "$tmp" | sha256sum -c -
  install -D -m 0755 "$tmp" "$binary"
fi
install -D -m 0755 wait-tailnet.sh /var/usrlocal/libexec/k3s-wait-tailnet
install -D -m 0600 config.yaml /etc/rancher/k3s/config.yaml
install -D -m 0644 k3s.service /etc/systemd/system/k3s.service
install -D -m 0644 resolv.conf /etc/rancher/k3s/resolv.conf
systemctl daemon-reload
systemctl enable --now k3s.service
echo 'Existing K3s processes are not restarted; changed service or server configuration takes effect on the next start.'
echo 'Manage and verify the host firewall separately with firewall.sh --apply and --check.'
