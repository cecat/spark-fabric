#!/usr/bin/env bash
# Provision the three Sibline JetStream streams for spark-960b.
# Adapted from Sibline/broker/provision-streams.sh (pin cab044f): our agent names
# (gandalf, luoji) instead of Rick's (kukla, ollie).
#
# Idempotent: skips a stream that already exists.
#
# Admin creds come from the environment; source them from the 0600 cred file:
#   set -a; . ~/.config/sibline/cred; set +a
#   NATS_USER=admin NATS_PASSWORD="$NATS_ADMIN_PASS" \
#     NATS_SERVER=nats://127.0.0.1:4222 bash services/nats/provision-streams.sh
set -euo pipefail

NATS_BIN="${NATS_BIN:-$HOME/opt/nats/bin/nats}"
SERVER="${NATS_SERVER:-nats://127.0.0.1:4222}"
USER="${NATS_USER:-admin}"
PASSWORD="${NATS_PASSWORD:?set NATS_PASSWORD (admin) — source ~/.config/sibline/cred}"

ARGS=(--server "$SERVER" --user "$USER" --password "$PASSWORD")

command -v "$NATS_BIN" >/dev/null 2>&1 || { echo "nats CLI not found at $NATS_BIN" >&2; exit 127; }

ensure_stream() {
  local name="$1" subject="$2"
  if "$NATS_BIN" "${ARGS[@]}" stream info "$name" >/dev/null 2>&1; then
    echo "✓ stream exists: $name"
    return 0
  fi
  echo "→ creating stream $name ($subject)"
  "$NATS_BIN" "${ARGS[@]}" stream add "$name" \
    --subjects "$subject" \
    --storage file \
    --retention limits \
    --discard old \
    --max-age 7d \
    --max-msgs 10000 \
    --max-msg-size 1048576 \
    --dupe-window 2m \
    --ack \
    --defaults
}

ensure_stream sibline-gandalf   'sibline.gandalf.>'
ensure_stream sibline-luoji     'sibline.luoji.>'
ensure_stream sibline-broadcast 'sibline.broadcast'
echo 'OK — Sibline streams provisioned.'
