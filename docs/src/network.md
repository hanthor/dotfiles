# Network

The home LAN is a single flat private /24 behind a consumer router (DNS,
DHCP). Most fleet traffic goes over Tailscale instead. Per-host addresses are
not published here — run `just inventory` for the live LAN + Tailscale
crosswalk.

## Devices

| Name | Role |
|------|------|
| gateway | Router (DNS, DHCP) — see [Gateway](network/gateway/README.md) |
| bihar | OS and services unverified; currently unreachable — reserved address |
| karnataka | Utah host with AMD GPU; default target `multi-user.target` — reserved address |
| goa | Fleet control, Debian ARM (Raspberry Pi) — reserved address |
| phone | Android phone (reserved address) |
| printer | Network printer (DHCP) |
| macbook | MacBook Air (DHCP) |
| kvm | NanoKVM (reserved address) — see [KVM](network/kvm/README.md) |
| esp32 | Unidentified IoT device (static address) |
| dilli | Laptop (WiFi, when online) |

## Fleet nodes and known names

For inventory hosts, `ansible_host` in `inventory.yml` holds the tailnet address
where one is needed. A listed name or reserved address does not establish that
the host or MagicDNS is currently reachable.

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
| bihar | reserved | not in inventory — currently unreachable, OS and services unverified |
| karnataka | reserved | server — Utah; Tailscale `100.66.158.127`; default target `multi-user.target` |
