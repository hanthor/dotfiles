# Goa

Home server / Ansible control node for the hanthor fleet.

## Hardware

- Arch: aarch64 (ARM Cortex-A76)
- Board: [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/)
- MAC: `D8:3A:DD:E9:C7:1D`
- Tailscale IP: `100.69.238.116`

## OS

Debian GNU/Linux 13 (trixie), kernel 6.18.29

## Role

- **Fleet control plane** — runs [Ansible](https://www.ansible.com/) to manage all nodes
- Primary pi-coding-agent development host
- Inventory + health check hub (`just inventory`, `just doctor`)

## Notes

- [Homebrew](https://brew.sh/) at `/home/linuxbrew/.linuxbrew` (ARM — some bottles unavailable)
- System packages via `apt`, userland tools via `brew`
- Hosts the dotfiles git repo at `~/.local/share/dotfiles`
- Pi agent config at `~/.pi/agent/`
