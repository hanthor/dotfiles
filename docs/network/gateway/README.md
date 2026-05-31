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
