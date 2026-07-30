#!/usr/bin/env python3
"""
FALDA -> UMP mirror (Phase 11).

One-directional sidecar that makes FALDA's *shared* memory portable: it reads
distilled atoms from FALDA's `shared-corpus` pool and writes them as UMP records
under the one shared did:key owner. UMP thus becomes a vendor-neutral, copyable
view of exactly what the agents deliberately shared — the swap-proof layer that
later lets a different memory engine read the same records.

Deliberately scoped (see docs/PLAN-FALDA-SIBLINE.md "Phase 11"):
  - DIRECTION: FALDA -> UMP only. FALDA stays the single source of truth. This
    process only READS FALDA and only WRITES UMP; a UMP-side change never flows
    back. There is no reverse path in this file, by design.
  - SCOPE: the `shared-corpus` pool ONLY. Private tenant memory is never read, so
    it can never leak into the portable store. Private stays private.
  - GRANULARITY: atoms (distilled facts), not raw stream turns. An atom is
    already the shape of a UMP record; raw turns are conversation, not memory.
  - ENRICH: each record gets the fields a FALDA atom lacks so a shared fact is
    auditable to an external reader — `provenance` (actor / actor_kind / method /
    source.ref back to the FALDA atom id) and `scope.visibility = shared`.
  - SINGLE WRITER: this mirror is the ONLY writer into UMP. Agents must not write
    UMP directly via MCP — two live stores with independent writers and no source
    of truth is an un-reconcilable-divergence problem.

Idempotency (two layers, so re-runs never duplicate):
  1. Local state file records every FALDA atom id already mirrored, so we skip
     re-POSTing it. Incremental fetch uses `time_start` = last watermark (with a
     small lookback) against FALDA's `updated_at` ordering.
  2. UMP itself dedups on (body + scope) via findDuplicate -> "merged", so even
     if the state file is lost and everything is re-posted, no duplicate records
     are created. Layer 1 is an optimization; layer 2 is the correctness guard.

Fail-soft: a FALDA or UMP outage just means atoms wait — the watermark and the
seen-id set only advance for atoms whose UMP write returned created/merged. No
exception is allowed to abort a run mid-batch and strand the watermark ahead of
un-mirrored atoms.

Stdlib-only (safe under systemd --user, no venv), mirroring the taps/distiller.

KNOWN LIMITATION (a finding for Rick, recorded in the README): a FALDA atom does
NOT carry which agent authored it, so `provenance.actor_kind` is honestly
"import" and `actor` is the shared owner DID (the principal the mirror runs as) —
we do NOT fabricate a per-atom author we cannot know. If FALDA later records atom
authorship, this mirror can pass it through faithfully.
"""
import json, os, sys, time, urllib.request, urllib.error

FALDA        = os.environ.get("FALDA_URL", "http://127.0.0.1:8077")
# Named pool resolves to one shared SQLite file regardless of tenant, but the
# query API still requires a (valid) tenant param; any tenant that can see the
# pool works. This does NOT scope which memory is read — the POOL does.
TENANT       = os.environ.get("MIRROR_TENANT", "gandalf")
POOL         = os.environ.get("MIRROR_POOL", "shared-corpus")

UMP          = os.environ.get("UMP_URL", "http://127.0.0.1:4100")
OWNER        = os.environ.get("UMP_OWNER")  # REQUIRED: the shared did:key owner
VISIBILITY   = os.environ.get("UMP_VISIBILITY", "shared")
ACTOR_KIND   = os.environ.get("UMP_ACTOR_KIND", "import")
METHOD       = os.environ.get("UMP_METHOD", "falda-shared-corpus-mirror")

STATE        = os.environ.get("MIRROR_STATE", os.path.expanduser("~/.ump/mirror_state.json"))
LOG          = os.environ.get("MIRROR_LOG", os.path.expanduser("~/.ump/mirror.log"))
POLL_SECONDS = int(os.environ.get("MIRROR_POLL_S", "300"))
PAGE_LIMIT   = int(os.environ.get("MIRROR_PAGE_LIMIT", "200"))
# Re-query slightly before the last watermark so an atom written on the same
# second as the previous cutoff can't be skipped. The seen-id set absorbs the
# resulting overlap.
LOOKBACK_S   = int(os.environ.get("MIRROR_LOOKBACK_S", "5"))
HTTP_TIMEOUT = int(os.environ.get("MIRROR_HTTP_TIMEOUT", "15"))

# FALDA atom.type -> UMP kind. Everything distilled is a fact => semantic.
KIND_MAP = {"fact": "semantic"}
DEFAULT_KIND = "semantic"


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
            st = json.load(f)
    except Exception:
        st = {}
    st.setdefault("mirrored_ids", [])
    st.setdefault("watermark", "")  # ISO-8601 of the newest atom mirrored so far
    return st


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, STATE)


