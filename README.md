# spark-fabric

The shared substrate that lets Charlie's agents remember things and talk to each
other, running on the DGX Spark (`spark-960b`).

This repo holds the services **both** agents consume. It belongs to neither of
them.

| Service | What it does | Port |
|---|---|---|
| [FALDA](https://github.com/rick-stevens-ai/falda) | Tiered long-term memory — stream → atoms → scenes → core, with hybrid vector + full-text search | 8077 |
| Embedder (Ollama, `nomic-embed-text`) | Turns text into vectors for FALDA. Local and always-on by design | 11434 |
| Distiller | Promotes raw turns into facts, scenes, and identity. Runs on Claude Opus via LiteLLM → argo-shim → Argo | — |
| [Sibline](https://github.com/rick-stevens-ai/Sibline) | NATS + JetStream side-channel so agents coordinate in the background without pinging a human | 4222 |
| [UMP](https://universalmemoryprotocol.io) | Portable memory records, so a fact learned in one tool is readable by another | 4000 |

Everything binds to loopback. Nothing here is exposed off-box.

**Start here:** [`docs/PLAN-FALDA-SIBLINE.md`](docs/PLAN-FALDA-SIBLINE.md) — the
build plan, ten gated phases, written to be executed by Claude Code on the Spark.

## Layout

| Path | Contents |
|---|---|
| `docs/` | The build plan, topology notes |
| `services/` | Per-service env templates, systemd units, provisioning scripts |
| `ops/` | Apply scripts and health checks for the whole substrate |
| `runlog/` | What was actually done, and what surprised us |

Service *checkouts* (`~/code/falda`, `~/code/Sibline`) are not vendored here —
pinned commits are recorded in each `services/<name>/README.md`.

**No secrets in this repo.** NATS passwords, the UMP owner key, and any API keys
live in `0600` files under `~/.config/`, referenced by path from the units.

## Related repos

Four repos, split by ownership. The boundary is deliberate: shared substrate
below, per-agent integration above.

| Repo | What lives there |
|---|---|
| **`spark-fabric`** *(this one)* | Shared substrate: FALDA, embedder, distiller, NATS/Sibline, UMP |
| **`Spark-Hermes`** | **Gandalf** — Hermes agent + gateway in an NVIDIA OpenShell sandbox, his `soul/` and `skills/`, egress policies, ops scripts |
| **`spark-ai`** | OpenClaw gateway + vLLM. Shared services — connect/read only, never restart |
| **`spark-ai-agents`** | **Luoji** — OpenClaw agent folders, runbooks, and notes |

Rule of thumb: if it mentions a sandbox, `docker exec`, or a Hermes/OpenClaw
config key, it belongs in that agent's repo — not here. If both agents would
need it, it belongs here.
