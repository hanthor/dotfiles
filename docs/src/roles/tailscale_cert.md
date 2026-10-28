# tailscale_cert

`units/tailscale-cert.sh` obtains a Tailscale certificate for `<machine>.<tailscale_domain>` and installs a systemd renewal service, timer and helper from `units/tailscale-cert/`. It renews when `/etc/ssl/tailscale/cert.pem` has less than 30 days of validity or its private key is absent or empty. The certificate is root-owned 0644 and its private key root-owned 0640.

A valid existing certificate must cover the configured hostname and match the private key. A mismatch fails without replacing the existing pair; resolve the mismatch explicitly before applying again.

Both initial provisioning and the timer use the same helper: it serializes renewals with `flock`, requests the pair in a private temporary directory with a 720-hour minimum validity, checks the hostname, expiry and key match, and only replaces the existing files after a successful request. If committing the certificate fails, it restores the prior key; if restoration itself fails, the private backup is retained in the temporary directory and its path is reported. Symlinked or non-regular certificate paths are refused. The two file replacements cannot be atomic as a pair, so consumers may briefly observe the new key before the new certificate.

The unit requires `yq`, Python, OpenSSL, Tailscale, `flock`, systemd, and root or noninteractive `sudo -n`. It does not retrieve a Bitwarden secret. Effective inventory group settings are honored and host settings take precedence. It skips inventory VPSes (including nested VPS groups), retired `matrix`/`telengana`, `skip_tailscale_cert: true`, and `machine_profile: vm-test`; unknown hosts and invalid inventory settings fail closed. The timer is enabled only after the renewal helper and both systemd units are installed successfully.
