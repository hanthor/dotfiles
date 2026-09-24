# Himachal

Laptop workstation in the hanthor fleet.

## Hardware

- Arch: x86_64
- Laptop (runs on login, not periodic timer)
- Tailscale: `himachal` (MagicDNS)

## OS

[Bluefin](https://projectbluefin.io/) (Fedora Atomic)

## Services

- `hive_ops` timers — drives the tuna-os Hive on the AWS cluster (`hive_ops_enabled: true`)

## Notes

- `dotfiles_update_delay_seconds: 90` — applies dotfiles 90s after login
- [PaperWM](https://github.com/paperwm/PaperWM) tiling, Papershell blur, Copyous clipboard — synced from fleet
