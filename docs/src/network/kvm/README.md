# NanoKVM (192.168.0.99)

IP KVM for the fleet.

## Hardware

- Vendor: [Shenzhen Sipeed Technology](https://wiki.sipeed.com/hardware/en/kvm/NanoKVM/introduction.html)
- MAC: `48:DA:35:6F:A9:20`
- OS: [OpenWrt](https://openwrt.org/) 21.02 (Linux 5.4)

## Services

| Port | Service |
|------|---------|
| 22 | SSH |
| 80 | HTTP (web UI) |
| 443 | HTTPS |
| 8000 | HTTP-alt (filtered) |

## Notes

- Plugged into Karnataka
- Access at `http://192.168.0.99`
- Provides remote keyboard/video/mouse for Karnataka
