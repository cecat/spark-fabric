# Master plan — the Spark agent fabric

**Audience:** Claude Code running on `spark-960b`, with the operator (Charlie)
available but intentionally not in the loop for routine decisions.

**Goal:** give Charlie's two agents — **Gandalf** (Hermes, sandboxed) and
**Luoji** (OpenClaw, native) — a shared long-term memory (FALDA) and a
background agent-to-agent message bus (Sibline), both self-hosted on this box.

**Scope of this pass:** FALDA first, verified end-to-end, then Sibline, then
UMP. Both agents are in scope. Rick Stevens' agents (Kukla, Ollie) are
explicitly **out** — this is a local-only deployment. Federating with Rick's
hosts comes later and is additive.

---

## Which repo does each thing land in?

Charlie's work is split across four repos. **The boundary is ownership, not
convenience.** Getting a file into the wrong one is the single easiest way to
make this unmaintainable, so check this table before creating anything.

| Repo | Holds | In this plan |
|---|---|---|
| **`spark-fabric`** *(new)* | Shared substrate both agents consume: FALDA gateway, embedder, NATS broker, distiller, UMP. Config templates, systemd units, provisioning scripts, this plan. | Phases 0–3, 6, 7, 10 |
| **`Spark-Hermes`** | Gandalf: Hermes gateway, OpenShell sandbox, his `soul/` + `skills/`, egress policies, apply scripts. | Phase 5 (all sub-steps), phase 8b |
| **`spark-ai-agents`** | Luoji: OpenClaw agent folders, runbooks, `.md` files. | Phase 4, phase 8a |
| **`spark-ai`** | OpenClaw gateway + vLLM. Shared services — **connect/read only, never restart.** | No changes |

Three rules that follow from the table:

- **Nothing agent-specific goes in `spark-fabric`.** If it mentions OpenShell,
  a sandbox, `docker exec`, or a Hermes/OpenClaw config key, it belongs in that
  agent's repo.
- **Nothing shared goes in an agent repo.** If both agents would need it, it
  belongs in `spark-fabric`.
- **The sibline file-mailbox bridge is Gandalf-specific.** It is a workaround
  for the sandbox, not a standard integration path. It goes in `Spark-Hermes`.
  Luoji speaks NATS directly and must not inherit it.

`spark-fabric` is being created and cloned by Charlie in parallel with this
work; assume it exists at `~/code/spark-fabric` and is empty apart from a
README.

### Task for every repo: a "Related repos" table

Early on — it makes everything after it easier to navigate — add a short
**Related repos** section to the README of **all four**, each listing the other
three with one line on what lives where. Same table in each, so orientation
takes thirty seconds instead of a grep across four checkouts.

---

## How to work this plan

**Read this section before doing anything.**

1. **Phases are gated.** Each ends with a `VERIFY` block containing a command
   and its expected output. Do not start phase N+1 until phase N's verify
   passes. If a verify fails, stop and report — do not work around it.

2. **Verify assumptions before building on them.** This plan marks every
   uncertain claim `[ASSUMED]`. Those are *hypotheses*, not facts. Confirm each
   against the actual system before depending on it. See
   `Spark-Hermes/docs/HERMES-LOAD-PATHS.md` for what happened last time that
   repo built on an unverified assumption — six weeks of edits into a directory
   nothing read. The method that caught it: find the loader, read the call
   chain, prove it with a canary.

3. **Nothing hand-configured on the box.** Config templates, systemd units, and
   apply scripts go in a repo — the one the table above says. Secrets go in
   `0600` files outside every repo. If a rebuild would lose it, it belongs in
   version control.

4. **Snapshot before touching an agent's stack.**
   `bash Spark-Hermes/ops/snapshot.sh pre-fabric` before phase 5. Luoji's stack
   is at `~/code/spark-ai*` — copy any file you modify there before modifying
   it. Do not restart vLLM or argo-shim: shared services, and argo-shim's SSH
   tunnel needs a human Duo approval to re-establish.

5. **Report at each phase boundary** with: what verified, what surprised you,
   what you had to decide. Keep a running log at
   `spark-fabric/runlog/RUNLOG-<date>-bringup.md`, in the style of the runlogs
   in `Spark-Hermes/runlog/`.

6. **Do the two agents in the order given.** Luoji (phase 4) before Gandalf
   (phase 5) — deliberately. Luoji is native, unsandboxed, and therefore the
   clean place to prove the FALDA capture pattern. Gandalf adds egress policy,
   a memory provider, and a file bridge on top. Proving one unknown at a time
   is the whole point.

---

## Reference material

Clone both repos to `~/code/` and read them. They are the source of truth;
this plan is the Linux/sandbox adaptation.

