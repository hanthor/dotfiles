# Hive v2 + goose (DeepSeek) — QEMU-safe Slim Dockerfile
#
# Key workaround: avoid useradd (libaudit mmap fails under QEMU).
# Create dev user manually via /etc/passwd + /etc/group.

FROM --platform=linux/amd64 node:24-slim

ARG GOOSE_VERSION=1.36.0

# ── Runtime dependencies ─────────────────────────────────────────────
# NOTE: openssh-client removed (dpkg postinst fails under QEMU)
#       dev user created manually below (useradd fails under QEMU)
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl git gosu iptables inotify-tools jq \
    procps python3 python3-pip python3-venv sudo tmux \
 && rm -rf /var/lib/apt/lists/*

# ── su-exec for UID switching (compile from source, purge toolchain) ──
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev \
 && curl -sL -o /tmp/su-exec.c https://raw.githubusercontent.com/ncopa/su-exec/master/su-exec.c \
 && gcc -Wall -o /usr/local/bin/su-exec /tmp/su-exec.c \
 && chmod u+s /usr/local/bin/su-exec \
 && rm /tmp/su-exec.c \
 && apt-get purge -y gcc libc6-dev && apt-get autoremove -y

# ── Non-root dev user (manual — useradd fails under QEMU) ─────────────
# node:24-slim already has uid=1000 gid=1000 node user.
# Create dev user with uid=1001, gid=1000 (group node).
RUN echo 'dev:x:1001:1000::/home/dev:/bin/bash' >> /etc/passwd && \
    echo 'dev:!:20000:0:99999:7:::' >> /etc/shadow && \
    mkdir -p /home/dev && \
    chown 1001:1000 /home/dev && \
    chmod 755 /home/dev

# ── ttyd web terminal ─────────────────────────────────────────────────
RUN curl -sL -o /usr/local/bin/ttyd \
      "https://github.com/tsl0922/ttyd/releases/latest/download/ttyd.x86_64" && \
    chmod +x /usr/local/bin/ttyd

# ── GitHub CLI ────────────────────────────────────────────────────────
ARG GH_VERSION=2.74.0
RUN mkdir -p /opt/hive/bin && \
    curl -sL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" | \
    tar xz --strip-components=2 -C /opt/hive/bin "gh_${GH_VERSION}_linux_amd64/bin/gh" && \
    mv /opt/hive/bin/gh /opt/hive/bin/gh-real && \
    chmod +x /opt/hive/bin/gh-real

# ── Copilot CLI ───────────────────────────────────────────────────────
RUN npm install -g @github/copilot && npm cache clean --force || \
    echo "WARN: Copilot CLI install failed"

# ── goose CLI (DeepSeek backend) ──────────────────────────────────────
RUN curl -sL "https://github.com/aaif-goose/goose/releases/download/v${GOOSE_VERSION}/goose-x86_64-unknown-linux-gnu.tar.gz" | \
    tar xz -C /usr/local/bin goose && \
    chmod +x /usr/local/bin/goose

# ── Claude Code CLI ───────────────────────────────────────────────────
RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force || \
    echo "WARN: Claude Code install failed"

# ── Application ───────────────────────────────────────────────────────
ENV HOME=/home/dev

# Pre-compiled Go binaries (cross-compiled on host)
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
RUN chmod +x /usr/local/bin/gh-app-token.sh \
    /usr/local/bin/hive-config.sh /usr/local/bin/agent-launch.sh \
    /usr/local/bin/gh /usr/local/bin/git-credential-hive.sh

# Snapshot publisher
COPY dashboard/ /opt/hive/dashboard/
RUN chmod +x /opt/hive/dashboard/publish-snapshot*.sh 2>/dev/null || true

# Seed data + example configs
COPY examples/kubestellar/hive-project.yaml /etc/hive/hive-project.yaml
COPY examples/acmm/ /opt/hive/examples/acmm/
COPY examples/agents/ /opt/hive/examples/agents/
COPY v2/deploy/data/ /opt/hive/seed-data/
COPY v2/deploy/ttyd-tmux.sh /usr/local/bin/ttyd-tmux.sh
RUN chmod +x /usr/local/bin/ttyd-tmux.sh

# ── Nous framework ────────────────────────────────────────────────────
COPY bin/nous-runner.sh bin/nous-sync.py bin/nous-hive-gate.py bin/nous-install.sh /tmp/hive/bin/
RUN chmod +x /tmp/hive/bin/*.sh
COPY examples/kubestellar/nous-campaign.yaml examples/kubestellar/nous-governor-campaign.yaml examples/kubestellar/nous-repo-campaign.yaml /etc/hive/
RUN mkdir -p /var/run/nous/governor /var/run/nous/repo /data/nous/snapshots /opt/nous && \
    pip3 install --no-cache-dir --break-system-packages pyyaml 2>/dev/null || true && \
    pip3 install --no-cache-dir --break-system-packages specify-cli 2>/dev/null || true

# ── Goose defaults (overridable at runtime) ───────────────────────────
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
