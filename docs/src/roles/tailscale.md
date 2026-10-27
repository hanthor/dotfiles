# tailscale

`units/tailscale.sh` skips Termux, where Android manages Tailscale. On other hosts it configures the resolved IPv6 stub and Tailscale forwarding/rp_filter sysctls, applies changed sysctls, and manages the resolver link when DNS acceptance is enabled and systemd-resolved is active. When `tailscale_accept_dns: false`, a connected host instead gets static DNS. These system changes require root or noninteractive `sudo -n`.

When already connected it sets the hostname, reconciles configured advertised routes, and configures the desktop operator and systray where applicable. When disconnected it installs Tailscale if needed, then joins via `units/tailscale-connect.py`. The helper reads the `tailscale-apikey` Bitwarden item's login password and passes it as `TS_OAUTH_CLIENT_SECRET` to `scripts/tailnet.py release NAME` before joining. Release removes offline matching names and numbered duplicates, not online devices, this device, or shared-in devices. Cleanup is best effort: failure produces a sanitized warning and joining is still attempted. The same credential is passed to Tailscale through a temporary private file that is removed afterwards, never in argv. An unlocked vault is needed for joining; a locked vault or `--no-secrets` produces `PARTIAL` and leaves the host disconnected.

Host variables include `tailscale_advertise_routes`, `tailscale_accept_dns`, `tailscale_operator`, and `tailscale_domain` (the domain also falls back to `group_vars/all.yml`). The shared unit library skips retired `matrix` and `telengana` before this unit changes anything; nothing on those hosts may be restarted.

Tailnet auditing, hostname release and OAuth credential setup are documented in [Tailnet hygiene](../tailnet.md).