| Repo | URL | License |
|---|---|---|
| FALDA | `https://github.com/rick-stevens-ai/falda` | Apache-2.0 |
| FALDA demo | `https://github.com/rick-stevens-ai/falda-demo` | — |
| Sibline | `https://github.com/rick-stevens-ai/Sibline` | MIT |

**Read first, in this order:**

- `falda/README.md` — four tiers, env vars, quick start
- `falda/docs/HARNESS_INTEGRATION.md` — **the most important document.** Rick's
  own production recipe for wiring Hermes *and* OpenClaw to FALDA, plus the
  NATS broker deploy. Written for macOS/launchd; we translate to
  Linux/systemd.
- `falda/docs/API.md` and `falda/docs/POOLS.md` — route table, multi-tenancy
- `falda/KUKLA_DELTA.md` — Kukla's changes; may contain deployment detail
- `Sibline/ARCHITECTURE.md` and `Sibline/spec/sibline-v1.md` — wire protocol
- `Sibline/broker/systemd.sibline-broker.service` — a Linux unit already exists

### UMP — a third component, and not Rick's

UMP is **not** Rick's project and is not on his GitHub. It is an independent
open standard by Edi Hasaj:

- Site: <https://universalmemoryprotocol.io>
- Repo: <https://github.com/edihasaj/universal-memory-protocol>
- Package: `@universalmemoryprotocol/core` (npm, v0.2.0, MIT, public)

Its own framing: *MCP standardizes tool access, A2A standardizes agent
coordination, UMP standardizes memory **portability**.* One record format, six
operations (`recall`, `remember`, `get`, `revise`, `forget`, `feedback`), stored
as a portable signed file (`~/.ump/memory.ump.json`) with a `did:key` owner
identity. Conformance tiers L0–L3.

**FALDA and UMP are complements, not alternatives.** FALDA is a memory *engine*
— tiering, distillation, hybrid search. UMP is a memory *interchange format* —
so a fact learned in one tool is readable by another. Installing both is
coherent; see phase 10.

UMP ships as an MCP server, which is the entire integration:

```
npx -y @universalmemoryprotocol/core ump-memory
```

---

## Target architecture

Everything runs on `spark-960b`. Nothing is exposed off-box.

```
                        HOST (spark-960b, Ubuntu 24.04, aarch64)
  ┌──────────────────────────────────────────────────────────────────────┐
  │                                                                      │
  │  Ollama :11434 ──embeddings──┐                                       │
  │  vLLM   :8000  ──chat────────┤                                       │
  │                              ▼                                       │
  │                    FALDA gateway :8077  (127.0.0.1 only, NO AUTH)     │
  │                       ├── tenant: gandalf                            │
  │                       ├── tenant: luoji                              │
  │                       └── pool:   shared-corpus                      │
  │                              ▲                                       │
  │            ┌─────────────────┼─────────────────┐                     │
  │            │                 │                 │                     │
  │       falda_tap          falda_tap        falda_distiller            │
  │       (luoji)            (gandalf)        (T0→T1→T2→T3)              │
  │            ▲                 ▲                                       │
  │            │                 │                                       │
  │  NATS :4222 (sibline)        │                                       │
  │     ├── sibline.gandalf.>    │                                       │
  │     ├── sibline.luoji.>      │                                       │
  │     └── sibline.broadcast    │                                       │
  │            ▲                 │                                       │
  │            │           sibline-bridge (host-side)                    │
  │       Luoji (OpenClaw)       │  file mailbox JSONL                   │
  │       ~/code/spark-ai*       │  in/out via docker exec               │
  │       native, direct NATS    │                                       │
  │                              ▼                                       │
  │   ┌──────────────────────────────────────────────┐                   │
  │   │ OpenShell sandbox: openshell-gandalf-*        │                   │
  │   │   Gandalf / Hermes v0.14.0                    │                   │
  │   │   egress ONLY via L7 proxy 10.200.0.1:3128    │                   │
  │   │   → FALDA reachable via egress policy         │                   │
  │   │   → NATS NOT reachable (see below)            │                   │
  │   └──────────────────────────────────────────────┘                   │
  └──────────────────────────────────────────────────────────────────────┘
```

### The one architectural decision that differs from Rick's setup

Rick's agents run natively on macOS. **Gandalf does not** — he's inside an
OpenShell sandbox whose only egress path is an L7 HTTP proxy at
`10.200.0.1:3128`, governed by allowlist presets in
`bringup/50-openshell-policies/`.

Consequences:

- **FALDA works from the sandbox.** It's HTTP/JSON, which the L7 proxy can
  express. Needs an egress preset (phase 5a).
