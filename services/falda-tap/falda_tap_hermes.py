#!/usr/bin/env python3
"""
FALDA shadow tap — Hermes (Gandalf) adapter.

Mirrors each new Gandalf conversation turn to the FALDA gateway (/stream/add)
under tenant `gandalf`. SHADOW ONLY: Hermes remains 100% authoritative and
untouched — this only READS its canonical message store and forwards to FALDA so
both systems accumulate the same conversational traffic in parallel.

Why this differs from the Luoji (OpenClaw) tap:
  - Luoji's sessions are host-mounted JSONL append logs → byte-offset tail.
  - Gandalf runs in an OpenShell sandbox with NO host bind-mount for its state,
    and its per-session `.jsonl` files exist for only ~1/3 of interactive
    sessions (verified 2026-07-28). The CANONICAL, complete store is the sandbox
    SQLite DB `/sandbox/.hermes/runtime/state.db` (`messages` + `sessions`
    tables, FTS5-indexed). So this tap:
      * crosses the sandbox boundary via `docker exec` (like ops/outbox-processor.sh),
      * reads state.db READ-ONLY (uri mode=ro; the sandbox has no sqlite3 CLI so
        we run stdlib python3 INSIDE the container to emit JSON),
      * checkpoints on the monotonic `messages.id` autoincrement PK.

Filters (decided 2026-07-28, mirrors the Luoji heartbeat/toolResult cuts):
  - Keep sessions whose `source` is a real conversation channel: telegram, slack.
    Drop `cron` (automated inbox-triage: [SILENT], skill preambles — the Gandalf
    analog of Luoji heartbeats; ~96% of message volume) and `api_server`.
  - Keep roles user, assistant. Drop tool / session_meta and empty content.
  - Drop assistant turns whose only content is the triage sentinel "[SILENT]".

Design:
  - Checkpoint = highest forwarded messages.id, stored on the HOST at
    ~/.falda/tap_state_gandalf.json. Advances only on a 200 from /stream/add, so
    a restart or FALDA outage never drops or dupes a turn.
  - Groups a batch by session_id and posts one /stream/add per session, using
    session_id = "hermes:<session_id>" in FALDA.
  - Runs on the HOST → needs no OpenShell egress policy (that gates the in-sandbox
    memory provider in 5c, not this tap). Stdlib-only, safe under systemd.
"""
import json, os, subprocess, time, urllib.request, urllib.error, sys

CONTAINER_PREFIX = os.environ.get("HERMES_CONTAINER_PREFIX", "openshell-gandalf-")
STATE_DB = os.environ.get("HERMES_STATE_DB", "/sandbox/.hermes/runtime/state.db")
FALDA    = os.environ.get("FALDA_URL", "http://127.0.0.1:8077")
TENANT   = os.environ.get("FALDA_TENANT", "gandalf")
STATE    = os.environ.get("TAP_STATE", os.path.expanduser("~/.falda/tap_state_gandalf.json"))
LOG      = os.environ.get("TAP_LOG", os.path.expanduser("~/.falda/tap_gandalf.log"))
POLL_SECONDS = int(os.environ.get("TAP_POLL", "20"))
BATCH    = int(os.environ.get("TAP_BATCH", "500"))
# /stream/add embeds every message inline via the (CPU) Ollama embedder, so a
# large session posted in one shot can exceed a short HTTP timeout on a cold
# embedder. Chunk each session's turns and give the POST real headroom.
CHUNK    = int(os.environ.get("TAP_CHUNK", "25"))
POST_TIMEOUT = int(os.environ.get("TAP_POST_TIMEOUT", "120"))

CAPTURE_SOURCES = {"telegram", "slack"}
CAPTURE_ROLES = {"user", "assistant"}
DROP_EXACT = {"[SILENT]"}


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
    with urllib.request.urlopen(req, timeout=POST_TIMEOUT) as r:
        return r.status, r.read()


def falda_up():
    try:
        with urllib.request.urlopen(FALDA + "/healthz", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def container_name():
    out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                         capture_output=True, text=True, check=True).stdout
    for line in out.splitlines():
        if line.startswith(CONTAINER_PREFIX):
            return line.strip()
    return None


