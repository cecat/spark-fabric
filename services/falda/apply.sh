#!/usr/bin/env bash
# Idempotent bring-up for the FALDA gateway. Safe to re-run.
#
# Assumes ~/code/falda is checked out at the pinned commit (see README). Applies
# the loopback-bind patch (falda has no auth and binds 0.0.0.0 by default),
# builds native deps under the pinned node, renders the env file, and installs
# the --user systemd unit.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FALDA_SRC="${FALDA_SRC:-$HOME/code/falda}"
NODE_BIN="${NODE_BIN:-$HOME/.nvm/versions/node/v22.22.3/bin/node}"
NPM_BIN="${NPM_BIN:-$HOME/.nvm/versions/node/v22.22.3/bin/npm}"
PATCH="$HERE/patches/0001-bind-loopback-by-default.patch"
ENV_OUT="$HOME/.config/falda/falda.env"

echo "==> checking prerequisites"
[ -d "$FALDA_SRC" ] || { echo "FATAL: $FALDA_SRC not found — clone falda at the pinned commit first"; exit 1; }
[ -x "$NODE_BIN" ] || { echo "FATAL: pinned node not found at $NODE_BIN"; exit 1; }
node_major="$("$NODE_BIN" -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge 20 ] || { echo "FATAL: node $node_major < 20 (falda engines requirement)"; exit 1; }

echo "==> applying loopback-bind patch (idempotent)"
cd "$FALDA_SRC"
if git apply --reverse --check "$PATCH" >/dev/null 2>&1; then
  echo "    already applied — skipping"
elif git apply --check "$PATCH" >/dev/null 2>&1; then
  git apply "$PATCH"
  echo "    applied"
else
  echo "FATAL: patch neither applies nor is already applied — falda source drifted from the pin. Review $PATCH"
  exit 1
fi

echo "==> installing deps + rebuilding better-sqlite3 under pinned node (ABI must match ExecStart)"
export PATH="$(dirname "$NODE_BIN"):$PATH"
"$NPM_BIN" ci
"$NPM_BIN" rebuild better-sqlite3
"$NODE_BIN" -e "const D=require('better-sqlite3'); new D(':memory:'); console.log('better-sqlite3 ABI OK');"

echo "==> rendering env -> $ENV_OUT (0600)"
mkdir -p "$(dirname "$ENV_OUT")" "$HOME/.falda/data"
sed "s#REPLACE_ME_HOME#$HOME#g" "$HERE/falda.env.template" > "$ENV_OUT"
chmod 600 "$ENV_OUT"

echo "==> installing --user systemd unit"
mkdir -p "$HOME/.config/systemd/user"
ln -sf "$HERE/falda-gateway.service" "$HOME/.config/systemd/user/falda-gateway.service"
systemctl --user daemon-reload
systemctl --user enable --now falda-gateway.service

echo "==> done. health:"
sleep 2
curl -sS --max-time 5 http://127.0.0.1:8077/healthz || { echo; echo "WARN: healthz not responding yet — check: journalctl --user -u falda-gateway or ~/.falda/gateway.log"; }
echo