- **NATS almost certainly does not.** NATS is raw TCP on 4222. The OpenShell
  policy schema is `protocol: rest` with HTTP method/path rules — there is no
  evident way to express a raw TCP tunnel. `[ASSUMED]` — verify in phase 7, but
  plan for it being true.

**Therefore Gandalf never speaks NATS.** Instead, a host-side bridge runs the
Sibline subscriber, writes to a file mailbox, and moves that mailbox in and out
of the sandbox. This is not a hack — `HARNESS_INTEGRATION.md` describes exactly
this file-mailbox bridge as a standard component; we make it Gandalf's primary
path rather than a fallback.

**Mirror the pattern already working in `Spark-Hermes`:**
`ops/outbox-processor.sh` is a host-side cron job that reads and writes
`/sandbox/.hermes/outbox/` via `docker exec -u sandbox`. The sibline bridge is
the same shape, and belongs in the same repo. Read that script before writing
the bridge.

---

## Phase 0 — Discovery and repo scaffolding

Establish facts, then lay down the repo structure. No services yet.

**0a. Scaffold `spark-fabric`.** The repo exists at `~/code/spark-fabric` and
already contains `README.md` and this plan at `docs/PLAN-FALDA-SIBLINE.md`.
Create the rest of the directory skeleton from the Deliverables section below
(`services/`, `ops/`, `runlog/`) and commit.

**0b. Related repos tables.** `spark-fabric/README.md` already carries the
table. Copy the same one into the READMEs of `Spark-Hermes`, `spark-ai-agents`,
and `spark-ai`. Do this now, not at the end: everything after is easier to
navigate with it in place, including for whoever picks this up next.

**0c. Inventory the box.**

```bash
# Interpreters and toolchain
node --version; which -a node; npm --version
python3 --version; ls /usr/bin/python3.*
docker --version; systemctl --version | head -1

# GPU / memory headroom for an embedding model
nvidia-smi --query-gpu=memory.total,memory.used --format=csv
free -g

# Ports must be free: 8077 (falda), 4222 (nats), 11434 (ollama)
ss -ltnp | grep -E ':(8077|4222|11434|8222)\b' || echo "all free"

# The sandbox container name (used throughout)
docker ps --format '{{.Names}}' | grep '^openshell-gandalf-'

# Luoji's OpenClaw layout — CONFIRM these paths, don't assume
ls -d ~/code/spark-ai*
ls ~/.openclaw/ 2>/dev/null
ls ~/.openclaw/sessions/ 2>/dev/null | head

# UMP (expect 0.2.0 or later — public, MIT)
npm view @universalmemoryprotocol/core version

# LiteLLM's port — the distiller's route to Argo/Opus in phase 6
systemctl --user status gandalf-litellm.service --no-pager | head -5
ss -ltnp | grep -i litellm
```

**Record in the runlog:**

- node version **and absolute path** — phase 2 needs it pinned for the
  `better-sqlite3` ABI
- which Python ≥3.11 exists — phase 8
- the `openshell-gandalf-*` container name
- Luoji's real session-log directory — phase 4
- LiteLLM's listening port — phase 6

> **VERIFY 0:** all four repos have a Related repos table. `spark-fabric` has
> its skeleton committed and holds this plan. The runlog records every item
> above. Ports 8077/4222/11434 are free and a `python3.11+` exists.

---

## Phase 1 — Embeddings (Ollama + nomic-embed-text, local)

FALDA needs an OpenAI-compatible `/v1/embeddings` endpoint. **This is a
different model from the one that does the reasoning**, and the two decisions
are independent:

| | Distiller (chat) | Embedder |
|---|---|---|
| Job | read transcripts, write facts/summaries | turn text into a vector |
| Quality sensitivity | very high — real reasoning | low — no generation |
| Call frequency | background, every ~10 turns | **every read and every write** |
| Survives an outage? | yes, it's a batch job | no — memory stops |

**Decision: embedder local, distiller remote via Argo.** Two reasons, one of
them hard:

1. **argo-shim cannot serve embeddings.** This deployment reaches Argo through
   [`argo-shim`](https://github.com/n-getty/argo-shim) at `127.0.0.1:44497`,
   which speaks the **Anthropic Messages API**. Anthropic has no embeddings
   endpoint — the shape simply doesn't exist in that API. Whatever Argo offers
   upstream, this path can't carry it. (Other Argonne bridges —
   `argo-proxy`, `argo_bridge` — are OpenAI-shaped and *do* expose
   `/v1/embeddings`; adopting one is a separate project, not a prerequisite.)
2. **Embeddings must stay consistent.** Vectors from different models are not
   comparable. Embed with model A, search with model B, and recall returns
   plausible nonsense with no error. So this component can't fail over — pinning
   it locally removes that whole class of failure for ~275MB.

