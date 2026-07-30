# RUNLOG 2026-07-28 — spark-fabric bring-up (Phase 0)

**Operator:** catlett
**Driver:** Claude Code (Opus) on the Spark (`spark-960b`)
**Outcome:** Phase 0 (discovery + repo scaffolding) complete. VERIFY 0 green.
One plan assumption overturned before it could cost anything: **Luoji is
sandboxed, not native.** Reported below; recommend an operator decision before
Phase 4. No services installed. Nothing restarted.

---

## What this phase was

Establish facts about the box, lay down the `spark-fabric` skeleton, and put a
Related repos table in all four repos. No services yet. Read-only discovery
except for repo scaffolding and README edits.

---

## Inventory (Phase 0c)

### Interpreters and toolchain

| Thing | Value | Notes |
|---|---|---|
| node (default, nvm) | **v22.22.3** | `/home/catlett/.nvm/versions/node/v22.22.3/bin/node` |
| node (`/usr/bin/node`, `/bin/node`) | **v18.19.1** | system node — **different major** |
| npm | 10.9.8 | |
| python3 | **3.12.3** | `/usr/bin/python3.12` — only 3.12 present, no 3.11 |
| docker | 29.2.1 | |
| systemd | 255 | user units in use already |

**better-sqlite3 ABI note (Phase 2):** two node majors are on PATH. v22 (nvm)
is the interactive default; v18 is `/usr/bin/node`. The FALDA gateway's systemd
`ExecStart` must pin **one** absolute node path, and `npm ci` / `npm rebuild`
must run under that same binary, or `ERR_DLOPEN_FAILED`. Decision deferred to
Phase 2, but the hazard is real here because the two majors diverge.

**Python note (Phase 8):** plan calls for **3.11+** for the Sibline subscriber
(`datetime.fromisoformat()` with N-digit microseconds). We have **3.12.3**,
which satisfies "3.11+". No separate 3.11 needed. The dedicated venv
(`~/.sibline/venv`) will be built on 3.12.

### GPU / memory

- GPU: **NVIDIA GB10** (DGX Spark), driver 580.142, CUDA 13.0. `nvidia-smi`
  per-process memory shows `Not Supported` for total/used via the CSV query
  (unified-memory arch — the `--query-gpu=memory.total` returns N/A on GB10),
  but `nvidia-smi` itself works and shows vLLM's `EngineCore` resident. This is
  cosmetic for our purposes: the embedder (`nomic-embed-text`) runs on CPU.
- Host RAM: **121 GB total, ~10 GB available** at inventory time (111 GB in
  use — vLLM + containers). Swap 15 GB, unused. Embedder needs ~275 MB; fine.

### Ports (must be free)

`8077` (falda), `4222` (nats), `11434` (ollama), `8222` (nats monitoring):
**all free.** ✓

Already in use and relevant:
- `127.0.0.1:4000` — **LiteLLM** (`gandalf-litellm.service`, PID 2507, up 3
  weeks). This is the distiller's route in Phase 6.
- `127.0.0.1:44497` — **argo-shim** (plus socat mirrors on the docker bridges).
- `127.0.0.1:8642` — Gandalf inference SSH tunnel.

### Containers

```
openclaw-sbx-agent-luoji-b88d9626    Up 4 days     ← Luoji (SANDBOXED — see surprise #1)
openclaw-sbx-agent-cecat-f7952fcc    Up 4 days
openclaw-gateway                     Up 39 h (healthy)
openshell-gandalf-354307c9-...       Up 2 weeks    ← Gandalf sandbox
vllm-qwen3-coder-next                Up 3 weeks    ← shared, DO NOT restart
```

Gandalf sandbox container name (used throughout later phases):
**`openshell-gandalf-354307c9-7df4-47a5-9b86-f6ae0a81ae9e`**

### LiteLLM (Phase 6 route)

- Service: `gandalf-litellm.service` (`--user`, enabled, active 3 weeks).
- **Port 4000.** Route confirmed present:
  `litellm :4000 → argo-shim :44497 → Argo → Opus`.
- Model name to use: `claudeopus47` (per plan; explicit, not the `hermes-agent`
  alias). Not re-verified against `litellm/config.yaml` yet — will confirm in
  Phase 6 before wiring the distiller.

### UMP (Phase 10)

- `@universalmemoryprotocol/core` npm version: **0.2.0** (public, MIT). ✓
- **Port collision flagged:** plan's Phase 10 suggests `ump memory --http 4000`,
  but **4000 is already LiteLLM.** UMP will need a different port. Deferred to
  Phase 10; recording now so it isn't a surprise then.

### Service checkouts

