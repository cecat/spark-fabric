#!/usr/bin/env bash
# spark-fabric stack health — one command to see the whole FUS substrate.
# Covers the shared services (FALDA, embedder, distiller, Sibline broker +
# bridges). Gandalf-agent health lives in Spark-Hermes/ops/status.sh; this is
# the substrate view.
#
# Read-only. Exit 0 if everything green, 1 if any check fails.
set -u

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { printf "${GREEN}[✓]${NC} %s\n" "$*"; }
bad()  { printf "${RED}[✗]${NC} %s\n" "$*"; FAILED=1; }
warn() { printf "${YELLOW}[!]${NC} %s\n" "$*"; }
note() { printf "${CYAN}[i]${NC} %s\n" "$*"; }
FAILED=0

NATS_BIN="$HOME/opt/nats/bin/nats"
CRED="$HOME/.config/sibline/cred"

note "spark-fabric substrate health ($(date -u +%Y-%m-%dT%H:%M:%SZ))"

# ── 1. systemd --user units (active + enabled = running now AND survives reboot)
echo "--- services ---"
UNITS="ollama falda-gateway falda-tap-luoji falda-tap-gandalf falda-distiller-luoji \
sibline-broker sibline-bridge-luoji sibline-bridge-gandalf gandalf-sibline-shuttle \
ump-memory"
for u in $UNITS; do
  a=$(systemctl --user is-active "$u.service" 2>/dev/null)
  e=$(systemctl --user is-enabled "$u.service" 2>/dev/null)
  if [ "$a" = "active" ] && [ "$e" = "enabled" ]; then
    ok "$u (active, enabled)"
  else
    bad "$u (active=$a enabled=$e)"
  fi
done
if loginctl show-user "$USER" 2>/dev/null | grep -q "Linger=yes"; then
  ok "linger enabled (units start at boot without login)"
else
  bad "linger NOT enabled — units will NOT start on reboot (loginctl enable-linger $USER)"
fi

# ── 2. FALDA gateway + embedder
echo "--- FALDA / embedder ---"
HZ=$(curl -s -m 5 http://127.0.0.1:8077/healthz 2>/dev/null)
echo "$HZ" | grep -q '"ok":true' && ok "FALDA healthz ok (:8077)" || bad "FALDA healthz FAILED: ${HZ:-no response}"
EV=$(curl -s -m 5 http://127.0.0.1:11434/api/version 2>/dev/null)
echo "$EV" | grep -q version && ok "embedder ollama ok (:11434) $(echo "$EV" | tr -d '{}\"')" || bad "embedder FAILED"

# per-tenant stream + atom counts (proof capture + distillation are populating)
for t in luoji gandalf; do
  s=$(curl -s -m 5 -X POST http://127.0.0.1:8077/stream/query -H 'content-type: application/json' -d "{\"tenant\":\"$t\",\"limit\":1}" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("total","?"))' 2>/dev/null)
  a=$(curl -s -m 5 -X POST http://127.0.0.1:8077/atoms/query -H 'content-type: application/json' -d "{\"tenant\":\"$t\",\"limit\":1}" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("total","?"))' 2>/dev/null)
  note "tenant=$t: stream=$s atoms=$a"
done

# ── 3. Sibline broker + streams
echo "--- Sibline ---"
if ss -ltn 2>/dev/null | grep -q "127.0.0.1:4222"; then ok "broker listening (:4222 loopback)"; else bad "broker NOT listening on :4222"; fi
if [ -f "$CRED" ] && [ -x "$NATS_BIN" ]; then
  # shellcheck disable=SC1090
  ADMIN_PW=$(grep '^NATS_ADMIN_PASS=' "$CRED" | cut -d= -f2-)
  STREAMS=$("$NATS_BIN" --server "nats://admin:${ADMIN_PW}@127.0.0.1:4222" stream ls -n 2>/dev/null)
  for s in sibline-gandalf sibline-luoji sibline-broadcast; do
    echo "$STREAMS" | grep -qx "$s" && ok "stream $s" || bad "stream $s MISSING"
  done
  # durable consumers single (no reconnect zombies)
  for pair in "sibline-gandalf:gandalf-inbox-durable" "sibline-luoji:luoji-inbox-durable"; do
    st=${pair%%:*}; c=${pair##*:}
    n=$("$NATS_BIN" --server "nats://admin:${ADMIN_PW}@127.0.0.1:4222" consumer ls "$st" 2>/dev/null | grep -c "$c")
    [ "$n" = "1" ] && ok "consumer $c (single)" || warn "consumer $c count=$n (expect 1 — reconnect zombie? see runbook)"
  done
else
  warn "nats CLI or cred file missing — skipping stream checks"
fi

# ── 4. UMP memory server (interchange format)
echo "--- UMP ---"
UMP_PORT=$(grep -s '^UMP_HTTP=' "$HOME/.config/ump/ump.env" | cut -d= -f2 || echo 4100)
UMP_PORT=${UMP_PORT:-4100}
if ss -ltn 2>/dev/null | grep -q "127.0.0.1:${UMP_PORT}"; then
  ok "UMP listening (127.0.0.1:${UMP_PORT} loopback)"
elif ss -ltn 2>/dev/null | grep -qE "(0\.0\.0\.0|\*):${UMP_PORT}"; then
  bad "UMP bound to ALL interfaces on :${UMP_PORT} — should be loopback (check the wrapper)"
else
  bad "UMP NOT listening on :${UMP_PORT}"
fi
WK=$(curl -s -m5 "http://127.0.0.1:${UMP_PORT}/.well-known/ump.json" 2>/dev/null)
if echo "$WK" | grep -q '"conformance"'; then
  OWNER=$(echo "$WK" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("owner",""))' 2>/dev/null)
  ok "UMP well-known ok (conformance L2, owner ${OWNER:0:24}…)"
else
  bad "UMP well-known FAILED"
fi

echo ""
[ "$FAILED" = "0" ] && ok "ALL GREEN" || bad "one or more checks FAILED"
exit "$FAILED"