An embedding model is not an LLM. `nomic-embed-text` does one forward pass and
emits 768 numbers; it runs fine on CPU. The "local Qwen is much weaker than
Opus" concern is real and applies to the **distiller** (phase 6), not here.

1. Install Ollama (aarch64 Linux build) and enable its systemd unit.
2. `ollama pull nomic-embed-text`
3. Bind to `127.0.0.1:11434` only.

> **VERIFY 1:**
> ```bash
> curl -s http://127.0.0.1:11434/v1/embeddings \
>   -H 'Content-Type: application/json' \
>   -d '{"model":"nomic-embed-text","input":"cryostat target temperature"}' \
>   | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["data"][0]["embedding"]))'
> ```
> Expected: `768`. If a different number, set `FALDA_DIM` to match it in phase 2
> — the dimensionality must agree or recall silently degrades.

---

## Phase 2 — FALDA gateway

```bash
git clone https://github.com/rick-stevens-ai/falda ~/code/falda
cd ~/code/falda
npm ci
npm rebuild better-sqlite3
```

> **GOTCHA — native ABI.** `better-sqlite3` is a native module. The node that
> runs `npm ci` / `npm rebuild` **must** be the node the gateway runs under, or
> you get `ERR_DLOPEN_FAILED` (NODE_MODULE_VERSION mismatch). Pin the absolute
> node path from phase 0 in the systemd unit's `ExecStart`. Do not rely on
> `PATH`.

Create a **systemd unit** (translate `deploy/launchd/com.stevens.falda-gateway.plist.template`).
Prefer a `--user` unit under `~/.config/systemd/user/` for consistency with the
existing vLLM bridge units — check `bringup/40-vllm-bridge/` and match whatever
that does.

Environment:

```
FALDA_PORT=8077
FALDA_DB=~/.falda/falda.db
FALDA_BLOBS=~/.falda/blobs
FALDA_EMBED_BASE_URL=http://127.0.0.1:11434/v1
FALDA_EMBED_API_KEY=x
FALDA_EMBED_MODEL=nomic-embed-text
FALDA_DIM=768
```

> **SECURITY — FALDA has no authentication of its own.** Bind to `127.0.0.1`
> only. Never expose it on the tailnet or the public internet. The sandbox
> reaches it through the OpenShell proxy (phase 5a), not by the gateway being
> publicly bound.

Commit the env template, the systemd unit, and a README to
`spark-fabric/services/falda/`. The FALDA checkout itself
(`~/code/falda`) stays out of version control — record the pinned commit in the
README instead.

> **VERIFY 2:**
> ```bash
> curl -s localhost:8077/healthz
> npm run smoke      # in ~/code/falda — prints "ALL TIERS GREEN"
> ```
> Expected: `{"ok":true,"tiers":[...],"pools":true}` and `ALL TIERS GREEN`.

---

## Phase 3 — Tenants and the shared pool

Per `docs/POOLS.md`: **one tenant per agent identity. Two agents share memory
via an opt-in named pool, never by sharing a tenant.** Private memory stays
physically isolated in each tenant's `self` store.

- tenant `gandalf`
- tenant `luoji`
- pool `shared-corpus` — `{"gandalf": "readwrite", "luoji": "readwrite"}`

```bash
curl -s localhost:8077/pools/declare -d '{
  "name": "shared-corpus",
  "members": {"gandalf": "readwrite", "luoji": "readwrite"},
  "description": "facts both of Charlie'\''s agents contribute to and read"
}'
```

> **VERIFY 3:** write an atom to tenant `gandalf` with no pool; confirm a search
> as tenant `luoji` does **not** return it. Then write one to `shared-corpus`
> and confirm both tenants see it. Isolation is the whole point — prove it.

---

## Phase 4 — Luoji (OpenClaw) shadow capture

Start with Luoji: he's native on the host, so no sandbox complications. Get the
pattern working here before attempting Gandalf.

Use `integrations/external-source/falda_tap.py`. It tails the agent's L0 session
JSONL and forwards new turns to `/stream/add`, with a restart-safe byte-offset
checkpoint.

```
SOURCE_CONV_DIR=<Luoji's session dir, confirmed in phase 0>
FALDA_URL=http://127.0.0.1:8077
FALDA_TENANT=luoji
```

Install as a systemd unit (`Restart=always`). The tap is stdlib-only, so system
`python3` is fine — do **not** put it in the sibline venv.

> **SHADOW, NOT LIVE.** The tap captures in parallel with Luoji's existing
> memory. It does not change what Luoji recalls. Do not flip OpenClaw's
> `memory.provider` to falda in this phase. Prove capture first; going live is a
> later, separate decision.

