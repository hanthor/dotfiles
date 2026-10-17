# Dilli

Secondary workstation in the hanthor fleet.

## Hardware

- Arch: x86_64
- WiFi on the home LAN (DHCP)
- Tailscale: `dilli` (MagicDNS: `dilli.manatee-basking.ts.net`)
- SSH User: `james` (`ssh james@dilli`)
## OS

[Bluefin](https://projectbluefin.io/) (Fedora Atomic)

## Services

- BuildStream Dashboard — build monitor

## Notes

- [PaperWM](https://github.com/paperwm/PaperWM), Papershell, Copyous extensions synced from fleet
- Brew packages managed via dotfiles playbook
