# Sibline bridge — host-side NATS clients for the sandboxed agents (Phase 8)

Both agents (gandalf, luoji) are **sandboxed** and cannot open a raw NATS
connection to the broker. So the NATS client runs **on the host**, one bridge
daemon per agent, and messages cross the sandbox boundary through a **file
mailbox** — the same file-shuttle pattern as the FALDA taps and
`Spark-Hermes/ops/outbox-processor.sh`.

## Why not let the agents speak NATS directly? (spike, 2026-07-29)

The plan and CLAUDE.md assumed only Gandalf needed a bridge ("Luoji speaks NATS
directly"). Both premises turned out false:

- **Luoji is sandboxed too** (same finding as Phase 0). His sandbox can't reach
  `127.0.0.1:4222` either.
- We spiked the Slack-style "persistent outbound through the L7 proxy" idea:
  socat bridge on `172.19.0.1:4222` + an `access: full` / `tls: skip` L4-tunnel
  egress policy (the shape brew/github use). **It failed** — verbose socat showed
  the raw NATS SYN never even arrived. The OpenShell proxy only tunnels TLS/
  WebSocket on 443; Slack Socket Mode works because it's WebSocket-over-TLS,
  NATS is plain TCP on 4222. So the plan's original "raw TCP can't cross the
  sandbox proxy" is **confirmed**. Spike fully torn down; FALDA (5c) egress
  unaffected.

Net: both agents get a host-side bridge. They differ only in the last hop.

## Architecture

```
                 host                                    sandbox
  broker :4222 ── sibline_bridge.py (per agent) ── file mailbox ── agent reads
       │              (NATS client, host)              │
       │         inbound: durable JS consume  ─────────┘ (delivery hop, per agent)
       └──────── outbound: watch outbox dir  ◄───────── agent drops *.json
```

- **`sibline_bridge.py`** (generic, agent-agnostic): durable JetStream consumers
  on `sibline.<self>.inbox` + `sibline.broadcast`; appends non-noise envelopes to
  `SIBLINE_MAILBOX_PATH`; auto-answers `kind=ping` with `pong` (no agent wake);
  watches `SIBLINE_OUTBOX_DIR` for `*.json` the agent drops and publishes them
  (SYMMETRY RULE — the durable file exists first, then best-effort publish, then
  move to `sent/`). Includes the nats-py N-digit-microsecond timestamp shim.

### Per-agent delivery (the only difference)

| | Luoji | Gandalf |
|---|---|---|
| sandbox surface | `/workspace` is a **live host bind-mount** | `/sandbox/.hermes` is **overlay, no bind** |
| mailbox path | written straight into `~/code/spark-ai-agents/luoji/sibline/` → sandbox sees it at `/workspace/sibline/` instantly | bridge stages to `~/.sibline/mailbox-gandalf.jsonl`; a **docker-exec shuttle** (`Spark-Hermes/ops/sibline-shuttle.sh`) syncs it into `/sandbox/.hermes/sibline/` |
| outbox | agent writes `/workspace/sibline/outbox/*.json`; bridge reads directly | agent writes `/sandbox/.hermes/sibline/outbox/*.json`; shuttle pulls to `~/.sibline/outbox-gandalf/`; bridge publishes |
| extra unit | none | `gandalf-sibline-shuttle.service` (Spark-Hermes) |

## Files

- `sibline_bridge.py` — the daemon (shared substrate).
- `sibline-bridge-luoji.service` — `--user` unit, mailbox → Luoji workspace bind.
- `sibline-bridge-gandalf.service` — `--user` unit, mailbox → host staging.
- Gandalf's shuttle lives in **Spark-Hermes** (`ops/sibline-shuttle.sh` +
  `bringup/45-falda-bridge/gandalf-sibline-shuttle.service`) — it's a
  Gandalf-specific docker-exec crossing, like `outbox-processor.sh`.

Secrets: `~/.config/sibline/cred` (0600) — `GANDALF_NATS_PASS`, `LUOJI_NATS_PASS`.
Delivery latency: real-time on the NATS leg; the file/shuttle hop adds one poll
interval (2–3s). Auto-pong is instant (host daemon answers without the agent).

## Boundary note

The generic bridge lives here in spark-fabric (shared substrate, both agents use
it) — following the `falda-tap` precedent where both agents' feeders sit together.
This deviates from CLAUDE.md's "file bridge is Gandalf-specific" line, which was
written believing Luoji spoke NATS directly. Only the Gandalf docker-exec
**shuttle** is agent-specific and stays in Spark-Hermes.

## RUNBOOK — reconnect zombies (do not skip after broker changes)

py-nats durable subscribers do **not** survive the broker's TCP reconnect: they
enter a "consumer exists, no active interest" state where messages queue but
never deliver. After **any** broker ACL/config change (editing
`services/nats/nats-server.conf`, re-provisioning, restarting the broker):

```bash
systemctl --user restart sibline-broker            # if the broker changed
systemctl --user restart sibline-bridge-luoji sibline-bridge-gandalf gandalf-sibline-shuttle
```

Verify no zombie duplication afterward:
```bash
set -a; . ~/.config/sibline/cred; set +a
~/opt/nats/bin/nats --server nats://admin:$NATS_ADMIN_PASS@127.0.0.1:4222 consumer ls sibline-gandalf
# expect exactly one gandalf-inbox-durable
```

## Verify (VERIFY 8, all green 2026-07-29)

1. Publish a `kind=message` to `sibline.gandalf.inbox` → lands in
   `/sandbox/.hermes/sibline/inbox.jsonl` (broker→bridge→shuttle).
2. From inside the Gandalf sandbox, drop `outbox/x.json` addressed to luoji →
   arrives in Luoji's `/workspace/sibline/inbox.jsonl` (shuttle→broker→bridge).
3. Ping each agent → the peer's bridge auto-pongs with the right `reply_to`.
Restart-safe: bouncing all three units keeps a single durable consumer each.
