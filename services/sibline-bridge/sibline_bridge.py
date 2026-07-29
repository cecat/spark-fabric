#!/usr/bin/env python3
"""Sibline host-side bridge — one per agent (gandalf, luoji).

Both of Charlie's agents are SANDBOXED and cannot open a raw NATS TCP
connection to the broker: the OpenShell L7 proxy only tunnels TLS/WebSocket on
443, and a spike (2026-07-29) proved a plain NATS stream to 172.19.0.1:4222
never even reaches the socat bridge. So — unlike Rick's native Ollie — the NATS
client runs HERE, on the host, and the message is handed to the agent through a
file mailbox (the sandbox barrier's file-shuttle pattern, same shape as the FALDA
taps and ops/outbox-processor.sh).

This daemon does BOTH legs (Sibline SYMMETRY RULE — same transport both ways):
  INBOUND : durable JetStream consumers on sibline.<self>.inbox + sibline.broadcast
            -> append each non-noise envelope to MAILBOX_PATH (JSONL).
            -> auto-answer kind=ping with kind=pong (no agent wake needed).
  OUTBOUND: watch OUTBOX_DIR for *.json files the agent dropped
            -> write a durable audit copy, then publish to the broker
            -> move the file to OUTBOX_DIR/sent/ (or /failed on error).

Delivery of MAILBOX_PATH into the sandbox differs per agent and is handled
OUTSIDE this daemon (keeps it agent-agnostic):
  - luoji  : MAILBOX_PATH points straight into his live /workspace bind-mount.
  - gandalf: MAILBOX_PATH is a host staging file; a docker-exec shuttle
             (Spark-Hermes) syncs it into /sandbox/.hermes/sibline/.

Env:
  SIBLINE_AGENT        gandalf | luoji   (also the NATS username)
  SIBLINE_SERVER       nats://127.0.0.1:4222
  SIBLINE_CREDS_FILE   file with <AGENT_UPPER>_NATS_PASS=...  (0600)
  SIBLINE_MAILBOX_PATH inbound JSONL sink
  SIBLINE_OUTBOX_DIR   dir the agent drops outbound *.json into
  SIBLINE_LOG_DIR      daemon log dir
"""
from __future__ import annotations

import asyncio
import datetime as _dt
import json
import os
import re
import signal
import time
import uuid
from pathlib import Path

import nats  # from ~/.sibline/venv
from nats.js.api import AckPolicy, Base as _NatsBase, ConsumerConfig, DeliverPolicy

# ----- config -----
AGENT = os.environ.get("SIBLINE_AGENT", "").strip().lower()
if AGENT not in ("gandalf", "luoji"):
    raise SystemExit("SIBLINE_AGENT must be gandalf or luoji")
SERVER = os.environ.get("SIBLINE_SERVER", "nats://127.0.0.1:4222")
CREDS_FILE = Path(os.environ.get("SIBLINE_CREDS_FILE", "~/.config/sibline/cred")).expanduser()
MAILBOX_PATH = Path(os.environ.get("SIBLINE_MAILBOX_PATH", f"~/.sibline/mailbox-{AGENT}.jsonl")).expanduser()
OUTBOX_DIR = Path(os.environ.get("SIBLINE_OUTBOX_DIR", f"~/.sibline/outbox-{AGENT}")).expanduser()
LOG_DIR = Path(os.environ.get("SIBLINE_LOG_DIR", "~/.sibline/logs")).expanduser()
OUTBOX_POLL_S = float(os.environ.get("SIBLINE_OUTBOX_POLL_S", "2"))

INBOX_SUBJECT = f"sibline.{AGENT}.inbox"
OUTBOX_SUBJECT = f"sibline.{AGENT}.outbox"
BROADCAST_SUBJECT = "sibline.broadcast"
INBOX_STREAM = f"sibline-{AGENT}"
BROADCAST_STREAM = "sibline-broadcast"
INBOX_DURABLE = f"{AGENT}-inbox-durable"
BROADCAST_DURABLE = f"{AGENT}-bcast-durable"