- `~/code/falda` — **present**, at commit `c9f14bc` ("fix(falda): HTTP 500 on
  embedding writes — Buffer-encode vectors for sqlite-vec bind…"). Has the docs
  the plan references (`API.md`, `POOLS.md`, `HARNESS_INTEGRATION.md`,
  `INSTALL.md`, `SCALE.md`) and both scripts (`integrations/external-source/
  falda_tap.py`, `falda_distiller.py`).
- `~/code/Sibline` — **not cloned yet** (Phase 7 will clone).
- `~/code/falda-demo` — not cloned (optional reference).

---

## Surprises / assumptions checked

### Surprise #1 (IMPORTANT) — Luoji is sandboxed, not native

**The plan's premise for Phase 4 is wrong.** The plan says: *"Luoji is native,
unsandboxed, and therefore the clean place to prove the FALDA capture pattern"*
and directs the tap at *"Luoji's L0 session JSONL"* via a host path
`SOURCE_CONV_DIR`.

What the box actually shows:

- Luoji runs in container **`openclaw-sbx-agent-luoji-b88d9626`** ("sbx" =
  sandbox). `spark-ai-agents/README.md` itself states: *"Agents are sandboxed in
  ephemeral Docker containers with no host access beyond explicitly mounted
  paths."*
- `~/.openclaw/` **does not exist.** OpenClaw config/state lives in a Docker
  volume `openclaw_openclaw-config`, mounted at `/home/node/.openclaw` inside
  the `openclaw-gateway` container.
- Luoji's **session logs** are at
  `/home/node/.openclaw/agents/luoji/sessions/*.jsonl` **inside the gateway
  container** — reachable only via `docker exec`, not a host path.
- Luoji's *workspace* (`~/code/spark-ai-agents/luoji`) **is** bind-mounted into
  the container at `/workspace`, but it holds his `SOUL.md`/`MEMORY.md`/etc.,
  **not** the session JSONL.

**How this was caught:** followed the method from the plan's "Corrections"
section — checked the actual artifact instead of the plan's wording.
`docker ps` → `docker inspect` mounts → `docker exec ls` of the config volume.
The session JSONL is real and current (`agents/luoji/sessions/`, files written
today), but it is *in the container*.

**Consequence for Phase 4:** the "native, no sandbox complications" rationale
for doing Luoji first evaporates. Both agents' session logs are inside
containers. Phase 4's tap can't just point `SOURCE_CONV_DIR` at a host path;
it needs the same host↔container access decision the plan reserved for Phase 5b
(host path if a volume exposes it, else a `docker exec` poller). **Stopping to
report before Phase 4 rather than routing around it**, per ground rule 1.

Also note: OpenClaw's session format is **not** the shape `falda_tap.py`
assumes. Sampled keys per line: `['cwd','id','timestamp','type','version']`
then `['id','modelId','parentId','provider','timestamp','type']` — an
event-log/trajectory format, not simple `{role, content}` turns. The tap will
need a format adapter. (Phase 4 detail; recording now.)

### Surprise #2 — two node majors on PATH

Covered above. v22 (nvm) default vs v18 (`/usr/bin/node`). Matters for the
`better-sqlite3` native ABI in Phase 2. Not a blocker; just must be pinned
deliberately, not left to `PATH`.

### Surprise #3 — port 4000 double-booked (future)

LiteLLM already owns 4000; the plan's Phase 10 UMP example also wants 4000.
Not a Phase 0 problem. UMP will get a different port when we get there.

### Confirmed as expected

- All target ports free. ✓
- UMP is public on npm at 0.2.0. ✓ (matches the plan's own Correction #1)
- `~/code/falda` present with the referenced docs and scripts. ✓
- LiteLLM→argo-shim→Argo route exists and is running. ✓

---

## What was decided

- **Deferred, not decided:** the FALDA gateway's node binary (Phase 2) — will
  pin the exact path there after deciding which major FALDA's `better-sqlite3`
  builds cleanest against.
- **Held for operator (blocks Phase 4):** how to treat Luoji given he's
  sandboxed. Options — (a) `docker exec` byte-offset poller against
  `/home/node/.openclaw/agents/luoji/sessions/`, modeled on the same
  host↔container pattern the plan already uses for Gandalf; (b) reconsider
  ordering, since the "Luoji is the simple native case" premise no longer holds.
  Recommend (a) — it keeps the plan's Luoji-before-Gandalf ordering and still
  proves the capture pattern, just via the volume rather than a host path.

---

## VERIFY 0

| Check | Result |
|---|---|
| All four repos have a Related repos table | ✓ (`spark-fabric` already had it; added to `Spark-Hermes`, `spark-ai`, `spark-ai-agents`) |
| `spark-fabric` skeleton committed, holds the plan | ✓ skeleton created (`services/{falda,embedder,distiller,nats,ump}`, `ops/`, `runlog/`); plan at `docs/PLAN-FALDA-SIBLINE.md`; commit pending |
| Runlog records every required inventory item | ✓ this file |
| Ports 8077 / 4222 / 11434 free | ✓ (also 8222) |
| `python3.11+` exists | ✓ 3.12.3 |

**Phase 0 gate: GREEN**, with one reported item (Luoji sandboxing) recommended
for an operator decision before Phase 4 begins.

---

## Files touched

- `spark-fabric/`: created `services/{falda,embedder,distiller,nats,ump}/`,
  `ops/`, `runlog/` (`.gitkeep` placeholders); this runlog. (commit pending)
- `Spark-Hermes/README.md`, `spark-ai/README.md`,
  `spark-ai-agents/README.md`: added Related repos table (each in its own repo;
  commit is the operator's call per repo).

## Not done / next

- Phase 1 (embedder) not started — awaiting operator ack of this report and the
  Luoji-sandboxing decision, per ground rule "report before installing."

---

## Addendum — Luoji session-capture prep (Option B) + upgrade eval

Following the Phase 0 finding that Luoji is sandboxed and his session logs live
in a Docker named volume (not a host path), the operator chose to surface those
logs to the host via a docker-compose bind mount ("Option B") so the Phase 4
FALDA tap can read them as plain files. Done on **2026-07-28**.

### Upgrade evaluation (concluded: stay on 6.11)

Operator asked whether to also upgrade OpenClaw to latest while touching the
gateway. Evaluated per the plan's "check the actual artifact" method:

- **Already on the deliberately-pinned latest-stable.** Running
  `2026.6.11`; `spark-ai/CHANGELOG.md` shows it was pinned 2026-07-10
  specifically to stop `:latest` auto-upgrades that had crash-looped the box.
- Available targets: `extended-stable 2026.6.33` (same 6.x line),
  `latest 2026.7.1-2` (**7.x major** — the real breaking-change delta),
  `beta 2026.7.2-beta.5`.
- `spark-ai/UPGRADE-2026.6.8.md` is the *historical* 4.2→6.11 upgrade analysis,
  already executed — not a pending action.
- **Decision (operator): stay on 6.11**, don't get sidetracked into a 7.x major
  during fabric bring-up. `gh` CLI not installed (was only needed to source 7.x
  release notes; moot now).

### Option B — what was done

- Host dir chosen: **`~/.openclaw-sessions/luoji`** (runtime state in `$HOME`,
  **outside** any repo and — critically — outside the sandbox's `/workspace`
  mount). Operator's first instinct was to nest it under
  `spark-ai-agents/luoji/`, but that dir **is** bind-mounted into Luoji's
  sandbox as `/workspace` (rw) — nesting sessions there would have exposed the
  agent's own raw session logs to the agent, an isolation breach. Moved out.
- Edited `spark-ai/openclaw/docker-compose.yml`: added one bind,
  `~/.openclaw-sessions/luoji → /home/node/.openclaw/agents/luoji/sessions:rw`.
  Backup: `docker-compose.yml.bak-pre-bindmount-20260728T194500Z`.
- Pre-change snapshot of the whole config volume:
  `~/backups/openclaw/openclaw-config-pre-bindmount-20260728T194143Z.tar.gz`.
- Copied the 20 existing session items out before the mount could shadow them.
- Recreated the gateway (`docker compose up -d`) — brief bounce of luoji /
  cecat / chattpc26. uid alignment is clean (gateway `node` = uid 1000 =
  `catlett`), so host files are owned by the operator.

### Verified

- Mount live (rw, correct source→target); container view == host view (20
  items, `sessions.json` present) — nothing shadowed.
- Gateway writes through the mount (probe round-tripped host↔container).
- **Sandbox isolation holds:** the luoji sandbox sees `/workspace` (his
  workspace files) but **not** the sessions dir.
- **Proven with live user data:** read the operator's actual Slack DMs to Luoji
  directly from `~/.openclaw-sessions/luoji/2da653f1-*.jsonl`. This is exactly
  the Phase 4 capability — confirmed end-to-end, not just synthetically.

### Two red herrings chased during verification (both benign)

1. **"Luoji not replying."** Not a gateway fault. Two causes, neither related to
   the bind mount:
   - The tap-relevant session (`2da653f1`) shows Luoji **received** the DMs and
     chose `NO_REPLY`, reasoning *"addressed to ChatCeC, not me."* OpenClaw
     allows **one bot for all agents**, so the operator uses per-agent channels
     where a mention of the shared bot = that channel's agent. Luoji's identity
     logic gates on the bot **display name** ("ChatCeC") rather than the
     channel, so he defers instead of answering. **Fix lives in
     `spark-ai-agents`** (Luoji's `SOUL.md`/`IDENTITY.md`) — operator is
     handling it. Not a spark-fabric/gateway issue.
   - Per-turn latency is inflated by the `sage` MCP server
     (`mcp.sagecontinuum.org`) timing out every turn (~15s in the tool-bundle
     phase). Pre-existing, remote endpoint down, unrelated.
2. **"cecat runaway loop."** Investigated (read session `b7c1bf04`): **benign.**
   cecat is doing legitimate Gmail triage (classifying real mail, applying
   rules, archiving bulk/newsletters) in a long-lived session (13:11→20:30),
   still progressing, no errors. The "model call every ~5s" was task work, not a
   loop. Initial alarm was mine, based on log volume before reading content —
   recorded here so the false positive is on the record.

### Boundary / secrets notes

- The compose edit is a **`spark-ai`** change (shared services). Committed there
  with a CHANGELOG entry, per operator; kept out of `spark-fabric`.
- No secrets added. Session logs are conversation content, deliberately kept in
  `$HOME` (not a repo) so they can never be `git add`-ed by accident.

### Open followups

- **Luoji mention-gating** (spark-ai-agents) — operator handling.
- **`sage` MCP timeout** — cosmetic/latency; revisit if it bothers day-to-day.
- **Phase 4 tap still needs a format adapter** — OpenClaw session JSONL is an
  event/trajectory log (`type`/`id`/`parentId`/`role` under `message`), not the
  flat `{role,content}` turns `falda_tap.py` assumes.

---

## Phase 1 — Embedder (Ollama + nomic-embed-text). VERIFY 1 GREEN.

Done **2026-07-28**. Ollama was **not** installed; port 11434 free; no prior
units. Installed as a `--user` systemd unit (matching the existing
`gandalf-*` bridge units), bound to loopback only.

### What surprised me / assumptions checked

1. **The `.tgz` URL is wrong — assets are `.tar.zst`.** `ollama.com/download/
   ollama-linux-arm64.tgz` redirects to a GitHub path that **404s** (delivered a
   9-byte "Not Found", whose sha256 is the well-known empty-ish hash — a good
   canary that the download failed). Queried the GitHub releases API for the
   real asset names instead of guessing. Correct assets for v0.32.5:
   `ollama-linux-arm64.tar.zst` (1.5 GB generic) and two JetPack variants.
2. **JetPack variant would have been the wrong pick.** Release ships
   `arm64`, `arm64-jetpack5`, `arm64-jetpack6`. This GB10/DGX Spark does **not**
   present as a Tegra/Jetson board — no `/etc/nv_tegra_release`, no
   `/proc/device-tree/model` — and runs CUDA 13.0. JetPack builds target older
   L4T CUDA; chose the **generic arm64** build (bundles its own CUDA libs, CPU
   fallback clean). Embedder runs on CPU anyway, so this is belt-and-suspenders.
3. **No root needed.** Installed to `~/opt/ollama` and ran as a `--user` unit —
   no `sudo`, no system service, consistent with the plan's preference and the
   existing user units.

### Pins (also in `services/embedder/README.md`)

- Ollama **v0.32.5** generic linux-arm64;
  tarball sha256 `aa7e06b5683ee66c4a3ec68ea7236db43b5a5d0821f0dfe2c5a215f4462bddf4`.
- Model `nomic-embed-text:latest`, id `0a109f422b47`, 274 MB.
- Binary `~/opt/ollama/bin/ollama`; models `~/.ollama/models`; log
  `~/.ollama/ollama.log`. Unit symlinked from the repo (repo = source of truth).

### VERIFY 1

- `GET /api/version` → `{"version":"0.32.5"}`.
- Listening socket is **`127.0.0.1:11434` only** (confirmed via `ss` — not
  `0.0.0.0`).
- `POST /v1/embeddings` (OpenAI-compatible) with `nomic-embed-text` →
  **embedding length 768**. Matches `FALDA_DIM=768` for Phase 2. ✓

**Phase 1 gate: GREEN.** No secrets added. Nothing hand-configured that a
rebuild would lose (unit + pins in repo; binary/model re-fetched by documented
steps). Stopping before Phase 2 (FALDA gateway) per the gating rule.

---

## Phase 2 — FALDA gateway. VERIFY 2 GREEN.

Done **2026-07-28**. falda checkout present at pin `c9f14bc`. Installed as a
loopback-bound `--user` systemd unit running under the pinned node.

### The node question from Phase 0 is now settled

falda's `package.json` sets `engines: node >=20`. System `/usr/bin/node` is
**v18** → disqualified. Only **nvm v22.22.3** (ABI 127) qualifies, so that's the
gateway's node. `npm ci` + `npm rebuild better-sqlite3` run under it; the unit's
`ExecStart` pins the absolute v22 path (no `PATH` reliance). `better-sqlite3`
loads clean (SQLite 3.53.2), `sqlite-vec-linux-arm64` present. No
`ERR_DLOPEN_FAILED`.

### What surprised me / assumptions checked (both caught by reading source)

1. **FALDA binds `0.0.0.0`, and there was no env to stop it.** `src/gateway.ts`
   called `.listen(PORT, …)` with no host — Node binds all interfaces. This box
   has a **Tailscale IP (100.120.99.52)** and **LAN IP (10.0.5.124)**, so
   no-auth FALDA would have been reachable off-box — the precise exposure the
   plan's SECURITY note forbids. No host firewall constrains 8077, and I have no
   sudo to add one. **Fix:** a one-line change adding `FALDA_HOST` (default
   `127.0.0.1`), captured as `services/falda/patches/0001-bind-loopback-by-default.patch`
   and re-applied by `services/falda/apply.sh` after any fresh clone (the
   checkout is deliberately un-vendored, so a raw edit would vanish on
   re-clone). Confirmed the socket is now `127.0.0.1:8077`. Operator delegated
   the how; chose the patch+apply-script route as lowest-maintenance and
   rebuild-safe, with **zero collateral** (8077 is used by nothing else on the
   box; the change only tightens the bind).
2. **Config is `FALDA_ROOT`, not `FALDA_DB`/`FALDA_BLOBS`.** falda's README
   still documents the old split; the running gateway reads a single
   `FALDA_ROOT` (DB + blobs + `EMBEDDING.json` lock in one dir). Env template
   uses `FALDA_ROOT`. Another doc/source drift — checked the loader, didn't
   trust the doc.

### Other notes

- **Embedding lock is real and strict.** On first boot the gateway writes
  `EMBEDDING.json` (model+dim); a later mismatch is a FATAL exit, not a warning.
  Ours initialized `model=nomic-embed-text dim=768`. Changing either later means
  re-embedding — good, it prevents silent recall corruption.
- Deliverables in `services/falda/`: `falda-gateway.service`,
  `falda.env.template`, `apply.sh` (idempotent), `patches/0001-*.patch`, README
  with pins. Data root `~/.falda/data`; log `~/.falda/gateway.log`; env at
  `~/.config/falda/falda.env` (0600).

### VERIFY 2

- `GET /healthz` → `{"ok":true,"tiers":["stream","atoms","scenes","core"],"pools":true}`. ✓
- `npm run smoke` → **13 passed, 0 failed — ALL TIERS GREEN**. ✓
- Socket is **`127.0.0.1:8077`** (confirmed via `ss`, after the loopback patch). ✓

**Phase 2 gate: GREEN.** No secrets. The falda source edit lives as a tracked
patch + apply script, not a hand-edit a rebuild would lose. Stopping before
Phase 3 (tenants + shared pool) per the gating rule.

---

## Phase 3 — Tenants + shared pool. VERIFY 3 GREEN.

Done **2026-07-28**. Tenants `gandalf`/`luoji` are **implicit** (a
`(tenant, self)` store is created on first write — nothing to "create"). Only
the shared pool is declared.

### API correction (checked source, per the method)

The plan's Phase 3/4 examples use a **query-string** form
(`GET /stream/search?q=…&tenant=luoji`) and a bare `/pools/declare -d {...}`.
The real API (`src/gateway.ts`) is **all POST with a JSON body**, `{tenant,
pool}` as body fields; no `pool` ⇒ private `self`. `/stream/add` needs
`{session_id, messages:[{role,content}]}`; `/atoms/upsert` needs `{content,
type?}`. Used atoms for the VERIFY (discrete facts). Captured a repeatable,
idempotent `declare-pools.sh` (declare-or-update, since `/pools/declare` errors
`exists` on re-run).

### VERIFY 3 — isolation + sharing, proven empirically and physically

- Private atom written to `gandalf` (self) → **not** returned by a `luoji`
  search; **is** returned by a `gandalf` search. ✓
- Atom written by `luoji` to `shared-corpus` → returned to **both** `gandalf`
  and `luoji` **via the pool**; **not** present in either tenant's private
  `self` store (verified by exact-content check, not just score). ✓
- On disk: separate SQLite files — `tenants/gandalf/self/falda.db`,
  `tenants/luoji/self/falda.db`, `pools/shared-corpus/falda.db`. Isolation is
  filesystem-physical, not a query predicate. ✓

### Bug found during cleanup → fixed (patch 0002)

Deleting the VERIFY test atoms exposed a real **upstream FALDA bug**:
`deleteAtoms`/`deleteStream` delete only the primary row, **orphaning the
`_fts` (and `_vec`) shadow rows**. Orphans surface in `/search` as **phantom
hits** — a `score` with no `id`/`content` — and they **coexist with real
results** (a later "helium" search returned the real atom *plus* a phantom). The
authoritative `/query` route is unaffected. This would have bitten the Phase 4/5
`/search` consumers intermittently (after any delete).

- Root cause in `src/falda.ts`: deletes never touched the shadow tables, though
  `upsertAtom` already does the correct `DELETE FROM atoms_fts/atoms_vec WHERE
  id=?` cleanup. Fix mirrors that.
- No upstream fix at the pin (`origin/main` == `c9f14bc`). Captured as
  `patches/0002-clean-fts-vec-on-delete.patch`; `apply.sh` now loops over all
  `patches/*.patch`.
- Purged the pre-existing orphan rows (gandalf: 1 stream + 2 atoms;
  shared-corpus: 1 stream) left by deletes before the fix.
- Regression-tested: write→delete→search now returns `items:[]`, raw
  `atoms_fts` count 0, and `npm run smoke` still **ALL TIERS GREEN**.
- Operator chose "patch now, like loopback."

**Phase 3 gate: GREEN.** Stores left clean (`/query` total 0 across all three).
No secrets. Stopping before Phase 4 (Luoji shadow capture) per the gating rule —
note Phase 4 still needs the OpenClaw-session format adapter and will use the
host-mounted session path from the Option B bind-mount.

---

## Phase 4 — Luoji shadow capture. VERIFY 4 GREEN.

Done **2026-07-28**. Shadow tap tailing Luoji's OpenClaw session JSONL →
FALDA `/stream/add` tenant `luoji`. OpenClaw stays authoritative; his own
`memory/*.md` is untouched and unaware of FALDA (shadow, not live).

### The format adapter (the known Phase-4 unknown)

falda's `falda_tap.py` assumes flat `{sessionKey, role, content}` lines.
OpenClaw's format is an event log: only `type=="message"` events carry a turn,
nested under `message.{role,content}`, where `content` is a string (user) or a
list of blocks (assistant/tool). Wrote a dedicated adapter,
`services/falda-tap/falda_tap_openclaw.py`, keeping falda's byte-offset
checkpoint design and adding OpenClaw parsing + filters. Reads the Option B
host-mounted path `~/.openclaw-sessions/luoji`.

### Capture-scope decisions (operator)

- **user + assistant only.** `toolResult` dropped — measured at ~79% of byte
  volume (36k vs 10k chars), pure log/file-dump noise that would bloat T0 and
  degrade distillation.
- **heartbeat turns filtered** (`[OpenClaw heartbeat poll]` / `HEARTBEAT_OK`) —
  cron noise.
- assistant `toolCall`-only turns (no text) naturally excluded (flatten to
  empty). Verified all 45 such skips were genuinely textless, not lost content.

### VERIFY 4

- **4a capture:** backfilled **94** real turns on first poll; searchable
  (`/stream/search` "favorite color" returns the prior DM). ✓
- **4b restart safety:** restarted the unit — count held at 94, zero
  duplication; checkpoint (`~/.falda/tap_state_luoji.json`) intact. ✓
- **4c live round-trip:** operator sent Luoji "remember codeword
  TANGERINE-CANYON" (addressed explicitly to LUOJI, which got past the
  still-unfixed mention-gating). New session `bc01033f` on disk → tap captured
  **3 turns** (96→99) → **TANGERINE-CANYON searchable in FALDA tenant luoji**.
  Same session's `toolResult`/tool-call/write events were correctly excluded —
  live proof the filters work. ✓

### Process note (my error, recorded)

Earlier in this phase I misread a monitor event: a `mirrored 2 turns` at 19:09
was Luoji's 15-min **heartbeat** cycle, not the operator's test message — the
operator was away and had sent nothing. I wrongly reported "the test didn't
work" and chased a non-existent message. Lesson: a tap-fired event ≠ the
specific message I was expecting; **verify captured content**, not just that the
tap fired. The real round-trip (above) was then done deliberately with baseline
+ content verification.

### Deliverables

`services/falda-tap/`: `falda_tap_openclaw.py`, `falda-tap-luoji.service`
(`--user`, `Restart=always`, stdlib python3 — NOT the sibline venv), README.
Log `~/.falda/tap_luoji.log`; checkpoint `~/.falda/tap_state_luoji.json`.

**Phase 4 gate: GREEN.** Shadow only — OpenClaw `memory.provider` NOT flipped.
Mention-gating remains an open `spark-ai-agents` item (operator's), independent
of the tap. Stopping before Phase 5 (Gandalf) per the gating rule.

---

## Phase 5 — Gandalf. STARTING STATE / HANDOFF (context reset 2026-07-28)

Written before a `/compact` at ~100% context. Phase 5 not yet begun; discovery
done. Work lands in **Spark-Hermes** (Gandalf-specific), per the boundary.

### Decisions locked in
- **Snapshot is NOT a gate.** `ops/snapshot.sh` / `nemohermes gandalf snapshot
  create` is **broken** — empty output (`backedUpDirs: []`; only `SOUL.md` +
  manifest; all 14 state dirs + `runtime/state.db` fail). Pre-existing, not
  caused by us. Operator decision: **Gandalf is disposable** — memories/sessions
  expendable, identity `.md` files are in Git — so proceed without a snapshot.
  Optional near-free insurance: `tar` `/sandbox/.hermes` to keep the sandbox
  `.env` secrets (Telegram/Tavily; also in host `~/.hermes/.env`). A
  `.tirith-install-failed: download_failed` marker in the sandbox may relate to
  the snapshot tooling — operator's Spark-Hermes territory, not fabric.

### Discovery that rewrites 5a (plan's `[ASSUMED]` was wrong)
- Plan assumed `host.openshell.internal:8077` just works. **It won't yet.** The
  sandbox (`172.19.0.2`, bridge `openshell-docker` = `br-a89074d4fc78`) reaches
  host services ONLY via socat bridges on **`172.19.0.1`**. vLLM/litellm/argo
  already have them (`:8000/:4000/:44497`). FALDA is loopback-only, so **`:8077`
  has no bridge**. `host.openshell.internal` → `172.19.0.1`, so
  `host.openshell.internal:8077` fails until a bridge exists.
- **5a therefore needs TWO things:** (1) a FALDA socat bridge on
  `172.19.0.1:8077` — mirror
  `Spark-Hermes/bringup/40-vllm-bridge/gandalf-vllm-bridge-openshell.service`
  (`socat TCP-LISTEN:8077,bind=172.19.0.1,fork,reuseaddr TCP:127.0.0.1:8077`),
  install as a `--user` unit in **Spark-Hermes**; (2) the egress policy
  `bringup/50-openshell-policies/falda-local-egress.yaml` mirroring
  `telegram-egress.yaml`, applied via `ops/apply-policies.sh`. **Do NOT touch**
  the existing `falda-egress.yaml` (Rick's remote proxy `103.101.203.226:8444`).
- `172.19.0.1` is a docker-bridge iface, **not** off-box — same exposure profile
  as the existing bridges; L7 egress policy still gates the sandbox. Safe.
- **VERIFY 5a:** `docker exec -u sandbox
  openshell-gandalf-354307c9-7df4-47a5-9b86-f6ae0a81ae9e curl -s
  http://host.openshell.internal:8077/healthz` → `{"ok":true,...}`.

### Still ahead
- **5b** shadow capture, tenant `gandalf`. Find Hermes L0 session log (ASSUMED
  `/sandbox/.hermes/`, confirm). Prefer host path if a volume exposes it, else a
  `docker exec` poller like `ops/outbox-processor.sh`. Reuse the Phase-4 tap
  approach but for the Hermes format.
- **5c** FALDA as Gandalf's real memory. `/opt/hermes/agent/memory_provider.py`
  ABC confirmed to exist. Map `sync_turn`→`/stream/add`, `prefetch`→search,
  `system_prompt_block`→`/core/read`. Tenant `gandalf`, pool `shared-corpus`.
  Shadow first, then prefetch. Provider source in Spark-Hermes behind an apply
  script — NEVER hand-place in the container (rebuild wipes it). VERIFY 5c: a
  fresh `/new` session recalls a `shared-corpus` fact (from a Luoji conversation)
  WITHOUT being told to search.

### Resume checklist
1. Read this section + `git log` (spark-fabric through Phase 4, all pushed).
2. Memory note `project_spark_fabric_bringup.md` has the same state.
3. Do NOT restart vLLM / argo-shim. All four repos under `~/code`, remotes
   `github.com/cecat/*`. FALDA on `127.0.0.1:8077`, embedder `:11434`, both live.
4. Start at **5a**: FALDA socat bridge (Spark-Hermes) + egress policy, then
   VERIFY 5a from inside the sandbox.

---

## Phase 5a — FALDA reachable from the Gandalf sandbox — ✅ GREEN (2026-07-28)

Work landed in **Spark-Hermes** (agent-specific), per the boundary. Two parts:

### 1. Socat bridge (substrate half)
`Spark-Hermes/bringup/45-falda-bridge/gandalf-falda-bridge-openshell.service`
```
socat TCP-LISTEN:8077,bind=172.19.0.1,fork,reuseaddr TCP:127.0.0.1:8077
```
Installed as a `--user` unit (`systemctl --user enable --now`). One unit only —
FALDA already binds host loopback, so unlike vLLM there's no second host-facing
bridge. Verified listener: `172.19.0.1:8077` (socat). README in that dir.

### 2. Egress policy (enforcement half)
`Spark-Hermes/bringup/50-openshell-policies/falda-local-egress.yaml`, preset
`falda-local-egress`. Applied with **`nemohermes gandalf policy-add --from-file
… --yes`** (NOT `ops/apply-policies.sh`, which would also apply Rick's REMOTE
`falda-egress.yaml`). → Policy **version 9 loaded**.

**Schema correction vs the plan (checked the actual blueprint, didn't guess):**
read `/opt/nemoclaw-blueprint/policies/presets/local-inference.yaml` inside the
sandbox — the working local-HTTP pattern. Two things a naive mirror of
`telegram-egress.yaml` would have gotten WRONG:
- `allowed_ips: [10/8, 172.16/12, 192.168/16]` is **required** — OpenShell's SSRF
  guard rejects private host-gateway IPs (172.19.0.1) otherwise.
- Plain `protocol: rest` on bare port 8077 (no TLS/443 — the proxy speaks HTTP to
  FALDA). Modeled the preset exactly on `local-inference`, not on telegram.

### Enforcement model discovered (and why the plan's VERIFY was wrong)
The Hermes gateway (PID 205, `hermes gateway run`) forces ALL egress through the
OpenShell L7 proxy `10.200.0.1:3128` (`https_proxy`/`http_proxy` in its environ;
`NO_PROXY=localhost,127.0.0.1,::1,10.200.0.1` — note `host.openshell.internal` is
NOT exempt). The proxy enforces the policy **per calling principal**.

Two test paths that MISLED (both recorded in the 45-falda-bridge README):
- **Bare `docker exec … curl http://host.openshell.internal:8077/…`** → 200 even
  with NO policy. A fresh exec shell has none of the gateway's proxy env, so it
  bypasses enforcement. This is the plan's VERIFY 5a as written — it proves the
  bridge, proves NOTHING about the policy. **Superseded.**
- **`docker exec … curl -x http://10.200.0.1:3128 …`** → 403 `policy_denied`
  even WITH the correct policy — an exec'd curl isn't in the gateway's tracked
  process tree, so the proxy won't treat it as a principal. vLLM (known-working
  for the real agent) 403s identically through this path.

**Faithful test = `nemohermes gandalf exec`** — runs in the tracked context the
proxy honors.

### VERIFY 5a (authoritative) — PASS
```
$ nemohermes gandalf exec -- /usr/bin/curl -s http://host.openshell.internal:8077/healthz
{"ok":true,"tiers":["stream","atoms","scenes","core"],"pools":true}
$ nemohermes gandalf exec -- … -X POST …/stream/search -d '{"tenant":"gandalf","query":"ping"}'
{"messages":[]}        # (after orphan purge below)
```
Control: vLLM `:8000` via the same tracked exec → 200. FALDA `:8077` via same → 200.

### Incidental cleanup — pre-existing orphan vec/fts rows in gandalf tenant
The first gandalf search returned a phantom score-only hit (`{"score":…}`, no
id/content) — the same orphan signature patch 0002 prevents. These predate 0002
(delete-path fix is forward-only). The gandalf tenant had **0 real rows**
(`stream=0`, `atoms=0`) but 1 orphan in `stream_vec` + 2 in `atoms_vec`. Purged
(with a `.bak-pre-orphan-purge` backup of the tenant db) via the bundled
`sqlite-vec-linux-arm64/vec0.so`. Post-purge: all fts/vec counts 0; searches
return `[]`. Clean tenant for 5b/5c.

### Files (Spark-Hermes)
- `bringup/45-falda-bridge/gandalf-falda-bridge-openshell.service` + `README.md`
- `bringup/50-openshell-policies/falda-local-egress.yaml`

**Gate: 5a GREEN. Proceeding to 5b (shadow capture, tenant gandalf).**

---

## Phase 5b — Gandalf shadow tap — ✅ GREEN (2026-07-28)

Source is spark-fabric `services/falda-tap/falda_tap_hermes.py` + unit
`falda-tap-gandalf.service` (shared substrate — a FALDA feeder). NOT yet
installed as a service (running manually during eval; install step below).

### Source-of-truth decision (plan's [ASSUMED] jsonl was wrong)
Discovery proved the per-session `*.jsonl` files exist for only **32 of 102**
interactive sessions (gap spread across all dates, not a format era) — tailing
them would silently miss ~69% of conversations. The canonical, complete store is
the sandbox SQLite DB `/sandbox/.hermes/runtime/state.db` (`messages` +
`sessions`, FTS5). No host bind-mount, so the tap crosses via `docker exec -u
sandbox python3` (stdlib; sandbox has no sqlite3 CLI), reads read-only
(`mode=ro`), checkpoints on the monotonic `messages.id` PK. Filter: keep
`source IN (telegram,slack)` user+assistant non-empty; drop `cron` (~96% of
volume: automated inbox-triage `[SILENT]`/skill preambles — Gandalf analog of
Luoji heartbeats) + `api_server` + tool/session_meta roles + exact `[SILENT]`.

### Bug found & fixed DURING 5b (worth noting): /stream/add timeout on backfill
First backfill run threw `TimeoutError`. Root cause: `/stream/add` embeds every
message inline via the CPU Ollama embedder; a 99-msg / 50KB session posted in one
shot on a cold embedder exceeded the 10s client timeout. Fix in the tap: chunk
each session into `TAP_CHUNK=25` sub-batches and raise `TAP_POST_TIMEOUT=120`.
(This is a CLIENT-side fix; see FALDA-FINDINGS RE for the server-side note — no
per-request server timeout knob, embed cost is silent.) `forward()` now posts in
strict global-id order, one POST per same-session chunk, STOPS on first failure,
and only advances the checkpoint over fully-handled ids — no gaps/dupes on restart.

### VERIFY 5b — PASS (content, not just mechanism)
Clean single backfill: **394 rows, 22 sessions, 0 duplicates** (checkpoint
id=24364). `stream/search tenant=gandalf "are you listening"` returns the real
telegram line `"Hello are you listening?"` (1x). Earlier triplicates (from my
repeated reset-and-rerun while fixing the timeout) were purged via the API delete
path FIRST — which also drove `stream_fts`/`stream_vec` to 0, **confirming patch
0002 works end-to-end through the gateway** (positive finding for Rick).

### Install as service (when ready to run continuously)
```
ln -sf ~/code/spark-fabric/services/falda-tap/falda-tap-gandalf.service \
  ~/.config/systemd/user/falda-tap-gandalf.service
systemctl --user daemon-reload && systemctl --user enable --now falda-tap-gandalf.service
```

---

## Phase 5c PREP — Charlie's two research requirements (2026-07-28)

Charlie reframed Phase 5: the memory provider is **experimental apparatus** for
studying how much of the Hermes-vs-OpenClaw behavioral difference (same model,
same endpoint) is attributable to context/memory management. Two requirements to
build into the FALDA provider from the start (cheap now, painful to retrofit).
Report on observability BEFORE building 5c. Findings from reading the actual
source (`/opt/hermes/agent/memory_provider.py`, `memory_manager.py`,
`run_agent.py`) follow.

### REQ-1 observability — WHAT'S REACHABLE FROM THE MemoryProvider ABC
Investigated against source (NOT assumed). Provider hooks are called by
`agent/memory_manager.py`, wired in `/opt/hermes/run_agent.py`:

REACHABLE (log these directly — they ARE our provider's own outputs):
- `system_prompt_block()` return string — OUR static block. Called at prompt
  assembly (run_agent ~6241 via `memory_manager.build_system_prompt()`).
- `prefetch(query, session_id)` return string + the `query` — call site
  run_agent ~12523. **query = `original_user_message`** (clean user input, NOT
  skill-injected `user_message` — good: stable independent variable). We control
  the return, so we can log which FALDA tiers we hit and per-tier result counts.
- `on_turn_start(turn_number, message)` — run_agent ~12510, fires BEFORE
  prefetch. Gives us turn number + clean user message. NOTE: at THIS call site
  only 2 positional args are passed (no `remaining_tokens/model/platform`
  kwargs the ABC docstring lists as possible — so don't rely on those here).
- `on_pre_compress(messages)` — full message list about to be compressed
  (run_agent ~10681). `on_session_end(messages)`, `on_session_switch(...)`,
  `on_memory_write(action,target,content,metadata)`, `on_delegation(...)`.
- `initialize(session_id, **kwargs)` kwargs: hermes_home, platform, and maybe
  agent_context/agent_identity/agent_workspace/parent_session_id/user_id.

NOT reachable from the ABC (reported plainly, per Charlie's instruction):
- The FULL assembled system prompt is **NOT passed to any provider hook**. It's
  built by `AIAgent._build_system_prompt()` (run_agent ~6264) and cached at
  `self._cached_system_prompt` (~1948) — an AIAgent instance attribute the
  provider never receives. Our provider can see ONLY its own
  `system_prompt_block()` contribution, not the sibling blocks (soul, skills,
  tools, etc.) nor the final concatenation.
- **BUT** — the full prompt IS observable WITHOUT patching /opt/hermes: Hermes
  itself persists it. `_ensure_db_session()` (run_agent ~2551) writes
  `system_prompt=self._cached_system_prompt` into `sessions.system_prompt` in
  state.db. VERIFIED: all 22 telegram/slack sessions have it populated (max len
  18474; sample begins with the SOUL canary). So the provider (or a sidecar) can
  read the full assembled prompt per session_id from state.db read-only — no
  patch, survives rebuilds. This is the answer to Charlie's core question.
- Do NOT patch /opt/hermes for visibility (rebuild wipes writable layer) — not
  needed given the state.db route.

### REQ-2 config-driven knobs — NATIVE MECHANISM EXISTS
The ABC has `get_config_schema()` + `save_config(values, hermes_home)`, driven by
`hermes memory setup`. That's for SETUP prompting, writes to provider's native
config location. For an ABLATION HARNESS the cleaner path: provider reads a
versioned config FILE at init (in Spark-Hermes), so "one file + restart" = one
condition. Knobs to expose (no magic numbers): retrieval top-k per tier; RRF
dense/lexical weights; which tiers prefetch consults + a prefetch-OFF baseline;
max chars injected/turn; free-text experiment/condition label stamped into every
log line. Same treatment later for distiller knobs (phase 6): L1_EVERY_N,
L2_INTERVAL_S, L3_INTERVAL_S, chunk window.

### Telemetry logs = DATA not code
Write per-turn logs OUTSIDE any repo: `~/.falda/telemetry/`, mode 0600,
gitignored (they contain Charlie's conversations). Per turn log: exact
system_prompt_block() string; exact prefetch() string + its query + tiers hit +
per-tier counts; turn number, session_id, timestamp, condition label; and a hash
of each big string so unchanged turns are cheap.

### Phase 5c PREP addendum — full hook surface verified against source (Hermes v0.14.0)
Charlie confirmed (read upstream) the full system prompt reaches NO hook — agreed,
stop looking, use the state.db route. He wants the ENTIRE observable surface
instrumented even where the provider is functionally a no-op. Verified each hook's
ACTUAL call-site args in this deployed version:

- **on_turn_start(turn_number, message, **kwargs)** — call site run_agent.py:12510
  passes ONLY `(self._user_turn_count, _turn_msg)`. The manager wrapper
  (memory_manager.py:379) forwards `**kwargs` faithfully, BUT the run_agent call
  site supplies none. So in v0.14.0 the docstring's promised
  `remaining_tokens/model/platform/tool_count` DO NOT ARRIVE at gateway turns.
  → Report to Charlie: NOT populated here. Log them defensively
  (`kwargs.get(...)`) so we capture them if/when a future version adds them, but
  don't count on them. (model/platform we already know from initialize().)
- **on_pre_compress(messages)** — run_agent.py:10681, passes the full `messages`
  list about to be compressed, NO kwargs. We can log len(messages) + a token
  estimate + our returned contribution. This is the compaction-content observer.
- **on_session_switch(new_sid, parent_session_id, reset, reason)** — run_agent.py
  :10789 fires on compression with `reason="compression"`, `reset=False`,
  parent=old sid. So: pre_compress (what's discarded) + session_switch
  (reason=compression, chains old→new sid) together = full compaction-event
  record. `reset=True` distinguishes /new//reset from /resume//branch.
- **on_memory_write(action, target, content, metadata)** — run_agent.py:10972,
  fires on built-in MEMORY.md/USER.md tool writes (action add/replace). Instrument
  it → the COMPETING native memory system is observed too, not just FALDA.
- **on_session_end(messages)** — full conversation history at session boundary;
  log for post-hoc analysis.

**Independent static-context sampler (no Hermes hooks):** periodically hash
SOUL.md / MEMORY.md / USER.md and log on change. These are the static-context
record. Locations to confirm at build: sandbox `/sandbox/.hermes/SOUL.md` (present),
MEMORY.md/USER.md under `/sandbox/.hermes/memories/` (dir seen in 5b). Sampler
runs host-side (like the tap) or as a tiny timer; writes to ~/.falda/telemetry/.

Net 5c telemetry plan: provider logs its own system_prompt_block + prefetch
(query, tiers, per-tier counts, returned text) + every hook above; a state.db
reader captures the full assembled `sessions.system_prompt` per session_id; a
file-hash sampler captures SOUL/MEMORY/USER drift. All → ~/.falda/telemetry/
(0600, gitignored), each line stamped with the config condition label.

### 5b — installed as background service (2026-07-28 22:19)
`falda-tap-gandalf.service` enabled + active (survives reboot). Verified single
process, 394 rows unchanged on service start (checkpoint idempotency held — no
dupes). Confirmed the full ingestion layer is now self-sustaining, all --user,
all enabled:
- ollama.service (embedder) · falda-gateway.service (store)
- falda-tap-luoji.service (Luoji→FALDA, still live) · falda-tap-gandalf.service (Gandalf→FALDA)
Both agents' telegram/slack + OpenClaw conversations mirror to FALDA continuously.
This is the "just works" steady state Charlie wanted BEFORE any research
experiments. Next: 5c FALDA memory provider (built as experimental apparatus per
the REQ-1/REQ-2 prep above).

---

## Phase 5c — FALDA as Gandalf's memory provider — ✅ VERIFY 5c GREEN (2026-07-29)

Built the FALDA memory provider as experimental apparatus per REQ-1/REQ-2.
Cross-agent automatic recall proven end-to-end. Work lands in **Spark-Hermes**
(Gandalf-specific), per the boundary. Nothing in spark-fabric except findings.

### Design (locked with Charlie this session)
- **`sync_turn` is a NO-OP.** The 5b host tap remains the sole shadow writer to
  `tenant=gandalf` — no double-write, tenant privacy intact.
- **Sharing to `shared-corpus` is a deliberate agent act**, never automatic —
  exposed as the `falda_share` tool, not a per-turn firehose (Charlie: automatic
  pool writes would destroy the privacy boundary).
- **Two tools, each INDEPENDENTLY config-gated** (`falda_share`, `falda_search`):
  `get_tool_schemas()` consults config so the 2×2 (prefetch × search-tool, share
  independent) is fully addressable. Charlie needs the whole grid; a hardcoded
  tool would lose half of it.
- **Recall (prefetch + core block) separately gated; rolled OUT off→on.**
- **Telemetry lives inside the sandbox** (`/sandbox/.hermes/telemetry/`, 0700);
  a host timer `docker cp`s it to durable `~/.falda/telemetry/` (0600).

### Deliverables (Spark-Hermes)
- `gandalf/plugins/falda/__init__.py` — `FaldaMemoryProvider` + `register(ctx)`.
  stdlib `urllib` transport (NOT requests — not on the gateway interpreter path;
  urllib honors the gateway proxy env → tracked principal, passes 5a policy).
- `gandalf/plugins/falda/{plugin.yaml,condition.yaml}` — condition.yaml is the
  "one file + restart = one condition" knob file.
- `ops/apply-memory-provider.sh` (`--activate`/`--deactivate`), wired into
  `ops/post-rebuild.sh` (re-pushes plugin AND re-activates — rebuild wipes both
  the overlay plugin and `memory.provider`).
- `ops/pull-telemetry.sh` + `bringup/45-falda-bridge/gandalf-telemetry-pull.{service,timer}`.
- `gandalf/skills/falda-memory/SKILL.md`.

### Source facts verified (not assumed)
- Provider registration: drop `$HERMES_HOME/plugins/falda/` with an `__init__.py`
  exposing `register(ctx)`; set `memory.provider: falda`. Worked example: bundled
  `holographic`. Loaded/available confirmed via Hermes's own
  `discover_memory_providers()`/`load_memory_provider()`.
- **Gateway runs `/opt/hermes/.venv/bin/python`** (the venv has PyYAML/requests),
  NOT the bare `/usr/bin/python3.13`. `/proc/205/exe` was misleading.
- **Cron turns pass `skip_memory=True`** (`cron/scheduler.py:1464`) → the provider
  never inits for cron; only real interactive (telegram/slack) turns. The two
  `gateway/run.py` `skip_memory=True` sites are auxiliary sub-agents, not the main
  path.

### Two landmines caught
1. **`docker exec` heredoc silent no-op.** The apply script's yaml edit read
   empty stdin (no `-i`), reported success, changed nothing. Fixed with
   `docker exec -i`.
2. **Config-integrity anchor.** `/etc/nemoclaw/hermes.config-hash` (root-owned)
   pins `config.yaml`; my edit changed its hash. Traced the startup logic: this
   deployment runs the **non-root path** (`nemoclaw-start` + gateway both run as
   `sandbox`), which calls `verify_config_integrity_if_locked` → **skips** because
   `/sandbox/.hermes/.config-hash` is sandbox-owned, not root-locked. config.yaml
   had already diverged from the /etc anchor on 2026-07-28 (pre-me); gateway has
   run fine since. Restart verified safe; boot log: "integrity check skipped for
   mutable default." (Only the ROOT startup path enforces the /etc anchor.)

### Restart mechanism
`docker restart <gandalf-ctr>` — re-runs the entrypoint, preserves the writable
overlay (plugin + config-edit survive; only a full rebuild wipes them). NOT a
shared service. `kill 205` would make `nemoclaw-start` hit its final `wait` and
exit — avoided.

### VERIFY A — GREEN (provider present, prefetch OFF)
After `--activate` + restart: `hermes memory status` → Provider: falda,
installed ✓, available ✓. Charlie sent a real Telegram turn; telemetry
`session_open` (condition `5c-A-baseline-all-off`, `registered_tools: []`),
`turn_start` (`tool_count: null` — confirms v0.14.0 doesn't pass it, captured
defensively), `prefetch enabled:false`. Gandalf behaved normally → "provider
present" cleanly isolated from "recall on." Host puller mirrored the 3 lines to
`~/.falda/telemetry/`.

### VERIFY 5c — GREEN (automatic cross-agent recall), proven mechanistically
1. Seeded a synthetic fact as **tenant=luoji, pool=shared-corpus**: "Luoji's
   project codeword is VELVET-MERIDIAN." (both an atom and a stream turn).
2. Pre-flight read check: gandalf+pool search FINDS it (atoms+stream); gandalf
   private `self` does NOT — pool isolation holds.
3. Flipped `condition.yaml` → `5c-B-prefetch-on` (prefetch_enabled + include_shared),
   re-applied, restarted. (Provider caches config at load, so a restart is
   required to change condition.)
4. Charlie, fresh `/new` Telegram session, asked "what is Luoji's project
   codeword?" WITHOUT telling him to search → **Gandalf answered VELVET-MERIDIAN.**
5. Telemetry proof (condition `5c-B-prefetch-on`, turn 1):
   `prefetch enabled:true, include_shared:true,
   per_source_counts={stream:self:5, stream:shared:1, atoms:self:0, atoms:shared:2},
   injected_chars:832`; `registered_tools:[]` and NO `tool_call` event → recall
   was automatic prefetch from the pool, not an explicit search and not
   confabulation.

### New FALDA findings (in docs/FALDA-FINDINGS.md)
- **RE-5** — RRF weights hardcoded (`1/(RRF_K+i)`, equal dense/lexical) in
  `hybrid()`; no per-request dense/lexical weight → our REQ-2 RRF knob is INERT,
  logged intended-vs-actual. Candidate PR: accept `dense_weight`/`lexical_weight`.
- **BUG-2 addendum** — patch 0002 is forward-only; a pre-existing orphan surfaced
  in the `shared-corpus` POOL: seeded 1 atom, `/atoms/search` returned 2 (real +
  phantom score-only) while `/atoms/query` correctly returned total 1. Harmless to
  recall (real hit ranks first) but confirms the "LEFT JOIN base table, drop
  null-content rows in search" defense-in-depth is worth shipping with 0002.
- **CONFIRMED GOOD** — cross-agent pool recall (the headline differentiator)
  works end-to-end via a Hermes prefetch. Neither agent's native memory has this.

### Current live state
- Condition: **`5c-B-prefetch-on`** (prefetch ON, both tools OFF,
  system_prompt_block OFF). Provider active; gateway serving.
- Telemetry durable at `~/.falda/telemetry/falda_provider.jsonl`.
- Full ingestion + recall now live: taps feed FALDA; provider reads it back.

### Not yet done
- Telemetry pull timer written but **not yet installed** as a `--user` unit
  (pulled manually during verify). Install when running the grid continuously.
- SOUL/MEMORY/USER file-hash sampler (REQ-1 static-context observer) — designed
  in prep, not yet built.

---

## Phase 5c — ablation grid, first run — ✅ (2026-07-29)

Ran the 2×2 (prefetch × search_tool; share held off) with an automated driver.
Runner: `Spark-Hermes/ops/run-ablation-grid.sh`. Per cell: rewrite
`condition.yaml` → apply → `docker restart` → wait for api_server health → POST 3
recall probes → pull telemetry. Provider telemetry (condition-stamped) is the
measurement.

### Driver mechanics (things that mattered)
- **api_server is in the gateway's OWN network namespace.** It binds
  `127.0.0.1:18642` inside netns `4026534453`; a plain `docker exec` shell is in a
  different netns → connection refused. Reach it with `nsenter -t <gw_pid> -n
  curl …`. The gw pid changes every restart — re-resolve it each poll.
- **Session contamination guard.** api_server derives `session_id =
  sha256(system_prompt + first_user_message)` (`_derive_chat_session_id`), and
  `X-Hermes-Session-Id` needs an API key (none set). So identical probe text
  across cells would collide and load stale history. Fix: prefix each probe with
  `[grid:<cell>:<label>]` → unique, empty-history session per (cell×probe).
- **Cron is the only other traffic** and it skips the provider (`skip_memory`),
  so it doesn't pollute telemetry — but a cron job running during startup delays
  the api_server bind, so the health wait must be patient (used 120×2s).

### Probes (answers pre-seeded in FALDA)
- Q1 codeword → VELVET-MERIDIAN (shared-corpus pool)
- Q2 ticket → 4471 (gandalf PRIVATE tenant — tests self-tier)
- Q3 deploy window → Thursday 1400 UTC (shared-corpus pool)

### Results — behavior × telemetry (the whole point)

| Cell | prefetch | search tool | Q1 codeword | Q2 ticket | Q3 deploy | telemetry |
|---|---|---|---|---|---|---|
| **P0S0** | off | off | ❌ "don't know" | ❌ | ❌ | prefetch enabled=false ×3; no tools registered; 0 tool calls |
| **P1S0** | **on** | off | ✅ VELVET-MERIDIAN | ✅ 4471 | ✅ Thu 1400 | prefetch fired ×3, injected 1998/808/1459 chars, 4 shared-hits/turn |
| **P0S1** | off | **on** | ~ hedged* | ❌ | ❌ | prefetch off; `falda_search` **registered**; fired **1×** of 3 |
| **P1S1** | **on** | on | ✅ VELVET-MERIDIAN | ✅ 4471 | ✅ Thu 1400 | prefetch fired ×3 (same as P1S0); tool registered but **0 calls** |

\* P0S1 codeword: model said *"Prior sessions answered VELVET-MERIDIAN … I have
no verification"* — a hedge referencing training/other context, NOT a clean
recall. Telemetry shows `falda_search` fired on exactly ONE of the three P0S1
sessions (the codeword one); ticket + deploy fired no tool and returned
"don't know."

### Findings (research signal, first pass)
1. **Prefetch is the decisive lever.** P0S0→P1S0 flips all three probes from
   "don't know" to correct, with zero tool use — automatic injection alone
   accounts for the recall. Both scopes work (private self-tier AND shared pool).
2. **An available search tool is largely NOT self-invoked.** In P0S1 Gandalf
   reached for `falda_search` only 1/3 times and otherwise answered "I don't
   know" rather than digging. So *having* a memory tool ≠ *using* it; passive
   prefetch >> active tool for surfacing facts the model doesn't know it's
   missing. (Candidate hypothesis for the Hermes-vs-OpenClaw behavioral delta.)
3. **When prefetch is on, the tool is redundant.** P1S1 == P1S0 behaviorally and
   the tool fired 0×: the fact was already in context, so no reason to search.
4. **Injected-char volume varies by query** (808–1998) at fixed top-k — RRF
   returns different-length hits; the `max_chars_per_turn=2000` cap was
   approached (1998) but not exceeded. Knob works.
5. **Security posture is visible in telemetry-adjacent behavior:** Gandalf
   flagged the `[grid:…]` probe prefix as a possible injection on the ticket
   probe — worth remembering that instrumentation prefixes leak into the model's
   view and can change behavior. For clean runs, keep tags minimal/plausible.

### Artifacts
- Runner: `Spark-Hermes/ops/run-ablation-grid.sh` (committed with results).
- Raw data: `~/.falda/telemetry/falda_provider.jsonl` (filter `condition=grid-*`);
  behavioral answers in `~/.falda/grid-run.log`. Both 0600, outside all repos.

### Live state after the grid
Condition set to **`5c-live-full`** (prefetch + search + share all ON) as the
everyday running state. To change: edit `condition.yaml` + re-apply + restart.

---

## Phase 6 — Distiller (T0→T1→T2→T3) — ✅ VERIFY 6 GREEN (2026-07-29)

Stood up the distiller sidecar that promotes FALDA stream turns up the tiers via
Argo/Opus. Deliverables in spark-fabric `services/distiller/` (config + unit +
README only; the script is un-vendored at `~/code/falda/falda_distiller.py`, pin
`c9f14bc`).

### Prereqs verified (not assumed)
- LiteLLM live on `:4000`; `claudeopus47` is a real model_name in
  `Spark-Hermes/litellm/config.yaml` (→ anthropic/claudeopus47, dummy key). No
  master key. **Cheap round-trip through the exact distiller route
  (`:4000/v1/chat/completions` → argo → Opus) returned the canary** before first
  run. (Charlie: the route is reachable — this Claude Code session uses it.)

### Two script defaults that WOULD misconfigure (overridden in env)
- `FALDA_URL` defaults to `:8078`; our gateway is **:8077**.
- `DISTILLER_MODEL` defaults to `gpt-4o-mini`; must be **claudeopus47**.
Both set in `services/distiller/distiller.env.template` →
`~/.config/falda/distiller-luoji.env` (0600). Recorded as FALDA findings.

### No vLLM fallback — already correct
On an Argo error the script logs + returns 0 for that tier and retries next poll
— exactly the plan's "retry/resume, not fall back to vLLM." No patch needed.

### Shadow-vs-live nuance (important, per-tenant)
The script docstring says distilled atoms are "pure shadow." True for **luoji**
(no memory provider) but **NOT for gandalf** — the 5c provider's prefetch reads
gandalf atoms, so a gandalf distiller would feed the live agent. So **luoji is
the clean VERIFY 6 target**, and a gandalf distiller is deferred as part of the
5c experimental surface (not turned on blindly).

### VERIFY 6 — GREEN (quality judged, not just mechanism)
`--once` backfill over luoji: **121 turns → 14 atoms → 1 scene → 1 core**, all
tiers via Opus. Atoms are genuinely sensible and correctly typed:
- persona: "LuoJi operating under the OpenClaw gateway, identity-linked to
  ChatCeC"; "Charlie uses codeword TANGERINE-CANYON for LUOJI" (the real Phase-4
  codeword, distilled from captured history).
- instruction: "when smoke tests pass, skip DM and proceed to Step 6/7";
  "consolidate duplicate health reports into one alert."
- episodic: the real 2026-07-10 consolidated-health-alert incident, with
  root-cause detail.
No pleasantries/transient chatter. `/atoms/search tenant=luoji` returns
score-ranked hits. T2 scene = coherent narrative of the incident; T3 core = a
usable persona profile (Identity/Environment/Preferences/Constraints).

### New finding
- T3 core came wrapped in a ```` ```markdown ```` fence the L3 prompt didn't ask
  for (cosmetic; the model added a code fence). Noted in FALDA-FINDINGS.

### Continuous unit installed
`services/distiller/falda-distiller-luoji.service` (`--user`, `Restart=always`,
stdlib python3) enabled + active (PID confirmed, clean loop: falda=:8077
tenant=luoji model=claudeopus47 L1_EVERY_N=10 L2=3600s L3=21600s poll=120s).
The `--once` run already advanced the checkpoint
(`~/.falda/distiller_state-luoji.json`: 14/1/1), so the loop won't re-distill the
backfilled turns — only new ones.

### Not done / deferred
- **gandalf distiller instance** — deliberately NOT started (would feed the live
  5c agent). Decide separately.
- Distiller is now a 5th self-sustaining `--user` service alongside
  ollama/falda-gateway/tap-luoji/tap-gandalf.

---

## Phase 7 — Sibline broker (NATS + JetStream) — ✅ VERIFY 7 GREEN (2026-07-29)

The "S" of FUS. NATS + JetStream broker for background agent-to-agent
coordination. Shared substrate → `spark-fabric/services/nats/`. Loopback-only.

### Cloned the reference
`~/code/Sibline` pin **`cab044f`** (rick-stevens-ai/Sibline) — un-vendored, like
falda. Adapted its `broker/nats-server.conf`, `provision-streams.sh`,
`scripts/smoke.py`. The plan's `falda/deploy/nats/` fallback also exists but the
Sibline artifacts are the canonical source.

### Binaries (pinned, no root)
nats-server **v2.14.3** + natscli **v0.4.0**, linux-arm64, to `~/opt/nats/bin/`.
Queried the GitHub releases API for real asset names (didn't guess URLs).
Checksums recorded in `services/nats/README.md`.

### Config — generic + secret-free (committable)
`services/nats/nats-server.conf`: bind `127.0.0.1:4222`, monitoring
`127.0.0.1:8222`, JetStream file store. **Every runtime value is a `$VAR`** —
nats-server expands env in strings, PATHS, and passwords (verified with a
correct-vs-wrong-password probe). So the committed conf has NO secrets and NO
machine paths; the `--user` unit injects them:
- secrets from `~/.config/sibline/cred` (0600, gitignored-by-location — it's in
  `~/.config`, outside every repo): `NATS_ADMIN_PASS`, `GANDALF_NATS_PASS`,
  `LUOJI_NATS_PASS` (32-char random each).
- paths via `Environment=` (`SIBLINE_STORE_DIR=~/.sibline/jetstream`,
  `SIBLINE_LOG_FILE=~/.sibline/logs/nats.log`).

### Deltas from Rick's reference (all deliberate)
loopback (not tailnet); users gandalf/luoji (not kukla/ollie); streams
sibline-gandalf/luoji/broadcast; `--user` unit + `~/.sibline/` (not root +
`/var/lib/sibline`); `$VAR` secrets (not inline REPLACE_ME).

### The `$JS.>` grant (the plan's headline gotcha) — got it right first time
Each agent user has `publish` on `sibline.>`, `_INBOX.>`, **and `$JS.>`**.
Confirmed working: smoke.py publish + stream_info both succeed (the ack-publish
path is what `$JS.>` gates).

### VERIFY 7 — PASS
- `sibline-broker.service` (`--user`, Restart=always) active; JetStream up;
  listening `127.0.0.1:4222` + `:8222`, both loopback (confirmed via `ss`).
- 3 streams created (`nats stream ls`): sibline-gandalf, sibline-luoji,
  sibline-broadcast (file, 7d/10k/1MB, discard old, 2m dupe window).
- `smoke.py` PASS for BOTH agents: publish acked (seq=1), JetStream stored,
  stream_info readable. Smoke probes then purged → all streams back to 0 msgs.
- **Sandbox reachability of :4222 — confirmed UNREACHABLE (the plan's `[ASSUMED]`,
  now proven):**
  - `host.openshell.internal:4222` → `Connection refused` (no socat bridge; NATS
    deliberately has none, unlike FALDA's 5a bridge).
  - `127.0.0.1:4222` from sandbox → `Connection refused` (sandbox loopback ≠ host).
  - Faithful principal path `nemohermes gandalf exec … curl …:4222` → **403**
    (no egress policy for 4222).
  This is exactly why Gandalf needs the host-side FILE BRIDGE (Phase 8b), not
  direct NATS. Luoji is native → speaks NATS directly (Phase 8a).

### Now 6 self-sustaining `--user` services
ollama, falda-gateway, tap-luoji, tap-gandalf, distiller-luoji, **sibline-broker**.

### Reconnect-zombie gotcha (recorded for Phase 8)
py-nats durable subscribers don't survive a broker TCP reconnect (silently stop
delivering). After ANY broker ACL/config change: restart the broker, THEN every
subscriber unit. To be baked into the Phase 8 runbook.

### Next: Phase 8 — subscribers
8a Luoji direct (native NATS, `~/.sibline/venv`, durable `luoji-inbox-durable`).
8b Gandalf host-side bridge (file mailbox ↔ sandbox via docker exec, modeled on
`Spark-Hermes/ops/outbox-processor.sh`) — lives in Spark-Hermes.

---

## Phase 8 — Subscribers — ✅ VERIFY 8 GREEN (2026-07-29)

Both sandboxed agents now exchange messages over Sibline via host-side NATS
bridges. Full bidirectional A2A proven, neither agent touching Telegram/Slack.

### The direct-NATS spike (Charlie's "can we do the Slack trick?") — answered NO
Charlie noted Slack reaches the sandbox in real time (no cron) and asked whether
NATS could use the same path. Investigated the actual mechanism: Slack is
**Socket Mode = WebSocket-over-TLS on 443**, which the OpenShell L7 proxy
natively tunnels (`protocol: websocket` in slack.yaml). Evidence suggested the
proxy also does raw L4 tunnels (`access: full` / `tls: skip`, used by brew/github
— but those are TLS/443 too). **Spiked it:** socat bridge `172.19.0.1:4222` +
an `access: full`/`tls: skip` egress policy (v10), probed from inside the sandbox
via the faithful principal path. **Verbose socat proved the raw NATS SYN never
arrived** — the proxy silently drops plain (non-TLS, non-443) TCP. So the plan's
original "raw TCP can't cross the sandbox proxy" is CONFIRMED, and the Slack trick
needs WebSocket/TLS which NATS isn't. Spike fully torn down; verified FALDA (5c)
egress still works (only the sibline preset was removed). ~20 min, well spent.

### Plan correction: BOTH agents need a bridge (not just Gandalf)
Phase 8a says "Luoji is native, speaks NATS directly." Wrong — same Phase-0
finding: Luoji is sandboxed, his sandbox also can't reach :4222. So both get a
host-side bridge; they differ only in the last delivery hop.

### Architecture (host-side, file-shuttle across the sandbox barrier)
`services/sibline-bridge/sibline_bridge.py` — generic per-agent daemon (runs in
`~/.sibline/venv`): durable JS consumers on `sibline.<self>.inbox` +
`sibline.broadcast` → appends non-noise to a mailbox JSONL; auto-pongs `kind=ping`
(no agent wake); watches an outbox dir → publishes agent-dropped `*.json`
(SYMMETRY RULE: durable file first, then best-effort publish → `sent/`). Includes
the nats-py N-digit-microsecond timestamp shim (the plan's Python gotcha).

Delivery differs per agent (verified both surfaces):
- **Luoji** — `/workspace` is a live host bind-mount, so the bridge writes the
  mailbox straight into `~/code/spark-ai-agents/luoji/sibline/` → sandbox sees it
  at `/workspace/sibline/` instantly. NO docker exec. Unit: spark-fabric
  `sibline-bridge-luoji.service`.
- **Gandalf** — `/sandbox/.hermes` is overlay (no bind), so the bridge stages to
  host `~/.sibline/mailbox-gandalf.jsonl` and a **docker-exec shuttle**
  (`Spark-Hermes/ops/sibline-shuttle.sh` + `gandalf-sibline-shuttle.service`,
  modeled on outbox-processor.sh, offset-tracked no-dupe) syncs it in/out of
  `/sandbox/.hermes/sibline/`. Units: spark-fabric `sibline-bridge-gandalf.service`
  + Spark-Hermes shuttle.

### Boundary decision (flagged to Charlie)
CLAUDE.md says "the file bridge is Gandalf-specific → Spark-Hermes; Luoji must not
inherit it." That rule's premise (Luoji native) is false. Followed the falda-tap
precedent instead: the GENERIC bridge is shared substrate → spark-fabric
(both agents' feeders sit together, as the taps do). Only Gandalf's docker-exec
SHUTTLE is agent-specific → stays in Spark-Hermes. Reversible via git mv.

### VERIFY 8 — PASS (all three)
1. Luoji→Gandalf `kind=message` → landed in the GANDALF SANDBOX inbox
   (`/sandbox/.hermes/sibline/inbox.jsonl`) via broker→bridge→shuttle.
2. Gandalf→Luoji from INSIDE the sandbox (dropped `outbox/reply1.json`) → full
   round-trip: shuttle out → bridge publish → luoji bridge → his `/workspace`.
   A complete bidirectional A2A exchange, both sandboxed, no Telegram/Slack.
3. Auto-pong symmetry both directions (ping→pong with correct `reply_to`,
   answered by the peer's bridge daemon, no agent wake).
Restart-safe: bounced all 3 units → still exactly one durable consumer each (no
reconnect zombies). Test data purged from streams + mailboxes afterward.

### Reconnect-zombie runbook — in services/sibline-bridge/README.md
After ANY broker ACL/config change: restart broker, THEN all 3 subscriber units;
verify a single durable consumer each.

### Now 9 self-sustaining --user services
ollama, falda-gateway, tap-luoji, tap-gandalf, distiller-luoji, sibline-broker,
sibline-bridge-luoji, sibline-bridge-gandalf, gandalf-sibline-shuttle.

### Known limitation (honest)
Inbound to an agent lands in a mailbox file; it does NOT wake a live agent turn —
the agent surfaces it on its next turn / poll. Auto-pong (liveness) is instant.
Active "push into a live turn" is beyond VERIFY 8 and touches agent-side config.

### Next: Phase 9 — end-to-end (the 6 checks) then extend ops/status.sh + post-rebuild.sh.

---

## Phase 9 — End-to-end — ✅ VERIFY 9 GREEN, all 6 checks (2026-07-29)

The whole point. All six plan checks pass:

1. **A2A over Sibline both ways** ✓ — Gandalf (from inside his sandbox) → Luoji's
   `/workspace`, then Luoji → Gandalf's sandbox inbox. Neither via Telegram/Slack.
2. **Both agents captured to own FALDA tenants** ✓ — taps active, checkpoints
   advancing (luoji stream=132, gandalf stream=408 at check time).
3. **Luoji shared-corpus fact readable by Gandalf** ✓ — seeded a fact as
   tenant=luoji pool=shared-corpus; Gandalf read it back through the pool.
4. **Gandalf-private NOT visible to Luoji** ✓ — a gandalf-tenant secret was
   absent from BOTH Luoji's private search and the shared pool; control confirmed
   Gandalf sees his own. Isolation holds. (Test atoms cleaned after.)
5. **Survives reboot** ✓ — all 9 --user units are active AND enabled, and
   `Linger=yes` (units start at boot without login). Enablement + linger is the
   accepted proxy; an actual reboot is Charlie's call.
6. **One-command health** ✓ — new `spark-fabric/ops/status.sh` reports the whole
   substrate (9 services + FALDA/embedder + Sibline streams/consumers) → ALL
   GREEN, exit 0.

### ops/status.sh — new, fabric-wide (check 6)
Put the substrate health check in **spark-fabric** (not bloating Spark-Hermes's
Gandalf-only status.sh). Covers: every --user unit active+enabled, linger on,
FALDA healthz, embedder version, per-tenant stream/atom counts, broker listening,
all 3 streams present, durable consumers single (reconnect-zombie guard). Exit
non-zero on any failure.

### post-rebuild.sh — extended for Sibline (Spark-Hermes)
Added step 5c: a sandbox rebuild wipes the overlay `/sandbox/.hermes/sibline/`
tree and changes the container id; the host-side broker/bridge survive (--user),
but the docker-exec shuttle caches the container name at launch, so it's
restarted to rebind + recreate the tree. (FALDA egress preset already restored by
apply-policies.sh; the sibline broker is loopback host-side, no sandbox egress.)

### FUS COMPLETE: F✅ S✅ (U is Phase 10, optional)
9 self-sustaining --user services; both sandboxed agents share memory (FALDA +
shared-corpus pool + distillation) and coordinate over a message bus (Sibline),
all self-hosted and loopback-only. The core deliverable of the plan is met.

### Next: Phase 10 — UMP (OPTIONAL, memory interchange format / MCP server).
Note the known port collision: plan's example wants :4000 but LiteLLM owns it.

---

## Phase 10 — UMP (memory interchange format) — ✅ VERIFY 10 GREEN (2026-07-30)

Charlie: "replicating Rick's environment, shouldn't stop short at FS — do UMP."
Agreed. UMP is the memory INTERCHANGE FORMAT (MCP server) complementary to
FALDA's engine; makes a fact portable/cross-tool. Deliverables in
`spark-fabric/services/ump/`.

### Install + pins
`@universalmemoryprotocol/core` v0.2.0 (npm, MIT) global under nvm node v22.22.3
(engines node>=20; system v18 would fail — same pin as FALDA). Bins ump/
ump-memory/ump-serve/ump-import/ump-conformance. Server conformance UMP 0.1 / L2.

### 🐞 Finding (checked the artifact) — UMP binds 0.0.0.0
`ump memory --http <port>` calls `.listen(port)` with NO host → binds all
interfaces. UMP has no transport auth (owner scope only), so on this box
(Tailscale + LAN) the store would be off-box reachable. Same class as FALDA
BUG-1. UMP is a GLOBAL npm package, so patching dist/ is not rebuild-safe —
instead wrote `services/ump/ump-memory-loopback.mjs`, a faithful reimpl of the
`memory` bin that imports the package's public API (UmpServer, createHttpServer,
JsonFileStore, JsonlAuditLog, generateKeyPair) and calls `.listen(port,
"127.0.0.1")`. Verified: binds 127.0.0.1 only; LAN IP refuses. Suggested upstream
fix: `--host`/`UMP_HOST`, default loopback. (Candidate report for UMP maintainers,
in services/ump/README.md.)

### Wrapper resolution gotcha
ESM `import "@universalmemoryprotocol/core"` can't resolve a GLOBAL package from
an out-of-tree script (NODE_PATH doesn't help ESM). Fixed by importing the
absolute `dist/index.js` via `UMP_CORE_INDEX` (derived from `npm root -g`).

### Port + owner
- Port **:4100** (plan's :4000 is taken by LiteLLM — confirmed PID 2507).
- ONE shared `did:key` owner for BOTH agents (per plan):
  `did:key:z6Mksh6F8K7vFaPpzmstzqR2Fj9zaWwJpHC5q1QCVAYFDqbw`. Seed in
  `~/.ump/key.json` (0600). Both agents will use this same owner so memory is
  interchangeable. Store `~/.ump/memory.ump.json` (portable JSON), audit
  `audit.log.jsonl`.

### VERIFY 10 — PASS (all three)
- Conformance `ump-conformance http://127.0.0.1:4100` → **UMP 0.1 / L2, 12/13**
  (the one miss is L3 capability_tokens, above the L2 target — fine).
- Wrote a `semantic` record under the shared owner (routes are `/ump/*`, e.g.
  `/ump/remember`; schema needs `body.text`, kind∈semantic|episodic|procedural|
  working|identity, scope.visibility∈private|shared|public), recalled it back via
  `scope.owner`. **`scope.owner` mandatory confirmed:** omitting it → `{"results":
  []}` (silent empty, no error — the plan's warning, verified).
- `~/.ump/memory.ump.json` is self-describing plain JSON, copyable to another
  machine; a recall by the shared owner resolves it → what one agent writes under
  the owner, the other reads. Test record tombstoned after (UMP bitemporal
  soft-delete — stays in file marked forgotten, correct).
- Loopback bind verified via `ss` + LAN-IP refusal.

### Unit + status
`ump-memory.service` (--user, nvm-node-pinned) active+enabled. Added UMP to
`spark-fabric/ops/status.sh` (loopback-bind assertion + well-known/conformance).
Now **10 self-sustaining --user services**; fabric status = ALL GREEN.

### Not done — agent MCP wiring (deliberate, more invasive)
Making the agents USE UMP live = registering the server in each agent's MCP
config (Hermes `mcp_servers`, OpenClaw MCP). Touches agent-repo config; a
follow-up. Phase 10 delivers the substrate (server + shared owner + portable
store + L2 conformance). `ump import --owner <did> gandalf/soul/*.md` can seed.

## 🎉 FUS COMPLETE: F✅ U✅ S✅
All three of Rick's components replicated, self-hosted, loopback-only:
FALDA (memory engine + shared pool + distillation), UMP (interchange format),
Sibline (message bus). 10 self-sustaining --user services. Both sandboxed agents
share memory and coordinate. Phase 10 was the last plan phase.
