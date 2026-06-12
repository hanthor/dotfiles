FROM debian:bookworm-slim

# Runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl git jq tmux python3 ca-certificates gnupg openssh-client \
  && rm -rf /var/lib/apt/lists/*

# gh CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
  && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
  && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

# Goose CLI
RUN ARCH=$(dpkg --print-architecture) \
  && GOOSE_ARCH=$([ "$ARCH" = "arm64" ] && echo "aarch64" || echo "x86_64") \
  && curl -fsSL "https://github.com/block/goose/releases/latest/download/goose-${GOOSE_ARCH}-unknown-linux-gnu.tar.gz" \
    -o /tmp/goose.tar.gz \
  && cd /tmp && tar -xzf goose.tar.gz \
  && find /tmp -name "goose" -type f -exec cp {} /usr/local/bin/goose \; \
  && chmod +x /usr/local/bin/goose && rm -rf /tmp/goose*

# Copy hive contributor scripts from upstream repo
COPY bin/contributor-agent.sh /usr/local/bin/
COPY bin/contributor-relay.sh /usr/local/bin/
COPY bin/agent-launch.sh /usr/local/bin/
COPY bin/gh-wrapper.sh /usr/local/bin/gh-wrapper
COPY config/backends.conf /usr/local/etc/hive/
COPY config/restrictions/contributor-default.json /etc/hive/restrictions/

RUN chmod +x /usr/local/bin/contributor-agent.sh /usr/local/bin/contributor-relay.sh \
    /usr/local/bin/agent-launch.sh /usr/local/bin/gh-wrapper
RUN mkdir -p /opt/hive/node_modules && cd /opt/hive && npm install ws 2>/dev/null || true

# Goose config for Lemonade (OpenAI-compatible)
ENV GOOSE_PROVIDER=openai
ENV GOOSE_MODEL=Qwen3.6-35B-GGUF
ENV OPENAI_BASE_URL=https://lemonade.manatee-basking.ts.net/v1
ENV OPENAI_API_KEY=dummy
ENV AGENT_BACKEND=goose
ENV AGENT_MODEL=Qwen3.6-35B-GGUF

RUN useradd -m -s /bin/bash -u 1000 dev
RUN mkdir -p /var/run/hive-metrics /home/dev/.config/goose /home/dev/.config/gh \
  && chown -R dev:dev /var/run/hive-metrics /home/dev/.config

ENV NODE_PATH=/opt/hive/node_modules
USER dev
WORKDIR /home/dev

ENTRYPOINT ["/usr/local/bin/contributor-agent.sh"]