def _post(base, route, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(base + route, data=data,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return r.status, r.read()


def falda_up():
    try:
        with urllib.request.urlopen(FALDA + "/healthz", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def ump_up():
    try:
        with urllib.request.urlopen(UMP + "/.well-known/ump.json", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def fetch_atoms(watermark):
    """Fetch shared-corpus atoms updated at/after the watermark (minus lookback),
    paging through until exhausted. Returns a list oldest-first so the watermark
    advances monotonically as we mirror."""
    body = {"tenant": TENANT, "pool": POOL, "limit": PAGE_LIMIT, "offset": 0}
    if watermark:
        body["time_start"] = _lookback(watermark)
    out, offset = [], 0
    while True:
        body["offset"] = offset
        status, raw = _post(FALDA, "/atoms/query", body)
        if status != 200:
            raise RuntimeError(f"/atoms/query status={status}")
        page = json.loads(raw).get("items", [])
        if not page:
            break
        out.extend(page)
        if len(page) < PAGE_LIMIT:
            break
        offset += PAGE_LIMIT
    # FALDA returns newest-first; mirror oldest-first for a clean watermark.
    out.sort(key=lambda a: a.get("updated_at", ""))
    return out


def _lookback(iso):
    """Subtract LOOKBACK_S from an ISO-8601 timestamp. Best-effort: on any parse
    trouble, return the original (correctness still held by the seen-id set)."""
    try:
        from datetime import datetime, timedelta, timezone
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s) - timedelta(seconds=LOOKBACK_S)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
            f"{dt.microsecond // 1000:03d}Z"
    except Exception:
        return iso


def to_record(atom):
    """Shape a FALDA atom into a UMP record, enriched with provenance + scope."""
    kind = KIND_MAP.get(atom.get("type", ""), DEFAULT_KIND)
    structured = {
        "falda_id": atom.get("id"),
        "falda_type": atom.get("type"),
        "falda_created_at": atom.get("created_at"),
        "falda_updated_at": atom.get("updated_at"),
    }
    if atom.get("background"):
        structured["background"] = atom["background"]
    return {
        "kind": kind,
        "body": {"text": atom.get("content", ""), "structured": structured},
        "scope": {"owner": OWNER, "visibility": VISIBILITY},
        "provenance": {
            "actor": OWNER,
            "actor_kind": ACTOR_KIND,
            "method": METHOD,
            "source": {"ref": atom.get("id"), "provider": "falda"},
        },
    }


def mirror_atom(atom):
    """POST one atom to UMP. Returns True if the record is now present
    (created OR merged); False on a rejection or transport error (caller holds
    state so it retries next run)."""
    rec = to_record(atom)
    if not rec["body"]["text"].strip():
        return True  # empty atom: nothing portable, treat as done
    try:
        status, raw = _post(UMP, "/ump/remember", {"record": rec})
    except urllib.error.URLError as e:
        log(f"WARN UMP unreachable ({e}); holding atom {atom.get('id')}")
        return False
    if status != 200:
        log(f"WARN /ump/remember status={status} for atom {atom.get('id')}")
        return False
    try:
        result = json.loads(raw).get("result")
    except Exception:
        result = None
    if result == "rejected":
        log(f"WARN UMP rejected atom {atom.get('id')}: {raw[:200]!r}")
        return False
    return True  # created or merged — both mean the record is present


def run_once():
    if not OWNER:
        log("FATAL UMP_OWNER not set — refusing to run (scope.owner is mandatory)")
        return 0
    if not falda_up():
        log("FALDA not healthy; skipping this pass")
        return 0
    if not ump_up():
        log("UMP not healthy; skipping this pass")
        return 0

    st = load_state()
    seen = set(st["mirrored_ids"])
    try:
        atoms = fetch_atoms(st["watermark"])
    except Exception as e:
        log(f"ERR fetching atoms: {e}")
        return 0

    mirrored = 0
    for atom in atoms:
        aid = atom.get("id")
        if not aid or aid in seen:
            # Still advance the watermark past atoms we've already handled.
            if atom.get("updated_at", "") > st["watermark"]:
                st["watermark"] = atom["updated_at"]
            continue
        if mirror_atom(atom):
            seen.add(aid)
            mirrored += 1
            if atom.get("updated_at", "") > st["watermark"]:
                st["watermark"] = atom["updated_at"]
        # On failure: do NOT advance watermark past this atom, do NOT mark seen —
        # it will be retried next pass. Keep going with the batch.

    st["mirrored_ids"] = sorted(seen)
    save_state(st)
    if mirrored:
        log(f"mirrored {mirrored} atom(s) FALDA {POOL} -> UMP (owner {OWNER[:20]}…)")
    return mirrored


def main():
    once = "--once" in sys.argv
    log(f"FALDA->UMP mirror starting. falda={FALDA} pool={POOL} ump={UMP} "
        f"owner={(OWNER or '')[:20]}… once={once} poll={POLL_SECONDS}s")
    if once:
        run_once()
        return
    while True:
        try:
            run_once()
        except Exception as e:
            log(f"ERR run_once: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
