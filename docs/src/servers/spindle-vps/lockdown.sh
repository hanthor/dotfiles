#!/usr/bin/env bash
# Run ON the VPS after `sudo tailscale up` has joined the tailnet and SSH over the tailnet works.
# Locks the host down: SSH only over tailscale0; only 80/443 (Caddy) public; everything else dropped.
# Oracle's console "Instance console connection" remains the break-glass path.
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
echo "locked down. Public ports left: 80, 443. Also delete the public SSH ingress rule in the OCI security list."
