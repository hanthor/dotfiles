# proxy (Caddy)

`units/proxy.sh` deploys the rootful Caddy quadlet from `units/proxy/caddy.container` and renders `units/proxy/Caddyfile.j2` using `units/service-templates.py` and the host's `web_services` list. Caddy is configured on port 9000; the unit points the default Tailscale Serve HTTPS handler at `127.0.0.1:9000`. Routes include `/service/<name>` redirects and `/bst/`; there is no homepage at `/`.

The unit requires `yq`, Python, root or noninteractive `sudo -n`, systemd, Podman and Tailscale. It skips inventory VPSes, retired `matrix`/`telengana`, `skip_proxy: true`, and `machine_profile: vm-test`. It does not fetch vault secrets. The Tailscale Serve configuration can replace an existing default HTTPS handler.

It writes `/etc/caddy/Caddyfile` and `/etc/containers/systemd/caddy.container` as root-owned 0644 files. Activation is skipped if either deployment fails; otherwise it reloads systemd, restarts Caddy after changes, and enables and starts the service before changing Serve.
