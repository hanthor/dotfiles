# ESP32 (192.168.0.112)

Unknown ESP32 device on the LAN.

## Hardware

- Vendor: Espressif
- MAC: `10:B4:1D:94:49:48`
- Type: ESP32 microcontroller

## Services

All ports filtered or closed — no listening services detected.

## Investigation

- [x] Full TCP port scan — all ports closed, no web UI
- [x] mDNS probe — no response
- [x] HTTP probe — no response
- [x] Common IoT ports (ESPHome, MQTT, CoAP) — all closed
- [x] UDP scan — only mDNS (5353) open|filtered
- [ ] Check router DHCP lease table for hostname
- [ ] Check router web UI for connected clients list
- [ ] Check for Panasonic Comfort Cloud / AC WiFi adapter MAC prefix
- [ ] Check Urban Company / native water purifier MAC ranges
- [ ] Try power-cycling the device and re-scan during boot
- [ ] Monitor network traffic to/from the device over time

## Theories

- **Panasonic AC WiFi adapter** — ESP32-based bridge between AC IR and WiFi
- **Urban Company water purifier** — ESP32-based IoT controller
- **Other IoT sensor** — no listening services, outbound-only communication
