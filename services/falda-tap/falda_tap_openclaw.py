#!/usr/bin/env python3
"""
FALDA shadow tap — OpenClaw adapter.

Tails an OpenClaw agent's L0 session JSONL shards and mirrors each new
conversation turn to the FALDA gateway (/stream/add). SHADOW ONLY: OpenClaw
remains 100% authoritative and untouched — this only READS its session files
(surfaced to the host via the spark-ai compose bind-mount) and forwards to FALDA
so both systems accumulate the same traffic in parallel.

Why a separate adapter instead of falda's integrations/external-source/
falda_tap.py: that tap assumes each JSONL line is a flat
{sessionKey, role, content}. OpenClaw's format is an event log — many event
types, and message events nest role/content under a "message" object whose
content is either a string (user) or a list of blocks (assistant/tool). This
adapter keeps the proven byte-offset-checkpoint design and adds OpenClaw parsing
plus signal filters.

Filters (decided 2026-07-28):
  - Only type=="message" events with role in {user, assistant}. toolResult is
    dropped — it is ~79% of the byte volume (log dumps, file listings) and is
    operational noise, not memory.
  - Heartbeat turns ("[OpenClaw heartbeat poll]" and their replies) are dropped
    as cron-driven noise.

Design:
  - Per-file byte-offset checkpoint -> survives restarts, never re-sends a line,
    never advances past a partial trailing line.
  - Best-effort: a FALDA outage just means lines wait; offsets only advance on 200.
  - Loops every POLL_SECONDS. Stdlib-only (safe under systemd, no venv).
"""
import json, os, time, urllib.request, urllib.error, glob, sys

# Host path where the OpenClaw gateway's luoji session dir is bind-mounted
# (spark-ai/openclaw/docker-compose.yml). See spark-fabric runlog 2026-07-28.
CONV_DIR = os.environ.get("SOURCE_CONV_DIR", os.path.expanduser("~/.openclaw-sessions/luoji"))
FALDA    = os.environ.get("FALDA_URL", "http://127.0.0.1:8077")
TENANT   = os.environ.get("FALDA_TENANT", "luoji")
STATE    = os.environ.get("TAP_STATE", os.path.expanduser("~/.falda/tap_state_luoji.json"))
LOG      = os.environ.get("TAP_LOG", os.path.expanduser("~/.falda/tap_luoji.log"))
POLL_SECONDS = int(os.environ.get("TAP_POLL", "20"))

HEARTBEAT_MARKERS = ("[OpenClaw heartbeat poll]",)
CAPTURE_ROLES = {"user", "assistant"}


def log(m):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, STATE)


def post(route, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(FALDA + route, data=data,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, r.read()


def falda_up():
    try:
        with urllib.request.urlopen(FALDA + "/healthz", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def flatten_content(content):
    """OpenClaw content is a string (user) or a list of blocks (assistant/tool).
    Return the concatenated text; text lives in {type:'text', text:...} blocks.
    toolCall blocks carry no text and contribute nothing."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        return " ".join(p for p in parts if p).strip()
    return ""


def is_heartbeat(text):
    return any(text.startswith(m) for m in HEARTBEAT_MARKERS)


def session_files(conv_dir):
    """Real session shards only. Exclude trajectory logs, reset archives, the
    empty main.jsonl, and the sessions.json index."""
    out = []
    for p in sorted(glob.glob(os.path.join(conv_dir, "*.jsonl"))):
        base = os.path.basename(p)
        if base.endswith(".trajectory.jsonl"):
            continue
        if base == "main.jsonl":
            continue
        out.append(p)
    return out


def parse_turn(line):
    """Return (role, content) for a capturable turn, or None to skip."""
    try:
        d = json.loads(line)
    except Exception:
        return None
    if d.get("type") != "message":
        return None
    m = d.get("message") or {}
    role = m.get("role", "")
    if role not in CAPTURE_ROLES:
        return None
    text = flatten_content(m.get("content"))
    if not text:
        return None
    if is_heartbeat(text):
        return None
    # Also drop the assistant's canned heartbeat acknowledgement.
    if role == "assistant" and text.strip() == "HEARTBEAT_OK":
        return None
    return role, text


def process_file(path, st):
    """Read new bytes, parse capturable turns, forward to FALDA under one
    session id derived from the shard filename. Offset only advances on 200."""
    off = st.get(path, 0)
    size = os.path.getsize(path)
    if size <= off:
        return 0
    with open(path, "r") as f:
        f.seek(off)
        buf = f.read()
    session_id = "openclaw:" + os.path.basename(path)[:-len(".jsonl")]
    msgs = []
    consumed = off
    for raw in buf.splitlines(keepends=True):
        if not raw.endswith("\n"):
            break  # partial trailing line — leave offset before it
        consumed += len(raw.encode())
        turn = parse_turn(raw.strip())
        if turn:
            msgs.append({"role": turn[0], "content": turn[1]})
    if not msgs:
        st[path] = consumed
        return 0
    try:
        status, _ = post("/stream/add", {"tenant": TENANT, "session_id": session_id, "messages": msgs})
    except urllib.error.URLError as e:
        log(f"WARN FALDA unreachable ({e}); holding offset for {os.path.basename(path)}")
        return 0
    if status != 200:
        log(f"WARN /stream/add status={status} for {os.path.basename(path)}; holding offset")
        return 0
    st[path] = consumed
    return len(msgs)


def main():
    log(f"FALDA OpenClaw tap starting. conv_dir={CONV_DIR} falda={FALDA} tenant={TENANT} poll={POLL_SECONDS}s")
    while True:
        if not falda_up():
            log("FALDA not healthy; waiting")
            time.sleep(POLL_SECONDS)
            continue
        st = load_state()
        total = 0
        for path in session_files(CONV_DIR):
            try:
                total += process_file(path, st)
            except Exception as e:
                log(f"ERR processing {path}: {e}")
        if total:
            save_state(st)
            log(f"mirrored {total} turns to FALDA (tenant={TENANT})")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
