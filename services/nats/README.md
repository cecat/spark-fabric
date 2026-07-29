# Sibline broker (NATS + JetStream) — Phase 7

The background agent-to-agent side channel. NATS with JetStream, **loopback-only**
(`127.0.0.1:4222`, monitoring `127.0.0.1:8222`), three users (`admin`, `gandalf`,
`luoji`), three file-backed streams. Nothing is exposed off-box.

This is shared substrate (both agents use it) → it lives here in `spark-fabric`.
The **Gandalf-specific file bridge** (Phase 8b) is a sandbox workaround and lives
in `Spark-Hermes`, not here.

## Pins

- **nats-server** v2.14.3 (linux-arm64), sha256 of tarball
  `1759b6a0ddebade9471b7c02891dfaa8c73b526c6f3ce391d4e21ec3eceffab8`;
  binary sha256 `808894204e213aad2b1870a071a4953035b3d0e25531c4a771626c18421961a6`.
- **natscli** v0.4.0 (linux-arm64), tarball(zip) sha256
  `9ce0c8a6653cd697d0b32687fcb53b59c13a2ad7a6ade7af8ad8a1c0f7357a87`;
  binary sha256 `d280d7094ad7ea1e2cc2e1e8f0b9c60ab845ba1c4bcbed7ccf68fcf2d4de080d`.
- Binaries at `~/opt/nats/bin/{nats-server,nats}` (no root; `--user` service).
- **Sibline** checkout `~/code/Sibline` pin **`cab044f`** — un-vendored reference
  (config/scripts adapted here). `nats-py` for smoke/subscribers in `~/.sibline/venv`.

## Adapted from Rick's reference (Sibline pin cab044f), deliberate deltas

| Rick's reference | Here | Why |
|---|---|---|
| tailnet bind (`YOUR_PRIVATE_IP:4222`) | loopback `127.0.0.1:4222` | plan scopes Sibline local-only for now; nothing off-box |
| users `kukla`, `ollie` | `gandalf`, `luoji` | our agents |
| streams `sibline-kukla/ollie` | `sibline-gandalf/luoji` (+`-broadcast`) | our agents |
| root system unit, `/var/lib/sibline`, `useradd sibline` | `--user` unit, `~/.sibline/`, no root | matches the other 5 spark-fabric services; no sudo |
| passwords inline (REPLACE_ME) | `$VAR` from `~/.config/sibline/cred` | committed config has NO secrets |

## Files here

- `nats-server.conf` — broker config. **No secrets, no machine paths**: every
  runtime value is a `$VAR` (nats-server expands env in strings/paths/passwords).
  Committed as-is.
- `sibline-broker.service` — `--user` unit. Injects secrets via
  `EnvironmentFile=~/.config/sibline/cred` and paths via `Environment=`.
- `provision-streams.sh` — idempotent stream creation (gandalf/luoji/broadcast),
  admin creds from env.

## Secrets

`~/.config/sibline/cred` (0600, **never** committed) holds
`NATS_ADMIN_PASS`, `GANDALF_NATS_PASS`, `LUOJI_NATS_PASS` (32-char random each).

## Two gotchas (both handled — do not regress)

- **The `$JS.>` grant is LOAD-BEARING.** Each agent user has `publish` on
  `sibline.>`, `_INBOX.>`, **and `$JS.>`**. Without `$JS.>`, JetStream
  consumer/ack ops fail "permission denied" — and the error misleadingly points
  at *subscribe* while the missing grant is on the *ack-publish* path. Verified
  green by smoke.py (publish + stream_info both succeed).
- **Reconnect zombies (Phase 8 concern, noted here).** py-nats durable
  subscribers do NOT survive the broker's TCP reconnect — they enter
  "consumer exists, no active interest" and silently stop delivering. After ANY
  broker ACL/config change: `systemctl --user restart sibline-broker` (or
  `kill -HUP` the nats-server), **then restart every subscriber unit**. Bake this
  into the Phase 8 runbook.

## Operate

```bash
# status / streams (admin)
set -a; . ~/.config/sibline/cred; set +a
~/opt/nats/bin/nats --server nats://admin:$NATS_ADMIN_PASS@127.0.0.1:4222 stream ls

# (re)provision streams — idempotent
NATS_USER=admin NATS_PASSWORD="$NATS_ADMIN_PASS" bash services/nats/provision-streams.sh

# smoke a given agent (needs ~/.sibline/venv with nats-py)
tmp=$(mktemp); echo "SIBLING_NATS_PASS=$GANDALF_NATS_PASS" >"$tmp"
SIBLINE_AGENT=gandalf SIBLINE_SERVER=nats://127.0.0.1:4222 SIBLINE_CREDS_FILE="$tmp" \
  ~/.sibline/venv/bin/python ~/code/Sibline/scripts/smoke.py; rm -f "$tmp"
```

## Sandbox cannot reach the broker — by design (VERIFY 7, confirmed)

Raw NATS `:4222` is unreachable from the Gandalf sandbox — proven, not assumed:
- `host.openshell.internal:4222` → Connection refused (no socat bridge; unlike
  FALDA's 5a bridge, NATS deliberately has none).
- `127.0.0.1:4222` from the sandbox → Connection refused (sandbox loopback ≠ host).
- Faithful principal path (`nemohermes gandalf exec … curl …:4222`) → **403**
  (no egress policy for 4222).

This is why Gandalf uses a host-side **file bridge** (Phase 8b), not direct NATS.
Luoji is native and speaks NATS directly (Phase 8a).