# The password key in the cred file, e.g. GANDALF_NATS_PASS / LUOJI_NATS_PASS.
PASS_KEY = f"{AGENT.upper()}_NATS_PASS"

# Kinds that are liveness/plumbing only — acked + logged, never surfaced to the agent.
NATS_ONLY_KINDS = {"smoke", "smoke_ack", "status", "heartbeat", "ping", "pong", "rr_probe"}
PING_KINDS = {"ping", "rr_probe"}
# Valid A2A peers on this box (extend as the mesh grows).
AGENT_NAMES = {"gandalf", "luoji"}

LOG_DIR.mkdir(parents=True, exist_ok=True)
MAILBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
(OUTBOX_DIR / "sent").mkdir(parents=True, exist_ok=True)
(OUTBOX_DIR / "failed").mkdir(parents=True, exist_ok=True)
DAEMON_LOG = LOG_DIR / f"sibline-bridge-{AGENT}.log"

# ----- nats-py timestamp compat (nats-server 2.14 returns N-digit microseconds) -----
_FRAC_RE = re.compile(r"(\.\d+)([Z+\-]|$)")


def _normalize_frac(iso_str: str) -> str:
    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1] + "+00:00"

    def _pad(m: "re.Match[str]") -> str:
        return "." + (m.group(1)[1:] + "000000")[:6] + m.group(2)

    return _FRAC_RE.sub(_pad, iso_str)


def _parse_utc_iso_compat(iso_str: str):
    return _dt.datetime.fromisoformat(_normalize_frac(iso_str)).astimezone(_dt.timezone.utc)


_NatsBase._parse_utc_iso = staticmethod(_parse_utc_iso_compat)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def log(msg: str) -> None:
    line = f"{now_iso()} [{AGENT}] {msg}\n"
    print(line, end="", flush=True)
    with DAEMON_LOG.open("a", encoding="utf-8") as f:
        f.write(line)


def load_password() -> str:
    if CREDS_FILE.exists():
        for line in CREDS_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{PASS_KEY}="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(f"missing {PASS_KEY} in {CREDS_FILE}")


def append_mailbox(record: dict) -> None:
    MAILBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MAILBOX_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


# ----- inbound -----
async def handle_js(msg, nc) -> None:
    subject = msg.subject
    raw = msg.data
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {"raw": raw.decode("utf-8", "replace")}

    ts = now_iso()
    kind = payload.get("kind", "")
    msg_id = payload.get("id", f"sibline-{uuid.uuid4().hex[:12]}")
    log(f"js-recv subject={subject!r} kind={kind!r} id={msg_id!r} size={len(raw)}")

    # Auto-pong (liveness) — answer without waking the agent, then ack.
    if kind in PING_KINDS:
        requester = str(payload.get("from") or "").strip().lower()
        if requester not in AGENT_NAMES:
            requester = next(iter(AGENT_NAMES - {AGENT}))
        pong = {
            "id": f"{AGENT}-pong-{uuid.uuid4().hex[:12]}",
            "from": AGENT, "to": requester, "ts": ts,
            "reply_to": msg_id, "kind": "pong",
            "body": {"req_id": msg_id, "req_ts": payload.get("ts", "")},
        }
        data = json.dumps(pong, separators=(",", ":")).encode()
        await nc.publish(f"sibline.{requester}.inbox", data)
        await nc.publish(OUTBOX_SUBJECT, data)
        await msg.ack()
        log(f"ponged -> sibline.{requester}.inbox req_id={msg_id!r}")
        return

    if kind in NATS_ONLY_KINDS:
        await msg.ack()
        log(f"nats-only kind={kind!r}, not surfaced")
        return

    body = payload.get("body", payload.get("text", f"[nats:{subject}]"))
    record = {
        "ts": ts, "from": payload.get("from", "?"), "via": "sibline",
        "id": msg_id, "subject": subject, "kind": kind or "message",
        "text": body if isinstance(body, str) else json.dumps(body),
        "payload": payload,
    }
    # Ack AFTER the mailbox write returns, so a crash mid-write leaves the
    # message for JetStream to redeliver (no silent loss).
    append_mailbox(record)
    await msg.ack()
    log(f"mailbox appended id={msg_id!r} kind={kind!r}")


