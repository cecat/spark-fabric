# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

`spark-fabric` is the **shared substrate** for Charlie's two agents — Gandalf
(Hermes, sandboxed) and Luoji (OpenClaw, native) — running on the DGX Spark
(`spark-960b`, Ubuntu 24.04, aarch64). It holds the services *both* agents
consume: FALDA memory, an Ollama embedder, a distiller, a NATS/Sibline message
bus, and UMP. It belongs to neither agent.

There is no application code here yet. The repo is currently a README plus the
build plan at `docs/PLAN-FALDA-SIBLINE.md`. The work is **executing that plan**:
provisioning services on the box via config templates, systemd units, and apply
scripts committed here. There is no build, lint, or test suite — verification is
per-phase `VERIFY` blocks (curl/CLI checks against running services), not a CI
harness.

## The four-repo boundary (read before creating any file)

Work is split across four repos by **ownership, not convenience**. Putting a
file in the wrong one is the easiest way to make this unmaintainable.

| Repo | Holds |
|---|---|
| **`spark-fabric`** *(this one)* | Shared substrate both agents consume: FALDA, embedder, distiller, NATS broker, UMP. Config templates, systemd units, provisioning scripts, the plan. |
| **`Spark-Hermes`** | Gandalf: Hermes gateway, OpenShell sandbox, `soul/`+`skills/`, egress policies, apply scripts. |
| **`spark-ai-agents`** | Luoji: OpenClaw agent folders, runbooks, `.md` files. |
| **`spark-ai`** | OpenClaw gateway + vLLM. Shared services — **connect/read only, never restart.** |

Rules that follow:
- **Nothing agent-specific goes in `spark-fabric`.** If it mentions OpenShell, a
  sandbox, `docker exec`, or a Hermes/OpenClaw config key, it belongs in that
  agent's repo.
- **Nothing shared goes in an agent repo.** If both agents would need it, it
  belongs here.
- **The Sibline file-mailbox bridge is Gandalf-specific** — a sandbox
  workaround, so it lives in `Spark-Hermes`. Luoji speaks NATS directly and must
  not inherit it.

Service *checkouts* (`~/code/falda`, `~/code/Sibline`) are **not vendored** —
record pinned commits in each `services/<name>/README.md`.

## How to work the plan

`docs/PLAN-FALDA-SIBLINE.md` is the source of truth. Its ordering and gates are
deliberate:

1. **Phases are gated.** Each ends with a `VERIFY` block (command + expected
   output). Do not start phase N+1 until phase N verifies. If a verify fails,
   **stop and report — do not work around it.**
2. **Verify assumptions before building on them.** Claims marked `[ASSUMED]` are
   hypotheses, not facts — confirm each against the actual system (find the
   loader, read the call chain, prove it with a canary) before depending on it.
   The plan exists in its current form because three confidently-stated claims
   in the first draft were wrong; checking the actual artifact (npm registry,
   source file, config) caught all three.
3. **Nothing hand-configured on the box.** Templates, units, and apply scripts
   go in a repo. If a rebuild would lose it, it belongs in version control.
4. **Do Luoji (phase 4) before Gandalf (phase 5).** Luoji is native and
   unsandboxed — the clean place to prove the FALDA capture pattern before
   Gandalf adds egress policy, a memory provider, and a file bridge on top.
5. **Report at each phase boundary** in a running log at
   `runlog/RUNLOG-<date>-bringup.md`.

## Architecture essentials

Everything binds to **loopback only** (`127.0.0.1`); nothing is exposed off-box.

- **FALDA** (`:8077`) — tiered long-term memory (stream→atoms→scenes→core) with
  hybrid vector + full-text search. **Has no auth of its own** — isolation
  depends entirely on the loopback bind. One tenant per agent (`gandalf`,
  `luoji`); agents share memory only via an opt-in named pool (`shared-corpus`),
  never by sharing a tenant.
- **Embedder** — Ollama + `nomic-embed-text` (`:11434`), local and always-on.
  Pinned local **by design**: `argo-shim` is Anthropic-shaped and structurally
  cannot serve embeddings, and vectors from different models aren't comparable,
  so this component can't fail over. `FALDA_DIM` must match the embedder's
  output (768) or recall silently degrades.
- **Distiller** — promotes T0→T1→T2→T3, running on Claude Opus via
  LiteLLM→argo-shim→Argo. Remote by design: distillation is the one genuinely
  hard reasoning job, and as a background batch job it tolerates an outage. If
  Argo is unreachable it must retry/resume, **not** fall back to vLLM.
- **Sibline** — NATS + JetStream (`:4222`, monitoring `:8222`) side-channel for
  background agent-to-agent coordination. Gandalf **never speaks NATS** (raw TCP
  can't cross the sandbox's L7 proxy) — a host-side bridge shuttles a file
  mailbox in/out via `docker exec`, mirroring `Spark-Hermes/ops/outbox-processor.sh`.
- **UMP** (`:4000`, optional, after phase 9) — memory *interchange format* (an
  MCP server), complementary to FALDA's memory *engine*. One shared `did:key`
  owner for both agents.

## Secrets and safety

- **No secrets in any repo.** NATS passwords, the UMP owner key, and API keys
  live in `0600` files under `~/.config/`, referenced by path from the units.
- **Never restart shared services** — vLLM and argo-shim in particular.
  argo-shim's SSH tunnel needs a human Duo approval to re-establish.
- **Never patch `/opt/hermes` in place** — container rebuilds wipe the writable
  layer. Anything that must survive belongs in a repo behind an apply script.
- Snapshot an agent's stack before touching it (`Spark-Hermes/ops/snapshot.sh`),
  and copy any `~/code/spark-ai*` file before modifying it.
