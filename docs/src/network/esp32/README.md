# ESP32 (192.168.0.112)

Unknown [ESP32](https://www.espressif.com/en/products/socs/esp32) device on the LAN.

## Hardware

- Vendor: [Espressif](https://www.espressif.com/)
- MAC: `10:B4:1D:94:49:48`
- Type: ESP32 microcontroller

## Services

All ports filtered or closed — no listening services detected.

## Investigation

- [x] Full TCP port scan — all ports closed, no web UI
- [x] mDNS probe — no response
- [x] HTTP probe — no response
- [x] Common IoT ports ([ESPHome](https://esphome.io/), [MQTT](https://mqtt.org/), CoAP) — all closed
- [x] UDP scan — only mDNS (5353) open|filtered
- [x] Check router DHCP lease table for hostname
- [x] Check router web UI for connected clients list
  - **NOT in DHCP client list** — device likely has a static IP
  - Not in address reservation list either
- [ ] Check for Panasonic Comfort Cloud / AC WiFi adapter MAC prefix
- [ ] Check Urban Company / native water purifier MAC ranges
- [ ] Try power-cycling the device and re-scan during boot
- [ ] Monitor network traffic to/from the device over time

## Theories

- **Panasonic AC WiFi adapter** — ESP32-based bridge between AC IR and WiFi
- **Urban Company water purifier** — ESP32-based IoT controller
- **Other IoT sensor** — no listening services, outbound-only communication

## DHCP Status

Not in DHCP client list or address reservation table — static IP likely configured on-device. Not getting its IP from the router.
