# Hive v2 + goose (DeepSeek) — MINIMAL Dockerfile
#
# Only installs goose (DeepSeek backend). Skips Claude Code, Copilot CLI,
# ttyd, and Nous framework to keep the image small for faster pulls.

FROM node:24-slim

# ── Minimal runtime dependencies ──────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl git gosu iptables inotify-tools jq \
    procps python3 sudo tmux util-linux \
 && rm -rf /var/lib/apt/lists/*

# ── su-exec for UID switching ─────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates gcc libc6-dev \
 && update-ca-certificates \
 && curl -sL -o /tmp/su-exec.c https://raw.githubusercontent.com/ncopa/su-exec/master/su-exec.c \
 && gcc -Wall -o /usr/local/bin/su-exec /tmp/su-exec.c \
 && chmod u+s /usr/local/bin/su-exec \
 && rm /tmp/su-exec.c \
 && apt-get purge -y gcc libc6-dev && apt-get autoremove -y

# ── Non-root dev user (manual — useradd fails under QEMU) ─────────────
RUN echo 'dev:x:1001:1000::/home/dev:/bin/bash' >> /etc/passwd && \
    echo 'dev:!:20000:0:99999:7:::' >> /etc/shadow && \
    mkdir -p /home/dev && chown 1001:1000 /home/dev && chmod 755 /home/dev

# ── goose CLI (DeepSeek backend) ──────────────────────────────────────
# goose v1.x has native DeepSeek support via custom_deepseek provider.
# We keep it as goose-real and use a wrapper to handle the old hive
# --no-confirm interface. Falls back to Python if goose is missing.
ARG GOOSE_VERSION=1.36.0
RUN curl -sL "https://github.com/aaif-goose/goose/releases/download/v${GOOSE_VERSION}/goose-x86_64-unknown-linux-gnu.tar.gz" | \
    tar xz -C /usr/local/bin && \
    mv /usr/local/bin/goose /usr/local/bin/goose-real && \
    chmod +x /usr/local/bin/goose-real

# Python fallback (direct DeepSeek API calls)
COPY deepseek-chat.py /usr/local/bin/deepseek-chat.py

# Wrapper: translates old hive goose CLI, tries goose-real first
COPY goose-wrapper.sh /usr/local/bin/goose
RUN chmod +x /usr/local/bin/goose /usr/local/bin/deepseek-chat.py

# ── Application ───────────────────────────────────────────────────────
ENV HOME=/home/dev

# Pre-compiled Go binaries
COPY hive-binary /usr/local/bin/hive
COPY bd-binary /usr/local/bin/bd

# Node.js proxy + dashboard static
COPY v2/proxy/ /opt/hive/proxy/
RUN cd /opt/hive/proxy && npm install --omit=dev

COPY v2/pkg/dashboard/static/index.html /opt/hive/proxy/public/

# Shell scripts
COPY bin/gh-app-token.sh bin/hive-config.sh bin/agent-launch.sh bin/git-credential-hive.sh /usr/local/bin/
COPY bin/gh-wrapper.sh /usr/local/bin/gh
COPY config/backends.conf /usr/local/etc/hive/backends.conf
RUN chmod +x /usr/local/bin/gh-app-token.sh /usr/local/bin/hive-config.sh \
    /usr/local/bin/agent-launch.sh /usr/local/bin/gh /usr/local/bin/git-credential-hive.sh

# Seed data + example configs
COPY examples/kubestellar/hive-project.yaml /etc/hive/hive-project.yaml
COPY examples/acmm/ /opt/hive/examples/acmm/
COPY examples/agents/ /opt/hive/examples/agents/
COPY v2/deploy/data/ /opt/hive/seed-data/
COPY v2/deploy/ttyd-tmux.sh /usr/local/bin/ttyd-tmux.sh
RUN chmod +x /usr/local/bin/ttyd-tmux.sh

# ── Goose defaults ────────────────────────────────────────────────────
ENV GOOSE_PROVIDER=openai_compatible \
    GOOSE_MODEL=deepseek-v4-pro

EXPOSE 3001 3002 7681
VOLUME ["/data", "/secrets"]

# Entrypoint
COPY v2/deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

RUN chown -R 1001:1000 /data /home/dev 2>/dev/null || true

ENTRYPOINT ["entrypoint.sh"]
CMD ["--config", "/etc/hive/hive.yaml"]