# Reader script run INSIDE the sandbox. Reads state.db read-only and prints one
# JSON object per capturable message as a line (JSONL) to stdout. Keeping the
# filter in SQL keeps the crossing cheap and the host side format-agnostic.
_READER = r'''
import sqlite3, json, sys
db, since, limit = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
q = """
SELECT m.id, m.session_id, s.source, m.role, m.content, m.timestamp
FROM messages m JOIN sessions s ON m.session_id = s.id
WHERE m.id > ?
  AND s.source IN ('telegram','slack')
  AND m.role IN ('user','assistant')
  AND m.content IS NOT NULL AND length(trim(m.content)) > 0
ORDER BY m.id ASC
LIMIT ?
"""
for row in con.execute(q, (since, limit)):
    print(json.dumps({
        "id": row[0], "session_id": row[1], "source": row[2],
        "role": row[3], "content": row[4], "timestamp": row[5],
    }))
'''


def fetch_new(container, since):
    """docker exec the reader in the sandbox; return a list of message dicts."""
    proc = subprocess.run(
        ["docker", "exec", "-u", "sandbox", container,
         "python3", "-c", _READER, STATE_DB, str(since), str(BATCH)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        log(f"WARN reader exit={proc.returncode}: {proc.stderr.strip()[:300]}")
        return []
    rows = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            log(f"WARN unparseable reader line: {line[:120]}")
    return rows


def _post_chunk(session_id, chunk):
    status, _ = post("/stream/add", {
        "tenant": TENANT,
        "session_id": "hermes:" + session_id,
        "messages": chunk,
    })
    return status


def forward(rows, st):
    """Forward rows in strict global id order, one /stream/add per bounded
    same-session chunk. The checkpoint (`last_id`) only advances over ids we've
    fully handled — a message posted (200) or an intentional drop. We STOP on the
    first failure, so processing in id order guarantees we never checkpoint past
    an unposted id (no gaps, no dupes on restart)."""
    committed = st.get("last_id", 0)
    forwarded = 0
    i, n = 0, len(rows)
    while i < n:
        r = rows[i]
        content = (r.get("content") or "").strip()
        if content in DROP_EXACT:
            committed = max(committed, r["id"])   # nothing to post; handled
            i += 1
            continue
        # Gather a chunk of consecutive, same-session, postable rows.
        sid = r["session_id"]
        chunk, last_id = [], committed
        while (i < n and len(chunk) < CHUNK
               and rows[i]["session_id"] == sid
               and (rows[i].get("content") or "").strip() not in DROP_EXACT):
            c = (rows[i].get("content") or "").strip()
            chunk.append({"role": rows[i]["role"], "content": c})
            last_id = rows[i]["id"]
            i += 1
        try:
            status = _post_chunk(sid, chunk)
        except urllib.error.URLError as e:
            log(f"WARN FALDA unreachable ({e}); holding checkpoint at {committed}")
            break
        except Exception as e:
            log(f"WARN /stream/add error ({e}); holding checkpoint at {committed}")
            break
        if status != 200:
            log(f"WARN /stream/add status={status} for {sid}; holding checkpoint at {committed}")
            break
        forwarded += len(chunk)
        committed = last_id

    if committed > st.get("last_id", 0):
        st["last_id"] = committed
    return forwarded


def main():
    log(f"FALDA Hermes tap starting. db={STATE_DB} falda={FALDA} tenant={TENANT} poll={POLL_SECONDS}s")
    while True:
        if not falda_up():
            log("FALDA not healthy; waiting")
            time.sleep(POLL_SECONDS)
            continue
        container = container_name()
        if not container:
            log(f"No running container matching {CONTAINER_PREFIX}*; waiting")
            time.sleep(POLL_SECONDS)
            continue
        st = load_state()
        since = st.get("last_id", 0)
        try:
            rows = fetch_new(container, since)
        except Exception as e:
            log(f"ERR fetch_new: {e}")
            time.sleep(POLL_SECONDS)
            continue
        if rows:
            n = forward(rows, st)
            save_state(st)
            if n:
                log(f"mirrored {n} turns to FALDA (tenant={TENANT}, checkpoint id={st.get('last_id')})")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
