# Network

Local network: `192.168.0.0/24` — gateway `192.168.0.1`

## Devices

| IP | Name | MAC | Vendor | Role |
|----|------|-----|--------|------|
| `.1` | `_gateway` | `7C:F1:7E:A8:FF:74` | TP-Link Systems | Router (DNS, HTTP, HTTPS, UPnP) |
| `.5` | bihar | `A8:A1:59:E1:6D:84` | ASRock | Talos K8s control plane |
| `.6` | karnataka | `9C:BF:0D:00:E5:0F` | Framework Computer | Talos K8s worker (AMD GPU) |
| `.10` | goa | *local* | — | Debian ARM SBC, fleet control |
| `.11` | phone | `86:E9:2C:CB:D2:E5` | Unknown | CMF Nothing Phone 1 (WiFi) |
| `.99` | NanoKVM | `48:DA:35:6F:A9:20` | Sipeed | IP KVM, OpenWrt, SSH/HTTP/HTTPS |
| `.112` | espressif | `10:B4:1D:94:49:48` | Espressif | ESP32 (IoT/sensor?) |
| `.216` | dilli | — | — | Laptop (WiFi, when online) |

## Fleet nodes (Tailscale MagicDNS)

| Hostname | Tailscale IP | LAN IP | Group |
|----------|-------------|--------|-------|
| goa | `100.69.238.116` | `.10` | server |
| bihar | `100.85.9.86` | `.5` | server |
| karnataka | *MagicDNS* | `.6` | llm |
| himachal | `100.73.3.51` | DHCP | desktop |
| dilli | `100.76.126.90` | `.216` | desktop |
| kanpur | *MagicDNS* | DHCP | desktop |
| kerala | `100.67.142.116` | cellular | desktop |
| matrix | `100.73.19.81` | remote | vps |
| lkofoss | `77.42.94.83` | remote | vps |
