# infra/computer

The local dev cloud computer: one container per user.

- `Dockerfile`: Ubuntu, Xvfb, Fluxbox, x11vnc, Playwright Chromium, the control server.
- `start.sh`: blocks private networks as root, then drops to the `crew` user.
- `control_server.py`: the only door in (port 7000, token on every request).

Build: `make computer-image`