> **VERIFY 4:** have a conversation with Luoji, then:
> ```bash
> curl -s 'localhost:8077/stream/search?q=<something you just said>&tenant=luoji'
> ```
> Expected: the turn comes back. Also confirm the checkpoint file advances and
> that restarting the tap does not duplicate turns.

---

## Phase 5 — Gandalf (Hermes, sandboxed)

The hard one. Three sub-steps, in order.

### 5a. Egress policy so the sandbox can reach FALDA

Add `bringup/50-openshell-policies/falda-local-egress.yaml` following the schema
of the existing presets (read `telegram-egress.yaml` — it's the cleanest
example). Then `bash ops/apply-policies.sh`.

**Which hostname?** The sandbox reaches host services by a specific name — the
vLLM bridge uses `http://host.openshell.internal:8000/v1`. Read
`bringup/40-vllm-bridge/` and `bringup/config.example.yaml` and mirror whatever
actually works there. `[ASSUMED]` that `host.openshell.internal:8077` is the
right target — verify with a curl from inside the sandbox before writing the
preset.

> **NOTE:** `Spark-Hermes/bringup/50-openshell-policies/falda-egress.yaml`
> already exists. That one targets **Rick's remote** FALDA proxy
> (`103.101.203.226:8444`) and is unrelated to this local deployment. Leave it
> alone; create a separate preset. Do not merge them.

> **VERIFY 5a:** from inside the sandbox:
> ```bash
> docker exec -u sandbox <container> curl -s http://host.openshell.internal:8077/healthz
> ```
> Expected: `{"ok":true,...}`. A `403` with `"error":"policy_denied"` means the
> preset didn't take — that's the L7 allowlist, not FALDA.

### 5b. Shadow capture for Gandalf

Find Hermes' L0 session log. `[ASSUMED]` it's under `/sandbox/.hermes/` — likely
a sessions or logs directory. Confirm by inspection.

Complication: the tap runs on the host, the logs are in the container. Two
options — pick based on what you find:

- **Preferred:** if the sandbox path is a Docker volume with a host-side path,
  point the tap at the host path directly. Cleanest, no bridging.
- **Otherwise:** a host-side poller that `docker exec`s to read new bytes, in the
  style of `ops/outbox-processor.sh`. Slower but works.

Tenant: `gandalf`.

> **VERIFY 5b:** talk to Gandalf in Telegram, then
> `curl -s 'localhost:8077/stream/search?q=<phrase>&tenant=gandalf'` returns it.

### 5c. Make FALDA Gandalf's actual memory

**Verified 2026-07-28:** `/opt/hermes/agent/memory_provider.py` **exists** in
this v0.14.0 install. Hermes has a real `MemoryProvider` abstract base class and
ships eight external providers. Earlier notes in `Spark-Hermes` claiming otherwise
were wrong — they were extrapolated from `tools/memory_tool.py`, which handles
only the *built-in* MEMORY.md/USER.md layer. An external provider runs
*alongside* that layer, not instead of it.

The ABC, read from source:

```python
# must implement
name                    -> str          # property
is_available()          -> bool
initialize(session_id: str, **kwargs)   -> None
get_tool_schemas()      -> List[Dict[str, Any]]

# override as needed (concrete defaults on the base)
system_prompt_block()   -> str
prefetch(query: str, *, session_id: str = "")       -> str
queue_prefetch(query: str, *, session_id: str = "") -> None
sync_turn(user_content: str, assistant_content: str, *, session_id: str = "") -> None
handle_tool_call(tool_name: str, args: Dict[str, Any], **kwargs) -> str
shutdown()              -> None

# optional hooks
on_turn_start / on_session_end / on_session_switch /
on_pre_compress / on_delegation / on_memory_write

# config
get_config_schema()     -> List[Dict[str, Any]]
save_config(values: Dict[str, Any], hermes_home: str) -> None
```

FALDA maps onto this almost one-to-one:

| Hermes hook | FALDA call |
|---|---|
| `sync_turn()` | `POST /stream/add` — every turn into T0 |
| `prefetch(query)` | `GET /stream/search` + `GET /atoms/search`, returned as a text block |
| `system_prompt_block()` | `GET /core/read` — the T3 core document |
| `get_tool_schemas()` / `handle_tool_call()` | explicit search tools for when the agent wants to dig |
| `on_session_end()` / `on_pre_compress()` | nudge the distiller |

**Order of work:**

1. `hermes memory status` and `hermes memory --help` — see what's configured and
   what the eight bundled providers are. Read one of them as a worked example
   before writing anything.
