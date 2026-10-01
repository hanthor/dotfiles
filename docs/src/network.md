# Network

The home LAN is a single flat private /24 behind a consumer router (DNS,
DHCP). Most fleet traffic goes over Tailscale instead. Per-host addresses are
not published here — run `just inventory` for the live LAN + Tailscale
crosswalk.

## Devices

| Name | Role |
|------|------|
| gateway | Router (DNS, DHCP) — see [Gateway](network/gateway/README.md) |
| bihar | Talos K8s control plane (powered down, expected back) — reserved address |
| karnataka | Talos K8s worker, AMD GPU (powered down, expected back) — reserved address |
| goa | Fleet control, Debian ARM (Raspberry Pi) — reserved address |
| phone | Android phone (reserved address) |
| printer | Network printer (DHCP) |
| macbook | MacBook Air (DHCP) |
| kvm | NanoKVM (reserved address) — see [KVM](network/kvm/README.md) |
| esp32 | Unidentified IoT device (static address) |
| dilli | Laptop (WiFi, when online) |

## Fleet nodes (Tailscale MagicDNS)

Hosts are reached by MagicDNS name; `ansible_host` in `inventory.yml` holds the
tailnet address where one is needed.

| Hostname | LAN | Group |
|----------|-----|-------|
| goa | reserved | server (applies locally) |
| punjab | — (AWS) | server |
| himachal | DHCP | desktop |
| dilli | DHCP | desktop |
| kanpur | DHCP | desktop |
| kerala | cellular | desktop |
| mumbai (ssh `:2222`) | phone | desktop (phone VM) |
| termux (ssh `:8022`) | phone | termux_hosts |
| matrix | remote | vps — retired |
| telengana | remote | vps — retired |
| bihar | reserved | Talos, not in inventory — offline |
| karnataka | reserved | Talos, not in inventory — offline |
