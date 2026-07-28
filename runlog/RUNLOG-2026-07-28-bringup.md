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