2. Find how a *custom* provider is registered (plugins directory, entry point,
   or config key). Follow the pattern the bundled ones use.
3. Write the FALDA provider. Tenant `gandalf`, pool `shared-corpus` for shared
   reads/writes, private `self` store otherwise.
4. **Shadow first.** Implement `sync_turn` (write) before `prefetch` (read).
   Confirm turns land in FALDA and that Gandalf still behaves normally, *then*
   turn on recall. One change at a time.
5. Keep the provider source in `Spark-Hermes`, pushed by an apply script — not
   hand-placed in the container, which a rebuild would wipe.

Also add `gandalf/skills/falda-memory/SKILL.md` documenting the HTTP surface for
explicit queries. Useful regardless, and it's the fallback if the provider work
stalls.

> **VERIFY 5c:** in a fresh session (`/new`), ask Gandalf something only FALDA
> would know — a fact from a *Luoji* conversation written to `shared-corpus` —
> **without** telling him to search. If he answers, prefetch is working and
> recall is automatic. If he only finds it when explicitly told to search, the
> provider isn't wired; report rather than papering over it with the skill.

---

## Phase 6 — Distiller (T0 → T1 → T2 → T3)

`falda_distiller.py` promotes raw stream turns into atoms, scenes, and core. It
only touches the documented HTTP API plus a chat endpoint.

**Use Argo (Claude Opus), not local vLLM.** Distillation is the one genuinely
hard reasoning job in this stack — deciding what's worth remembering, and
writing the persona core. Local Qwen at ~50 tok/s is not competitive here, and
unlike embeddings this is a background batch job that tolerates an outage by
catching up later.

The route already exists on this box:

```
falda_distiller.py  →  LiteLLM (OpenAI-shape)  →  argo-shim :44497 (Anthropic-shape)  →  Argo  →  Opus
```

`falda_distiller.py` wants an OpenAI-compatible `/v1/chat/completions`, and
LiteLLM is exactly the translation layer that provides it — see
`litellm/config.yaml`, model name `claudeopus47`.

```
LLM_BASE_URL=http://127.0.0.1:<litellm port>/v1
LLM_API_KEY=<whatever LiteLLM expects; the Argo route uses a dummy>
DISTILLER_MODEL=claudeopus47
L1_EVERY_N=10
L2_INTERVAL_S=3600
L3_INTERVAL_S=21600
```

**Discover the LiteLLM port** — `systemctl --user status gandalf-litellm.service`
and `ss -ltnp`. Use the explicit `claudeopus47` model name rather than the
`hermes-agent` alias, so re-pointing Gandalf's model later doesn't silently
change what the distiller runs on.

> Do **not** restart argo-shim or the SSH tunnel. Per
> `docs/KICKOFF-CLAUDE-CODE.md` these are shared services — connect only. The
> tunnel needs a human Duo approval to re-establish.

> If Argo is unreachable, the distiller should retry and resume, not fall back
> to vLLM. Mixed-quality atoms are worse than late atoms.

Run `--once` first as a backfill and read the output before installing the
continuous loop as a systemd unit. Checkpoint lives at
`~/.falda/distiller_state.json`.

> A fresh tenant with no atoms is expected and not a failure. Atoms appear after
> `L1_EVERY_N` new turns.

> **VERIFY 6:** after enough turns, `curl -s 'localhost:8077/atoms/search?q=...&tenant=luoji'`
> returns distilled facts, and the atoms are sensible rather than noise. If
> extraction quality is poor, the README notes large blobs cause
> under-extraction — reduce the window before blaming the model.

---

## Phase 7 — Sibline broker (NATS + JetStream)

Install `nats-server` (aarch64 Linux binary) and the `nats` CLI. Config from
`Sibline/broker/nats-server.conf` or
`falda/deploy/nats/nats-server.conf.template`.

- Listener: **`127.0.0.1:4222` plus the Docker bridge address** if the sandbox
  ever needs it. Monitoring on `127.0.0.1:8222` only. Not the tailnet — this is
  local-only for now.
- JetStream with file store under `~/.sibline/jetstream/`.
- Three users: `admin` (full `>`), `gandalf`, `luoji` (each scoped to `sibline.>`).

> **GOTCHA — the `$JS.>` grant.** Every agent user needs `publish: $JS.>` **in
> addition to** `sibline.>`. Without it, JetStream consumer and ack operations
> fail with "permission denied" — and the error points at *subscribe* while the
> missing grant is on the *ack publish* path. Rick's docs say this bites every
> new deployment once. Get it right the first time.

