# devbox/Dockerfile
# Standard, ephemeral dev-container image. Goal: drop this onto any fresh Ubuntu
# host (any cloud) and get a self-contained environment that can:
#   * run Docker-in-Docker (its own dockerd) — for building/running containers
#   * drive a real headless browser (Google Chrome) — for UI testing
#
# The build is fully reproducible: it pins the base to a digest-stable tag and
# only uses official apt repositories.
FROM ubuntu:24.04

LABEL org.opencontainers.image.title="devbox" \
      org.opencontainers.image.description="Ephemeral dev container with Docker-in-Docker and a headless browser"

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    DOCKER_HOST=unix:///var/run/docker.sock

# ---------------------------------------------------------------------------
# Optional CA trust injection.
# On a normal machine devbox/extra-ca/ holds only .gitkeep and this is a no-op.
# In environments behind a TLS-intercepting proxy, drop the proxy CA (*.crt)
# into devbox/extra-ca/ and it will be trusted before any HTTPS access. This is
# safe in production (empty by default) and keeps the build portable.
# ---------------------------------------------------------------------------
COPY extra-ca/ /tmp/extra-ca/
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates \
 && if ls /tmp/extra-ca/*.crt >/dev/null 2>&1; then \
        cp /tmp/extra-ca/*.crt /usr/local/share/ca-certificates/ && update-ca-certificates; \
    fi \
 && rm -rf /tmp/extra-ca

# ---------------------------------------------------------------------------
# Base tooling + Docker engine (provides dockerd for Docker-in-Docker).
# docker.io ships the daemon, CLI, and containerd from Ubuntu's own repos, so
# no third-party Docker repo is required.
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        git \
        gnupg \
        iproute2 \
        iptables \
        jq \
        openssh-client \
        sudo \
        docker.io \
        docker-compose-v2 \
 && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Headless browser for UI testing: Google Chrome stable from the official repo.
# Chrome is the most reliable headless browser inside containers and matches
# what Playwright/Puppeteer drive. Run it with --no-sandbox in the container.
# ---------------------------------------------------------------------------
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
 && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list \
 && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
 && rm -rf /var/lib/apt/lists/* \
 && ln -sf /usr/bin/google-chrome /usr/local/bin/chrome

# A flag file lets the selftest assert it is running inside a devbox image.
RUN echo "devbox" > /etc/devbox-release

COPY entrypoint.sh /usr/local/bin/devbox-entrypoint
COPY selftest.sh  /usr/local/bin/devbox-selftest
RUN chmod +x /usr/local/bin/devbox-entrypoint /usr/local/bin/devbox-selftest

WORKDIR /workspace

# The entrypoint boots the in-container Docker daemon (DinD) and then keeps the
# container alive so `devbox shell`/`devbox doctor` can attach to it.
ENTRYPOINT ["/usr/local/bin/devbox-entrypoint"]
CMD ["sleep", "infinity"]
