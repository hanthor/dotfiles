# Kerala

[PostMarketOS](https://postmarketos.org/) mobile device in the hanthor fleet.

## Hardware

- Arch: aarch64 (ARM)
- Mobile device (laptop power profile)
- Tailscale: `kerala-1` (MagicDNS; fleet alias `kerala`)

## OS

PostMarketOS (Alpine/musl-based)

## Notes

- Uses `apk` for package management (no [Homebrew](https://brew.sh/))
- Packages installed via `apk_packages` role
- Musl libc — Homebrew incompatible