Install the systemd unit from `Sibline/broker/systemd.sibline-broker.service`,
then create the streams (`Sibline/broker/provision-streams.sh` or
`falda/deploy/nats/create-streams.sh`), renaming for our agents:
`sibline-gandalf`, `sibline-luoji`, `sibline-broadcast`.

Secrets: NATS passwords in a `0600` env file (e.g.
`~/.config/sibline/cred`), **never** in the repo or inline in the unit.

> **VERIFY 7:** `nats stream ls` shows three streams. `python3 Sibline/scripts/smoke.py`
> passes. Also confirm the `[ASSUMED]` claim about the sandbox: try reaching
> `4222` from inside the container. Expect failure — record the exact error.

---

## Phase 8 — Subscribers

> **GOTCHA — Python version.** The subscriber needs **3.11+** so
> `datetime.fromisoformat()` parses the broker's N-digit-microsecond timestamps
> natively. Use a dedicated venv (`~/.sibline/venv`) with `nats-py`. Do not use
> system Python and do not share the venv with the tap.

### 8a. Luoji — direct

Native on the host, so he speaks NATS directly. Adapt
`Sibline/clients/ollie-openclaw/`. Agent id `luoji`, durable consumer
`luoji-inbox-durable`, subjects `sibline.luoji.inbox` + `sibline.broadcast`.

### 8b. Gandalf — host-side bridge

Adapt `Sibline/clients/kukla-hermes/` (the canonical Hermes reference), but run
it **on the host, not in the sandbox**. It consumes `sibline.gandalf.inbox` +
`sibline.broadcast` and writes to a file mailbox. A second component moves that
mailbox into `/sandbox/.hermes/sibline/` via `docker exec`, and picks up
Gandalf's outbound messages the same way.

**Model this on `ops/outbox-processor.sh`** — same host↔sandbox file-shuttling
shape, already working in production here. Read it first.

> **SYMMETRY RULE.** Every send does **both** legs: write the durable file leg
> first, then publish to the broker best-effort. If A→B rides the broker but
> B→A only writes a file, you get a latency asymmetry that looks exactly like a
> bug. Both directions, same transport, every time.

> **GOTCHA — reconnect zombies.** py-nats durable subscribers do **not** survive
> the broker's TCP reconnect: they enter a "consumer exists, no active interest"
> state where messages queue but never deliver. After **any** broker ACL or
> config change: `kill -HUP <nats-server-pid>`, then restart every subscriber
> unit. Bake this into a `ops/` runbook so it isn't rediscovered painfully.

> **VERIFY 8:** `bash Sibline/scripts/verify-symmetry.sh` passes. Publish
> `kind=ping` to `sibline.gandalf.inbox`; confirm it lands in the sandbox
> mailbox file. Then the reverse.

---

## Phase 9 — End-to-end

The whole point. All of these must pass:

1. Gandalf sends a message to Luoji over Sibline; Luoji receives and replies;
   Gandalf sees the reply. Neither goes through Telegram or Slack.
2. Both agents' conversations are being captured into their own FALDA tenants.
3. A fact Luoji writes to `shared-corpus` is retrievable by Gandalf.
4. A fact in Gandalf's private tenant is **not** visible to Luoji.
5. Everything survives a reboot — `systemctl --user status` clean for every unit.
6. `bash ops/status.sh` reports healthy (extend it to cover the new services).

> **VERIFY 9:** all six. Then update `ops/post-rebuild.sh` so a sandbox rebuild
> restores the FALDA egress preset and the sibline bridge, and `ops/status.sh`
> so a human can see the whole stack's health in one command.

---

## Phase 10 — UMP (optional, after phase 9 is green)

FALDA is the memory *engine*; UMP is the memory *interchange format*. Adding it
means a fact Gandalf learns is portable — readable by another agent, another
vendor's tool, or a future stack — instead of living only in FALDA's SQLite.

It is the least invasive component here: an MCP server, and Gandalf's
`config.yaml` already has an `mcp:` block (`provider: auto`, no servers
configured). That empty block is the plug point.

```bash
npm install -g @universalmemoryprotocol/core
ump memory --http 4000        # MCP + HTTP bindings, store at ~/.ump
ump conformance http://localhost:4000
```

Notes:

- **One owner identity for both agents.** Generate a `did:key` once, store the
  key material in a `0600` file, and use the *same* owner for Gandalf and Luoji
  so their memories are genuinely interchangeable. Do not let each generate its
  own.
- **`scope.owner` is mandatory on recall.** Omit it and you get an empty result
  set with no error — the same silent-failure shape as everything else that bit
  this deployment. Bake it into every call.
- Expect conformance around **12/13 at L2**; investigate anything materially
  below that before wiring agents up.
- Wire into Hermes via `mcp_servers.ump` in `config.yaml`; OpenClaw has its own
  MCP equivalent for Luoji.
