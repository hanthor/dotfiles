# Gateway (192.168.0.1)

## Hardware

- Model: TP-Link Archer AX10 v2.0
- MAC: `7C:F1:7E:A8:FF:74`
- Type: WiFi 6 router (AX1500)

## Firmware

- Version: `1.3.12 Build 20250828 Rel. 26873(5553)`

## Network

- Subnet: `192.168.0.0/24`
- DHCP pool: `.2` – `.253`
- Lease time: 120 minutes
- **WAN**: Direct public IP `122.163.159.113` (Airtel Fiber, dynamic)
- **ISP**: Bharti Airtel Broadband
- **Connection**: Fiber → ONT (bridge mode) → Ethernet → AX10 WAN port
- **CGNAT**: ❌ No — public IP directly on router, services can be port-forwarded

## Services

| Port | Service |
|------|---------|
| 53 | DNS |
| 80 | HTTP |
| 443 | HTTPS |
| 1900 | UPnP |

## Third-party firmware options

| Firmware | Status | Notes |
|----------|--------|-------|
| **OpenWrt** | ⚠️ Snapshot only | MediaTek MT7981B (Filogic 820) — initial support in mainline, not in stable release yet |
| **DD-WRT** | ❓ Forum discussion | [DD-WRT forum thread](https://forum.dd-wrt.com/phpBB2/viewtopic.php?t=335982) — community work-in-progress |
| **FreshTomato** | ❌ No | No AX/WiFi 6 support |

Chipset: MediaTek MT7981B (Filogic 820) — dual-core ARM Cortex-A53 @ 1.3GHz. Capable chipset, but AX10 v2 support is still maturing in third-party firmware.

## IPv6

- **Prefix**: `2401:4900:1c83:8ac0::/64` (ISP-provided, static)
- **Address lifetime**: 300s (privacy extensions active — host part rotates every 5 min)
- **Default route**: `fe80::7ef1:7eff:fea8:ff74` (router link-local, derived from MAC `7C:F1:7E:A8:FF:74`)
- **Connectivity**: ✅ Working (20ms to Google)

### Making IPv6 useful

Current issue: privacy extensions rotate addresses every 5 minutes — impractical for hosting services or stable SSH. Options:

1. **Stable SLAAC address** — add a static token on each machine:
   ```
   # /etc/systemd/network/eth0.network
   [IPv6AcceptRA]
   Token=::1  # becomes 2401:4900:1c83:8ac0::1
   ```
2. **Disable privacy extensions** (EUI-64, based on MAC):
   ```
   net.ipv6.conf.eth0.use_tempaddr = 0
   ```
3. **DHCPv6** — assign static addresses from router (if supported)

For fleet use: stable SLAAC tokens per machine give globally routable, static IPv6 addresses without needing Tailscale for basic SSH.

### Router limitations

- No IPv6 address on LAN interface (only link-local)
- No DHCPv6 server (router doesn't assign v6 addresses)
- No IPv6 firewall configurability in stock UI
- IPv6 prefix delegation: ISP delegates `/64` via SLAAC only
