# Local dev "cloud computer" for Crew. One container per user.
# Build: docker build -t crew-computer:dev infra/computer
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright

RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11vnc fluxbox \
      fonts-liberation fonts-noto-color-emoji \
      python3 python3-venv nodejs npm git curl jq ripgrep \
      ca-certificates tini iptables util-linux \
    && rm -rf /var/lib/apt/lists/*

# The control server and Playwright's own Chromium (the Ubuntu chromium package is a snap
# shim that does not work in Docker).
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
    && python3 -m venv /opt/control \
    && /opt/control/bin/pip install --no-cache-dir \
         "fastapi>=0.115" "uvicorn[standard]>=0.32" "playwright>=1.49" \
    && /opt/control/bin/playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

# Ubuntu 24.04 ships a default "ubuntu" user with uid 1000; replace it with ours.
RUN (userdel -r ubuntu 2>/dev/null || true) \
    && useradd -m -u 1000 -s /bin/bash crew \
    && mkdir -p /workspace /home/crew/.config \
    && chown -R crew:crew /workspace /home/crew

COPY start.sh /usr/local/bin/start.sh
COPY control_server.py /opt/control/control_server.py
RUN chmod +x /usr/local/bin/start.sh

WORKDIR /workspace
VOLUME ["/workspace", "/home/crew/.config"]
EXPOSE 7000

# start.sh runs as root only long enough to lock down the network, then drops to `crew`.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/start.sh"]
