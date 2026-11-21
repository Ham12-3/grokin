# Local dev "cloud computer" for Crew. One container per user.
# Build: docker build -t crew-computer:dev -f infra/computer/Dockerfile infra/computer
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    DISPLAYS="1 2 3 4 5 6"

RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb x11vnc fluxbox websockify novnc \
      chromium-browser fonts-noto fonts-noto-color-emoji \
      python3 python3-pip python3-venv nodejs npm git curl jq ripgrep ffmpeg \
      ca-certificates sudo tini \
    && rm -rf /var/lib/apt/lists/*
# Note: on Ubuntu 24.04 chromium-browser is a snap shim. If it fails in Docker,
# install Chrome for Testing or Playwright's bundled Chromium instead (preferred):
#   pip install playwright && playwright install --with-deps chromium

RUN useradd -m -s /bin/bash crew
RUN python3 -m venv /opt/control && /opt/control/bin/pip install --no-cache-dir \
      fastapi uvicorn[standard] playwright \
    && /opt/control/bin/playwright install --with-deps chromium

# start.sh: for each display N in $DISPLAYS start
#   Xvfb :N -screen 0 1280x800x24
#   fluxbox (DISPLAY=:N)
#   chromium --user-data-dir=/home/crew/.config/chromium-N --remote-debugging-port=92N ... (DISPLAY=:N)
#   x11vnc -display :N -rfbport 59N -nopw -localhost -forever -shared
#   websockify 60N localhost:59N
# then run the control server (FastAPI) on :7000, checking CONTROL_TOKEN on every request.
COPY start.sh /usr/local/bin/start.sh
COPY control_server.py /opt/control/control_server.py
RUN chmod +x /usr/local/bin/start.sh

USER crew
WORKDIR /workspace
VOLUME ["/workspace", "/home/crew/.config"]
EXPOSE 7000 6001-6006

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/usr/local/bin/start.sh"]
