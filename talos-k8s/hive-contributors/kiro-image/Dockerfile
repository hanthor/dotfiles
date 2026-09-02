# hive-contributor-kiro — upstream Hive contributor image + Kiro CLI.
#
# The upstream ghcr.io/kubestellar/hive-contributor image ships claude, codex,
# agy, and pi but NOT kiro-cli. This image layers Kiro on top and teaches the
# relay's backend table about a `kiro` backend.
#
# HOW THE RELAY LAUNCHES A BACKEND: contributor-relay.sh sources backends.conf,
# reads backend_binary()+backend_perm_flag(), and launches
#   <binary> <perm-flags> [--model <m>]
# in a tmux PTY as an INTERACTIVE chat session (it then send-keys the task
# prompt in). There is no place to inject a `chat` sub-command, and bare
# `kiro-cli` is NOT a chat REPL. So backend_binary(kiro) resolves to a thin
# wrapper (`kiro-hive`) that execs `kiro-cli chat`, giving the relay the
# interactive chat session it expects — the same shape as bare `claude`.
#
# Build & push (built locally with podman, NOT by CI — mirrors the pi-deepseek
# pattern in the tunaos-contributor-fleet skill):
#
#   cd talos-k8s/hive-contributors/kiro-image
#   podman build --build-arg TARGETARCH=amd64 \
#     -t ghcr.io/hanthor/hive-contributor-kiro:latest .
#   podman push ghcr.io/hanthor/hive-contributor-kiro:latest
#
# TARGETARCH: amd64 or arm64 (the AWS Talos nodes are amd64 today).
FROM ghcr.io/kubestellar/hive-contributor:latest

# We need root to install into /usr/local/bin; the base image ends on USER dev.
USER root

ARG TARGETARCH=amd64
# glibc build; the base image is debian-slim (glibc >= 2.34), so the non-musl
# package is correct. Switch to the -musl.zip variant only on a musl base.
RUN set -eux; \
    case "$TARGETARCH" in \
      amd64) KIRO_ARCH=x86_64 ;; \
      arm64) KIRO_ARCH=aarch64 ;; \
      *) echo "unsupported TARGETARCH=$TARGETARCH" >&2; exit 1 ;; \
    esac; \
    apt-get update; \
    apt-get install -y --no-install-recommends unzip ca-certificates curl; \
    rm -rf /var/lib/apt/lists/*; \
    curl --proto '=https' --tlsv1.2 -fsSL \
      "https://desktop-release.q.us-east-1.amazonaws.com/latest/kirocli-${KIRO_ARCH}-linux.zip" \
      -o /tmp/kirocli.zip; \
    mkdir -p /tmp/kirocli; \
    unzip -q /tmp/kirocli.zip -d /tmp/kirocli; \
    KIRO_BIN="$(find /tmp/kirocli -type f -name 'kiro-cli' | head -1)"; \
    test -n "$KIRO_BIN"; \
    install -m 0755 "$KIRO_BIN" /usr/local/bin/kiro-cli; \
    rm -rf /tmp/kirocli /tmp/kirocli.zip; \
    /usr/local/bin/kiro-cli --version || true

# Thin wrapper: the relay launches this as the "binary"; it starts the Kiro
# chat REPL so the interactive send-keys path works. Perm flags from
# backend_perm_flag(kiro) arrive as "$@" and are forwarded to `kiro-cli chat`.
COPY kiro-hive /usr/local/bin/kiro-hive
RUN chmod 0755 /usr/local/bin/kiro-hive

# Teach the relay's backend table about `kiro` (concatenated after the base
# defs so these functions shadow the base ones; other backends delegate back).
COPY backends-kiro.conf /usr/local/etc/hive/backends-kiro.conf
RUN cat /usr/local/etc/hive/backends-kiro.conf >> /usr/local/etc/hive/backends.conf

USER dev
