# FALDA distiller (T0 → T1 → T2 → T3)

Promotes raw FALDA stream turns up the tiers: **T0 stream → T1 atoms → T2 scenes
→ T3 core**, using Claude Opus (via LiteLLM → argo-shim → Argo) for the
extraction/synthesis reasoning. FALDA ships only storage primitives; this sidecar
is the missing promotion loop.

## Script is un-vendored

The distiller is `~/code/falda/falda_distiller.py`, part of the falda checkout —
**not copied into this repo** (same policy as the gateway and the taps). We
version only the config template, the systemd unit(s), and this README.

- **Pinned falda commit under test:** `c9f14bc` (2026-07-19). Re-verify with
  `git -C ~/code/falda rev-parse HEAD` before trusting these notes.

## Two script defaults that WILL misconfigure you (override in env)

The upstream script defaults are wrong for this box; the env template sets both:

| Env | Script default | Correct here | Why it matters |
|---|---|---|---|
| `FALDA_URL` | `http://localhost:8078` | `http://127.0.0.1:8077` | our gateway is on :8077; the default silently talks to nothing |
| `DISTILLER_MODEL` | `gpt-4o-mini` | `claudeopus47` | the plan mandates Opus for distillation; the default would fail (no such model on the Argo route) |

## LLM route (verified)

```
falda_distiller.py → LiteLLM :4000/v1/chat/completions → argo-shim :44497 → Argo → Opus
```

`claudeopus47` is a real `model_name` in `Spark-Hermes/litellm/config.yaml`
(→ `anthropic/claudeopus47`, dummy api_key). No LiteLLM master key required.
Round-trip confirmed end-to-end before first run.

- **Never restart argo-shim or its SSH tunnel** — shared service; the tunnel
  needs a human Duo approval to re-establish. Connect only.
- **No vLLM fallback, by design.** On an Argo error the script logs and returns 0
  for that tier, retrying on the next poll — exactly the plan's "retry/resume, not
  fall back to vLLM" rule (mixed-quality atoms are worse than late atoms). This is
  already the script's behavior; no patch needed.

## Shadow vs. live — IMPORTANT per-tenant distinction

The script's docstring calls distilled atoms "pure shadow, never injected into
the agent loop." **That is true for `luoji`** (no FALDA memory provider) but **NO
LONGER true for `gandalf`**: Phase 5c wired FALDA in as Gandalf's memory
provider, and its `prefetch` reads gandalf's atoms — so distilled gandalf atoms
*can* reach the live agent. Consequences:

- **`luoji` is the clean VERIFY 6 target** (pure shadow; distillation quality can
  be judged without touching a live agent).
- A **`gandalf` distiller instance changes agent behavior** and should be treated
  as part of the 5c experimental surface, not turned on blindly. Decide it
  deliberately.

## Run order (per the plan)

1. `--once` backfill first, read the output, judge atom quality. A fresh tenant
   with **0 atoms is expected** until `L1_EVERY_N` turns exist.
2. Only then install the continuous loop as a `--user` systemd unit.

```bash
# one-shot backfill for luoji
set -a; . ~/.config/falda/distiller-luoji.env; set +a
python3 ~/code/falda/falda_distiller.py --once
```

Checkpoint + log (per-tenant): `~/.falda/distiller_state-<tenant>.json`,
`~/.falda/distiller-<tenant>.log`. Idempotent: atom IDs are content-hash-derived,
so re-running never duplicates.

## VERIFY 6

After enough turns/backfill:
```bash
curl -s -X POST http://127.0.0.1:8077/atoms/search \
  -H 'content-type: application/json' \
  -d '{"tenant":"luoji","query":"<topic>","limit":10}'
```
returns distilled facts that are **sensible, not noise**. Poor extraction on big
blobs → reduce `L1_CHUNK_TURNS` before blaming the model.

## Files here

- `distiller.env.template` — copy to `~/.config/falda/distiller-<tenant>.env` (0600).
- `falda-distiller-luoji.service` — `--user` unit for the continuous loop.