# ----- outbound -----
async def drain_outbox(nc) -> None:
    """Publish any *.json the agent dropped in OUTBOX_DIR. SYMMETRY RULE: the
    durable file already exists (the agent wrote it); we publish best-effort,
    then move it to sent/ (or failed/)."""
    for f in sorted(OUTBOX_DIR.glob("*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"outbox bad json {f.name}: {e}; -> failed/")
            f.rename(OUTBOX_DIR / "failed" / f.name)
            continue
        payload.setdefault("id", f"{AGENT}-{uuid.uuid4().hex[:12]}")
        payload.setdefault("from", AGENT)
        payload.setdefault("ts", now_iso())
        to = str(payload.get("to", "")).strip().lower()
        # broadcast if to is empty/"broadcast"/"all", else direct to peer inbox
        if to in ("", "broadcast", "all"):
            subject = BROADCAST_SUBJECT
        else:
            subject = f"sibline.{to}.inbox"
        data = json.dumps(payload, separators=(",", ":")).encode()
        try:
            js = nc.jetstream()
            ack = await js.publish(subject, data)
            log(f"outbox published {f.name} -> {subject} seq={ack.seq}")
            f.rename(OUTBOX_DIR / "sent" / f.name)
        except Exception as e:
            log(f"outbox publish failed {f.name} -> {subject}: {e}; leaving for retry")
            # leave in place; next poll retries (idempotent via dupe-window)
            break


async def run() -> None:
    log(f"starting bridge: server={SERVER} inbox={INBOX_SUBJECT} mailbox={MAILBOX_PATH}")
    stop = asyncio.Event()

    def _sig(sig, _f):
        log(f"signal {sig}, stopping")
        stop.set()

    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)

    attempts = 0
    while not stop.is_set():
        nc = None
        try:
            nc = await nats.connect(
                SERVER, user=AGENT, password=load_password(),
                reconnect_time_wait=2, max_reconnect_attempts=-1,
                ping_interval=20, max_outstanding_pings=3,
                name=f"{AGENT}-sibline-bridge",
            )
            attempts = 0
            log("connected")
            js = nc.jetstream()
            subs = []
            for stream, durable, filt in [
                (INBOX_STREAM, INBOX_DURABLE, INBOX_SUBJECT),
                (BROADCAST_STREAM, BROADCAST_DURABLE, BROADCAST_SUBJECT),
            ]:
                cfg = ConsumerConfig(durable_name=durable, deliver_policy=DeliverPolicy.ALL,
                                     ack_policy=AckPolicy.EXPLICIT, filter_subject=filt)
                sub = await js.subscribe(filt, durable=durable, stream=stream, config=cfg,
                                         cb=lambda m, _nc=nc: asyncio.ensure_future(handle_js(m, _nc)))
                subs.append(sub)
                log(f"js-subscribed stream={stream!r} durable={durable!r} filter={filt!r}")

            # Outbound poller shares this connection.
            while not stop.is_set() and nc.is_connected:
                await drain_outbox(nc)
                await asyncio.sleep(OUTBOX_POLL_S)

            for s in subs:
                try:
                    await s.unsubscribe()
                except Exception:
                    pass
            await nc.drain()
            log("drained")
        except Exception as e:
            attempts += 1
            wait = min(30, 2 ** min(attempts, 5))
            log(f"connection error (attempt {attempts}): {e}; retry in {wait}s")
            await asyncio.sleep(wait)
        finally:
            if nc and not nc.is_closed:
                await nc.close()
    log("stopped")


if __name__ == "__main__":
    asyncio.run(run())
