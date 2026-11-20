#!/bin/bash
set -x
systemctl stop k3s
pgrep -f '^/var/lib/rancher/k3s/data/.*/containerd-shim' | xargs -r kill -9
sleep 2
awk '$2 ~ "^/(run/k3s|var/lib/kubelet|var/lib/rancher/k3s)" {print $2}' /proc/self/mounts | sort -r | while read -r m; do umount -l "$m"; done
ip link del cni0 2>/dev/null; ip link del flannel.1 2>/dev/null
iptables-save | grep -vE "KUBE-|CNI-|flannel" | iptables-restore
ip6tables-save | grep -vE "KUBE-|CNI-|flannel" | ip6tables-restore
rm -rf /var/lib/rancher/k3s /var/lib/kubelet /run/k3s /run/flannel /var/lib/cni /etc/rancher/k3s/k3s.yaml
install -m 0600 /home/james/home-k3s/config.yaml /etc/rancher/k3s/config.yaml
systemctl start k3s
systemctl is-active k3s
