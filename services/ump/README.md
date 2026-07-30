# UMP — memory interchange format (Phase 10)

FALDA is the memory *engine*; **UMP is the memory *interchange format*** — an MCP
server that makes a fact portable: readable by another agent, another vendor's
tool, or a future stack, instead of living only in FALDA's SQLite. It's the
least-invasive component (an MCP server + a portable JSON file).

## Pins

- `@universalmemoryprotocol/core` **v0.2.0** (npm, MIT), installed global under
  nvm node **v22.22.3** (package `engines: node>=20`; system node v18 would fail —
  same pin rationale as FALDA). Bins: `ump`, `ump-memory`, `ump-serve`,
  `ump-import`, `ump-conformance`.
- Server conformance: **UMP 0.1 / L2**.

## What runs here

- **`ump-memory-loopback.mjs`** — our server entrypoint. See the bind-bug note
  below for why it's a wrapper, not the stock `ump memory`.
- **`ump-memory.service`** — `--user` unit, nvm-node-pinned ExecStart.
- **`ump.env.template`** → `~/.config/ump/ump.env` (0600).
- Data + key: `~/.ump/` — `key.json` (0600, the owner seed), `memory.ump.json`
  (the portable store), `audit.log.jsonl`.
- Endpoint: **`http://127.0.0.1:4100`** (loopback). Routes under `/ump/*`
  (`/ump/remember`, `/ump/recall`, `/ump/forget`, `/ump/capabilities`, …) plus
  `/.well-known/ump.json`.

## 🐞 Finding for the UMP maintainers — server binds 0.0.0.0 (no host arg)

The stock `ump memory --http <port>` (and `ump serve`) call
`.listen(port)` with **no host**, so Node binds **all interfaces**. UMP has no
transport auth (only the owner scope), so on any box with a non-loopback IP
(here: Tailscale + LAN) the entire memory store is reachable off-box. Same class
as FALDA BUG-1. Because UMP is a global npm package (not a source checkout), we
did NOT patch `dist/` (a reinstall would wipe it); instead
`ump-memory-loopback.mjs` imports the package's public API
(`UmpServer`, `createHttpServer`, `JsonFileStore`, …) and calls
`.listen(port, "127.0.0.1")` itself. **Suggested upstream fix:** accept a
`--host` flag / `UMP_HOST` env, default `127.0.0.1`. Small, backward-compatible.

## Port :4100 (not :4000)

The plan's example uses `ump memory --http 4000`, but **LiteLLM already owns
:4000** on this box (the distiller's route). UMP uses **:4100**.

## One shared owner for BOTH agents (mandatory design)

There is ONE `did:key` owner (in `~/.ump/key.json`), used by Gandalf AND Luoji,
so their memories are genuinely interchangeable. Do not let each agent generate
its own — that would defeat portability. Current owner:
`did:key:z6Mksh6F8K7vFaPpzmstzqR2Fj9zaWwJpHC5q1QCVAYFDqbw` (seed is the 0600
`key.json`; back it up if the store must survive a box loss).

## ⚠️ `scope.owner` is mandatory on recall

Omit `scope.owner` on a recall and you get `{"results":[]}` — an empty set with
**no error** (the silent-failure shape that bit this deployment repeatedly, and
that the plan explicitly warns about). Always pass it.

## VERIFY 10 (green 2026-07-30)

- `ump-conformance http://127.0.0.1:4100` → **UMP 0.1 / L2, 12/13** (the one miss
  is L3 `capability_tokens`, above our L2 target).
- Wrote a `semantic` record under the shared owner, recalled it back via
  `scope.owner`; confirmed omitting `scope.owner` returns empty (no error).
- `~/.ump/memory.ump.json` is plain self-describing JSON — copyable to another
  machine. Anything one agent writes under the shared owner, the other reads.
- Bind is **127.0.0.1 only** (verified via `ss`; the LAN IP refuses).

## Not done here — agent MCP wiring (separate, more invasive)

Making the agents *use* UMP live means registering this server in each agent's
MCP config (Hermes `mcp_servers`, OpenClaw's MCP equivalent). That touches
agent-side config in the agent repos and is a deliberate follow-up — the
substrate (server + shared owner + portable store) is what Phase 10 delivers.
Seeding tip: `ump import --owner <did> gandalf/soul/*.md` bootstraps records from
existing Markdown.

## Operate

```bash
systemctl --user status ump-memory
bash ~/code/spark-fabric/ops/status.sh          # includes UMP checks
~/.nvm/versions/node/v22.22.3/bin/ump-conformance http://127.0.0.1:4100
```
