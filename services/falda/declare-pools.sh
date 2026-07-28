#!/usr/bin/env bash
# Declare FALDA tenants + the shared pool (Phase 3). Idempotent: re-declaring an
# existing pool with the same roster is a no-op update.
#
# Tenants are implicit — a (tenant, self) store is created on first write, so
# there is nothing to "create" for gandalf/luoji beyond using them. Only the
# shared pool needs an explicit declaration.
set -euo pipefail

FALDA_URL="${FALDA_URL:-http://127.0.0.1:8077}"

MEMBERS='{"gandalf": "readwrite", "luoji": "readwrite"}'
DESC="facts both of Charlie's agents contribute to and read"

echo "==> ensuring pool: shared-corpus $MEMBERS"
# declare-or-update: /pools/declare errors 'exists' on re-run, so fall back to
# /pools/update to make this script safely idempotent.
resp="$(curl -sS -X POST "$FALDA_URL/pools/declare" -H 'Content-Type: application/json' \
  -d "{\"name\":\"shared-corpus\",\"members\":$MEMBERS,\"description\":\"$DESC\"}")"
if echo "$resp" | grep -q '"code":"exists"'; then
  echo "    already declared — reconciling roster via /pools/update"
  curl -sS -X POST "$FALDA_URL/pools/update" -H 'Content-Type: application/json' \
    -d "{\"name\":\"shared-corpus\",\"members\":$MEMBERS,\"description\":\"$DESC\"}"
  echo
else
  echo "$resp"
fi

echo "==> current pools:"
curl -sS -X POST "$FALDA_URL/pools/list" -H 'Content-Type: application/json' -d '{}'
echo
