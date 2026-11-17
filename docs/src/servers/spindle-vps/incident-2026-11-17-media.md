# 2026-11-16/17: slow sync, missing avatars, Element X image errors

Symptoms on `matrix.reilly.asia`: sync felt slow, profile and room pictures were missing, and Element X
showed **"Sorry, an error occurred"** for every image. Four separate faults, plus host load.

The general fault guide (checks and fixes for any Spindle operator) is in the Spindle repo:
[`docs/troubleshooting.md`](https://github.com/tuna-os/spindle/blob/main/docs/troubleshooting.md).

## What was wrong and where it was fixed

| Fault | Symptom | Fix |
|---|---|---|
| Element X 26.11 requests media at `/_matrix/client/unstable/org.matrix.msc3916/media/…`; Spindle served only `/v1/media` | Every image and avatar 404s (`route="unmatched"` in metrics); Element X error dialog | Caddy rewrite (live now, also in this kit's `Caddyfile`); Spindle [#940](https://github.com/tuna-os/spindle/pull/940) serves the prefix itself |
| Federation media answered with a `Location` header was cached as 0 bytes | Beeper avatars blank forever | [#933](https://github.com/tuna-os/spindle/pull/933), in v0.1.5 |
| CDN labels images `application/octet-stream` | `M_UNSUPPORTED: no thumbnails for application/octet-stream` | [#937](https://github.com/tuna-os/spindle/pull/937), in v0.1.6 |
| Partial-state (faster-join) rooms never finished resync: one bad member signature, or one auth event the resident refuses with 403, failed the whole room; keys were fetched one server at a time | Newly joined big rooms have no member list or member avatars; `/joined_members` hangs | [#935](https://github.com/tuna-os/spindle/pull/935) (v0.1.5), [#938](https://github.com/tuna-os/spindle/pull/938) (v0.1.6) |

Not Spindle bugs, still open:

- **A browser tab looping on a dead token.** Firefox at `https://hanthor.github.io` sent sync/whoami/keys
  ~20 req/s, all `401 M_UNKNOWN_TOKEN`, after the MAS → built-in OIDC switch on 2026-11-16. Sign out and back
  in (or close it); the client should have logged itself out.
- **Host contention.** 2 OCPU / 12 GB, no swap; the School and Reef Hives use ~2.6 GB and heavy CPU/disk.
  Spindle's first sync after a restart takes up to a minute while caches warm. Moving the Hives off this
  host is the biggest remaining speed-up.
- **`synctap`** still proxies sliding sync for `@james` (0.5 CPU cap). Remove the service and the `@ssync`
  Caddy handle when that diagnosis is done.

## Live state left behind (as of 2026-11-17)

- `compose.yaml` runs `ghcr.io/tuna-os/spindle:v0.1.5` (backup `compose.yaml.bak-pre-v0.1.5-*`). Bump to the
  release that contains #940, then delete the `@msc3916` rewrite.
- `Caddyfile` has two temporary additions, each with a comment:
  - the `@msc3916` rewrite (keep until #940 is deployed);
  - an access log to `/data/access-diag.log` inside the Caddy container (`./caddy/access-diag.log` on the
    host). Headers and `access_token` are stripped. Remove the `log` block when done; the file grows.
- `@claude-test:reilly.asia` is a non-admin test account, joined to `#fedora:fedoraproject.org`. Its password
  is in `~/.spindle-testuser-pass` (mode 600) on the VPS. Deactivate it when it is no longer needed.

## Diagnosing on this host

- **Metrics:** `docker exec spindle-caddy-1 wget -qO- http://spindle:9100/metrics`.
  `spindle_http_requests_total{route="unmatched"}` counts paths Spindle does not serve.
- **`docker logs spindle-caddy-1` shows nothing new:** the container's json log file was deleted from disk.
  Log to a file in `/data` instead (above).
- **Editing `Caddyfile` or `spindle.toml`:** both are single-file bind mounts. `sed -i` and most editors
  replace the inode, and the container keeps reading the old file. Write in place
  (`cat new > Caddyfile`, or Python `open(p, "r+")` + `truncate`), or restart the container.
  Check with `docker exec spindle-caddy-1 cat /etc/caddy/Caddyfile`.
- **Seeing what a client requests:** `sudo tcpdump -i any -A "tcp port 8008 and host <spindle container IP>"`
  shows plaintext proxy→Spindle traffic (it includes bearer tokens; do not save it).
- **Partial-state rooms:** `docker logs spindle-spindle-1 | grep -E "resync|partial-state"`.
- **Test account while registration is closed:** add `shared_secret` under `[registration]`, restart, register
  via `/_synapse/admin/v1/register` (Synapse HMAC), remove the secret, restart. Details in the Spindle fault guide.

## Releasing a Spindle fix to this host

`release.yml` (dispatch with `bump=patch`) tags `main` only after **every** check on the commit has finished,
including the Matrix compliance suite (~1 h after merge). Dispatching earlier logs "CI is still running" or
"The Rust quality gate has not passed" and builds nothing. Then:

```sh
cd /srv/spindle
cp compose.yaml compose.yaml.bak-pre-vX.Y.Z-$(date -u +%Y%m%dT%H%M%S)
sed -i 's#tuna-os/spindle:vOLD#tuna-os/spindle:vNEW#' compose.yaml   # compose.yaml is not bind-mounted
docker compose pull spindle && docker compose up -d spindle
```
