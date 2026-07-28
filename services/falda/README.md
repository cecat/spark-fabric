# FALDA gateway

Tiered long-term memory (stream → atoms → scenes → core) with hybrid vector +
full-text search. Binds **`127.0.0.1:8077` only** — FALDA has **no auth of its
own**, so loopback isolation is the entire security boundary. See the plan's
Phase 2/3.

The falda checkout (`~/code/falda`) is **not vendored** — clone it at the pin
below. This directory holds the run artifacts: the loopback patch, the systemd
unit, the env template, and an idempotent apply script.

## Pins (recorded 2026-07-28)

| Thing | Value |
|---|---|
| falda commit | `c9f14bc` (fix: Buffer-encode vectors for sqlite-vec bind) |
| node (runtime + build ABI) | **v22.22.3**, `~/.nvm/versions/node/v22.22.3/bin/node` (ABI 127) |
| better-sqlite3 | `^12.11.1`, native; rebuilt under the pinned node |
| sqlite-vec | `sqlite-vec-linux-arm64` present (dense recall) |
| embedder | remote → `http://127.0.0.1:11434/v1` (Phase 1 Ollama) |
| FALDA_DIM | 768 (matches nomic-embed-text; locked in `EMBEDDING.json` on first boot) |

## Two things that differ from falda's own docs (verified against source)

1. **It binds `0.0.0.0`, not loopback — and there was no env to change that.**
   `src/gateway.ts` called `.listen(PORT, …)` with no host arg (Node → all
   interfaces). On this box that means the Tailscale and LAN IPs, i.e. no-auth
   FALDA exposed off-box — exactly what the plan forbids. Fix:
   `patches/0001-bind-loopback-by-default.patch` adds a `FALDA_HOST` env
   defaulting to `127.0.0.1`. The apply script re-applies it after a fresh
   clone (the checkout isn't vendored, so a raw edit would be lost on re-clone).
   Upstreamable as "make bind host configurable, default loopback."

2. **Config uses `FALDA_ROOT`, not `FALDA_DB`/`FALDA_BLOBS`.** falda's README
   still documents the old split; the running gateway (`src/gateway.ts:45`) reads
   a single `FALDA_ROOT` (DB + blobs + `EMBEDDING.json` under one dir). The env
   template uses `FALDA_ROOT`.

## Native ABI gotcha (why the node path is pinned)

`better-sqlite3` is a native module. `npm ci` / `npm rebuild` **must** run under
the same node the unit's `ExecStart` uses, or the gateway dies with
`ERR_DLOPEN_FAILED` (NODE_MODULE_VERSION mismatch). This box has two node
majors: nvm **v22** (used here) and `/usr/bin/node` **v18** (fails falda's
`engines >=20`). The unit pins the absolute v22 path and does not rely on `PATH`.

## Install / re-run

```bash
# 1. Clone falda at the pin (if not already present)
git clone https://github.com/rick-stevens-ai/falda ~/code/falda
git -C ~/code/falda checkout c9f14bc

# 2. Idempotent bring-up: patch + npm ci + rebuild + env + unit + start
bash ~/code/spark-fabric/services/falda/apply.sh
```

Data root `~/.falda/data`; log `~/.falda/gateway.log`; env rendered to
`~/.config/falda/falda.env` (0600). Unit symlinked from this repo.

## Verify (VERIFY 2)

```bash
curl -s localhost:8077/healthz
# {"ok":true,"tiers":["stream","atoms","scenes","core"],"pools":true}

cd ~/code/falda && npm run smoke   # prints "ALL TIERS GREEN"

ss -ltnp | grep 8077               # MUST be 127.0.0.1:8077, not *:8077
```
