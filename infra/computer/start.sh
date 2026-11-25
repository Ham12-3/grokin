#!/usr/bin/env bash
# Entry point for the Crew computer.
#
# 1. As root: block outgoing traffic to private networks and the cloud metadata address,
#    so a Bot (or a web page steering it) cannot reach the host or other machines.
# 2. Drop to the unprivileged `crew` user for good.
# 3. Run the control server, which starts screens and browsers on demand.
set -euo pipefail

: "${CONTROL_TOKEN:?CONTROL_TOKEN is required}"

if [ "$(id -u)" = "0" ]; then
  block_private_networks() {
    iptables -F OUTPUT
    iptables -A OUTPUT -o lo -j ACCEPT
    # Replies to connections that came in (the API talking to the control server).
    iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    # Name lookups only, and only to the resolvers Docker configured (they can sit in a
    # private range, so they are allowed before the blocks below).
    for resolver in $(awk '/^nameserver/ && $2 !~ /:/ {print $2}' /etc/resolv.conf); do
      iptables -A OUTPUT -d "$resolver" -p udp --dport 53 -j ACCEPT
      iptables -A OUTPUT -d "$resolver" -p tcp --dport 53 -j ACCEPT
    done
    for range in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10; do
      iptables -A OUTPUT -d "$range" -j REJECT
    done
    ip6tables -F OUTPUT 2>/dev/null || true
    ip6tables -A OUTPUT -o lo -j ACCEPT 2>/dev/null || true
    ip6tables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
    for range in fc00::/7 fe80::/10; do
      ip6tables -A OUTPUT -d "$range" -j REJECT 2>/dev/null || true
    done
  }

  if ! block_private_networks; then
    if [ "${ALLOW_OPEN_NETWORK:-0}" != "1" ]; then
      echo "crew-computer: could not set the network rules; refusing to start." >&2
      echo "crew-computer: (set ALLOW_OPEN_NETWORK=1 to start without them, dev only)" >&2
      exit 1
    fi
    echo "crew-computer: WARNING: running WITHOUT network rules" >&2
  fi

  # The volumes may be new and owned by root.
  chown crew:crew /workspace /home/crew/.config
  mkdir -p /workspace/outputs /workspace/inbox
  chown crew:crew /workspace/outputs /workspace/inbox

  # No capabilities survive this: `crew` cannot change the rules above.
  exec setpriv --reuid=crew --regid=crew --init-groups --inh-caps=-all --bounding-set=-all \
    env HOME=/home/crew USER=crew "$0"
fi

cd /workspace
exec /opt/control/bin/python /opt/control/control_server.py
