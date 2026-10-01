# Gateway

The home router: a consumer WiFi 6 router doing DNS and DHCP for the flat LAN.

## Network

- One private /24, DHCP pool covering most of the range, short lease time
- Fixed addresses for infrastructure (bihar, karnataka, goa, kvm) come from the
  router's address-reservation table, not from static config on the hosts
- ISP fiber, ONT in bridge mode, router holds the WAN address directly
- Nothing is port-forwarded; remote access to the fleet is via Tailscale

## Third-party firmware

The router's chipset (MediaTek Filogic 820) has only snapshot-level
[OpenWrt](https://openwrt.org/) support so far, so it runs stock firmware.
Revisit once a stable OpenWrt release supports it.

## IPv6

The ISP delegates a single /64 via SLAAC only. The stock firmware has no LAN
DHCPv6 server and no configurable IPv6 firewall. Hosts use privacy
extensions, so their addresses rotate — impractical for hosting or stable SSH.
Options if stable v6 addresses are ever wanted:

1. **Stable SLAAC token** per machine:
   ```
   # /etc/systemd/network/eth0.network
   [IPv6AcceptRA]
   Token=::1  # becomes <prefix>::1
   ```
2. **Disable privacy extensions** (EUI-64, based on MAC):
   ```
   net.ipv6.conf.eth0.use_tempaddr = 0
   ```
3. **DHCPv6** — not available on the stock firmware.

Tailscale remains the default path for fleet SSH.
