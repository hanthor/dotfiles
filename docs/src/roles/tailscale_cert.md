# tailscale_cert

`units/tailscale-cert.sh` obtains a Tailscale certificate for `<machine>.<tailscale_domain>` and installs a systemd renewal service and timer from `units/tailscale-cert/`, rendered by `units/service-templates.py`. It checks whether `/etc/ssl/tailscale/cert.pem` remains valid for 30 days; otherwise it runs `tailscale cert` with a 720-hour minimum validity. The certificate is root-owned 0644 and its private key root-owned 0640.

The unit requires `yq`, Python, OpenSSL, Tailscale, systemd, and root or noninteractive `sudo -n`. It does not retrieve a Bitwarden secret. The host domain overrides `group_vars/all.yml`. It skips inventory VPSes, retired `matrix`/`telengana`, `skip_tailscale_cert: true`, and `machine_profile: vm-test`. The timer is enabled only after both renewal units are installed successfully.
