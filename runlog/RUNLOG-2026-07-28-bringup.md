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