- The importers (`ump import`) can bootstrap from `CLAUDE.md` / `AGENTS.md` /
  Markdown directories — a reasonable way to seed the store from `gandalf/soul/`.

> **VERIFY 10:** `ump conformance` passes at L2. Write a memory as Gandalf, read
> it back as Luoji through the same owner, and confirm `~/.ump/memory.ump.json`
> is a portable file you could copy to another machine.

> **Do not put this before phase 9.** FALDA and Sibline are what make the two
> agents collaborate; UMP makes that collaboration portable later. Nothing
> depends on it.

---

## Deliverables, by repo

### `spark-fabric` — the shared substrate

```
README.md                    ← what the fabric is + Related repos table
docs/
  PLAN-FALDA-SIBLINE.md      ← this document, moved here
  TOPOLOGY.md                ← what runs where, ports, who talks to whom
services/
  falda/                     ← checkout notes, env template, systemd unit
  embedder/                  ← Ollama unit + model pin
  distiller/                 ← env template (LiteLLM→Argo), systemd unit
  nats/                      ← nats-server.conf template, stream provisioning
  ump/                       ← MCP server config, owner-DID setup notes
ops/
  apply-fabric.sh            ← render templates + install/restart units
  status.sh                  ← one-command health for the whole substrate
runlog/
  RUNLOG-<date>-bringup.md
```

Follow the conventions already proven in `Spark-Hermes/ops/` — `_lib.sh`-style
helpers, idempotent apply scripts, `--dry-run` where it's cheap.

### `Spark-Hermes` — Gandalf's integration

- `bringup/50-openshell-policies/falda-local-egress.yaml` — sandbox → FALDA
  *(distinct from the existing `falda-egress.yaml`, which points at Rick's
  remote proxy — do not merge them)*
- The **FALDA memory provider** for Hermes, plus an apply script that installs
  it into the sandbox
- `ops/sibline-bridge.sh` — host-side NATS↔file-mailbox shuttle, modelled on
  `ops/outbox-processor.sh`
- `gandalf/skills/falda-memory/SKILL.md`
- `ops/post-rebuild.sh` extended to restore the egress preset, the provider, and
  the bridge
- Related repos table in `README.md`

### `spark-ai-agents` — Luoji's integration

- The **FALDA memory provider plugin** for OpenClaw
  (`~/.openclaw/plugins/falda-memory/index.js` — versioned here, not
  hand-placed)
- Sibline subscriber config for agent id `luoji`
- Related repos table in `README.md`

### `spark-ai` — no changes

Gateway and vLLM are shared services. Connect and read only. Add the Related
repos table to its README and nothing else.

### Not in any repo

Every secret. NATS passwords, the UMP owner key, any API keys — `0600` files
under `~/.config/`, referenced by path from the units.

---

## Open items to report, not solve

- **Argo embeddings.** Not reachable through `argo-shim` — the Anthropic
  Messages API has no embeddings endpoint. If you ever want Argo-quality
  embeddings, that means adopting an OpenAI-shaped bridge (`argo-proxy` /
  `argo_bridge`) alongside the existing shim, **and** re-embedding the entire
  store, since vectors from different models aren't comparable. Report the
  option; don't take it on here.
- **Federating with Rick's agents.** Deliberately out of scope. The tenant/pool
  model and Sibline's subject tree both make it additive later — a second broker
  route and a shared pool, not a redesign.
- **Never patch `/opt/hermes` in place.** Container rebuilds wipe the writable
  layer, so the patch silently vanishes — see
  `Spark-Hermes/runlog/F-30-diagnosis-2026-06-29.md`. Anything that must survive
  belongs in a repo behind an apply script.

---

## Corrections folded in on 2026-07-28

This plan was revised after three claims in its first draft proved wrong.
Recorded because the *pattern* matters more than the specifics — each was stated
with more confidence than the evidence supported:

1. **"UMP isn't findable."** It is: a public, MIT-licensed open standard by Edi
   Hasaj, on npm. Searching only Rick's GitHub was too narrow.
2. **"Hermes v0.14.0 has no memory-provider interface."** It does —
   `agent/memory_provider.py`, plus eight bundled providers. The earlier source
   dig examined the built-in memory layer and over-generalized from it.
3. **"You must choose a local embeddings model."** Chat model and embedding
   model are independent decisions. The real constraint turned out to be that
   `argo-shim` is Anthropic-shaped and structurally cannot serve embeddings — a
   better reason, found only by reading `litellm/config.yaml`.

What caught all three: checking the actual artifact — the npm registry, the
source file, the config — instead of reasoning from what seemed likely. Do that.
