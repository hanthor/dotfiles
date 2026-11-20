#!/usr/bin/env bash
# Run ON the VPS after `sudo tailscale up` has joined the tailnet and SSH over the tailnet works.
# Locks direct host INPUT down: SSH only over tailscale0; direct host ports 80/443 only.
# Docker-published LiveKit ports are filtered by the OCI security list; keep it limited to this runbook's ports.
set -euo pipefail
ip link show tailscale0 >/dev/null || { echo "tailscale0 is not up; join the tailnet first" >&2; exit 1; }
tailscale ip -4 >/dev/null || { echo "not logged in to tailscale" >&2; exit 1; }

# 1. Accept everything arriving over the tailnet interface (SSH, admin ports).
iptables -C INPUT -i tailscale0 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -i tailscale0 -j ACCEPT
# 2. Drop the stock "SSH from anywhere" rule Oracle's Ubuntu image ships.
while iptables -C INPUT -p tcp -m state --state NEW -m tcp --dport 22 -j ACCEPT 2>/dev/null; do
  iptables -D INPUT -p tcp -m state --state NEW -m tcp --dport 22 -j ACCEPT
done
netfilter-persistent save
# 3. sshd: keys only, no root; bind stays on all interfaces but the firewall only lets tailscale0 in.
sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin) '
echo "locked down. Host INPUT: 80/443. Docker LiveKit ports: TCP 30001; UDP 32700-32767 (OCI security list). Also delete public SSH ingress in OCI."
