#!/bin/sh
# The K3s API binds to this address; tailscaled can start before it exists.
set -u
for _ in $(seq 1 60); do
    if ip -4 -o addr show dev tailscale0 2>/dev/null | grep -Fq 'inet 100.66.158.127/32 '; then
        exit 0
    fi
    sleep 1
done
echo 'K3s cannot start: expected Tailscale address is not present' >&2
exit 1
