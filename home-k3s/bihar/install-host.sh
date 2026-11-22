#!/usr/bin/env bash
# Run as root on Bihar. Leaves Utah, host firewall and Tailscale identity intact.
# K3s state stays in its default writable /var/lib/rancher/k3s. The upstream
# SELinux module cannot be added to Utah's read-only policy store at runtime;
# K3s SELinux container labeling is not enabled. Host SELinux stays enforcing.
set -euo pipefail
cd "$(dirname "$0")"
[ "$(id -u)" = 0 ] || { echo 'Run as root' >&2; exit 1; }
[ "$(hostname -s)" = bihar ] || { echo 'Wrong host' >&2; exit 1; }
ip -4 addr show dev tailscale0 | grep -q '100\.103\.44\.48/32' || { echo 'Expected Tailscale address is absent' >&2; exit 1; }
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
curl -fL --retry 3 'https://github.com/k3s-io/k3s/releases/download/v1.36.5+k3s1/k3s' -o "$tmp"
printf '%s  %s\n' d73847bcd3c5fccef0115b372e2f9a91f3032dc84bbf71518a4617565294d313 "$tmp" | sha256sum -c -
install -D -m 0755 "$tmp" /var/usrlocal/bin/k3s
install -D -m 0600 config.yaml /etc/rancher/k3s/config.yaml
install -D -m 0644 k3s.service /etc/systemd/system/k3s.service
install -D -m 0644 resolv.conf /etc/rancher/k3s/resolv.conf
install -D -m 0755 wait-tailnet.sh /var/usrlocal/libexec/k3s-wait-tailnet
# API reachable from the tailnet only (mirrors Karnataka). 9443 is ingress-nginx hostPort (KubeFlex control planes).
for p in 6443 9443; do firewall-cmd --permanent --zone=public --add-rich-rule="rule family=ipv4 source address=100.64.0.0/10 destination address=100.103.44.48/32 port port=$p protocol=tcp accept"; done
# Pod network -> kubelet (metrics-server); mirrors Karnataka.
firewall-cmd --permanent --zone=internal --change-interface=cni0
firewall-cmd --permanent --zone=internal --add-rich-rule="rule family=ipv4 source address=10.42.0.0/16 destination address=100.103.44.48/32 port port=10250 protocol=tcp accept"
# Pod egress to the internet (internal -> public); mirrors Karnataka.
firewall-cmd --permanent --new-policy=k3s-pod-egress || true
firewall-cmd --permanent --policy=k3s-pod-egress --set-target=CONTINUE
firewall-cmd --permanent --policy=k3s-pod-egress --add-ingress-zone=internal
firewall-cmd --permanent --policy=k3s-pod-egress --add-egress-zone=public
firewall-cmd --permanent --policy=k3s-pod-egress --add-rich-rule="rule family=ipv4 source address=10.42.0.0/16 accept"
firewall-cmd --reload
systemctl daemon-reload
systemctl enable --now k3s.service
