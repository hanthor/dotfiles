# hive-contributor-kiro image

Thin overlay on `ghcr.io/kubestellar/hive-contributor:latest` that adds the
Kiro CLI (`kiro-cli`) and wires it in as a `kiro` Hive backend. Only
`kiro-contributor` needs this image; the other three backends (claude, agy,
pi/codex) already ship in the upstream image.

## Why a custom image (and only for Kiro)

The upstream contributor image already contains `claude`, `codex`, `agy`, and
`pi`, selectable with `AGENT_BACKEND`. `kiro-cli` is not included, so it must be
layered on.

## How Kiro plugs into the relay

`contributor-relay.sh` launches the resolved backend binary in a tmux PTY as an
**interactive chat REPL**, then types the task prompt into it with `send-keys`.
Two adaptations make Kiro fit that contract:

1. **`kiro-hive` wrapper** — `backend_binary(kiro)` resolves to `kiro-hive`,
   which `exec`s `kiro-cli chat "$@"`. Bare `kiro-cli` is not a chat REPL and
   there is no hook to inject a `chat` sub-command, so the wrapper supplies it.
2. **`backends-kiro.conf` overlay** — appended to the image's `backends.conf`,
   it shadows `backend_binary`/`backend_perm_flag` to add a `kiro` case
   (delegating all other backends to the originals) and sets
   `--trust-all-tools` so an unattended pane never blocks on a tool-approval
   prompt.

Kiro's TUI needs a PTY; a non-TTY exec crashes with `failed to enable raw mode`
(Kiro issue #5250). tmux provides the PTY, so the interactive path is correct
and `--no-interactive` is deliberately NOT used.

## Auth

Headless auth via `KIRO_API_KEY` (`ksk_...`) from the pod Secret — no browser
device flow in an unattended pod. Kiro writes session state under the home dir,
which is a PVC, so it persists across restarts.

## Build & push

```bash
cd talos-k8s/hive-contributors/kiro-image
podman build --build-arg TARGETARCH=amd64 \
  -t ghcr.io/hanthor/hive-contributor-kiro:latest .
podman push ghcr.io/hanthor/hive-contributor-kiro:latest
```

`TARGETARCH` is `amd64` (AWS Talos nodes today) or `arm64`. The image pulls the
glibc Kiro build; switch the Dockerfile to the `-musl.zip` URL only on a musl
base.

## Verify locally before pushing

```bash
podman run --rm --entrypoint sh ghcr.io/hanthor/hive-contributor-kiro:latest -c '
  kiro-cli --version
  kiro-hive --help >/dev/null 2>&1; echo "wrapper exit: $?"
  bash -c "source /usr/local/etc/hive/backends.conf; \
           echo binary=\$(backend_binary kiro); \
           echo perm=\$(backend_perm_flag kiro); \
           echo claude_still=\$(backend_binary claude)"
'
```

Expected: `binary=kiro-hive`, `perm=--trust-all-tools`, `claude_still=claude`.
