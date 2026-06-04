# Hive v2 + pi (DeepSeek) — MINIMAL Dockerfile
#
# Only installs pi coding agent (DeepSeek backend). Skips Claude Code, Copilot CLI,
# goose, ttyd, and Nous framework to keep the image small for faster pulls.
# Pi natively supports DeepSeek — no proxy, no litellm workaround needed.

FROM node:24-slim

# ── Minimal runtime dependencies ──────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl git gosu iptables inotify-tools jq \
    procps python3 sudo tmux util-linux \
    fd-find ripgrep \
 && ln -s /usr/bin/fdfind /usr/local/bin/fd \
 && rm -rf /var/lib/apt/lists/*

# ── gh CLI (for agent PR creation) ────────────────────────────────────
# Downloaded separately to get latest version.
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update && apt-get install -y --no-install-recommends gh \
 && mv /usr/bin/gh /usr/local/bin/gh-real \
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

# ── pi Coding Agent (DeepSeek backend) ────────────────────────────────
# pi natively supports DeepSeek via the deepseek provider. No proxy,
# no litellm, no reasoning_content workaround needed.
# We keep it as pi-real and use a wrapper for the hive tmux interface.
RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent && \
    mv /usr/local/bin/pi /usr/local/bin/pi-real && \
    chmod +x /usr/local/bin/pi-real && \
    npm cache clean --force

# Wrapper: handles hive tmux interface (restart loop, ready markers)
COPY pi-wrapper.sh /usr/local/bin/pi
RUN chmod +x /usr/local/bin/pi

# pi config directory (wrapper also creates this at runtime)
RUN mkdir -p /home/dev/.pi/agent && chown -R 1001:1000 /home/dev/.pi

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

# ── pi defaults ───────────────────────────────────────────────────────
# Provider/model configured via ~/.pi/agent/settings.json at runtime.
# DeepSeek API key passed via DEEPSEEK_API_KEY env var from K8s secret.

EXPOSE 3001 3002 7681
VOLUME ["/data", "/secrets"]

# Entrypoint
COPY v2/deploy/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

RUN chown -R 1001:1000 /data /home/dev 2>/dev/null || true

ENTRYPOINT ["entrypoint.sh"]
CMD ["--config", "/etc/hive/hive.yaml"]
