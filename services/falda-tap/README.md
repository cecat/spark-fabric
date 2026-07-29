# FALDA shadow tap — OpenClaw (Luoji)

Tails Luoji's OpenClaw L0 session JSONL and mirrors each **conversation** turn to
FALDA `/stream/add` under tenant `luoji`. **Shadow only** — OpenClaw stays 100%
authoritative and untouched; this only reads its session files and forwards to
FALDA so both accumulate the same traffic in parallel. Luoji's own memory
(`/workspace/memory/*.md`) is unchanged and unaware of FALDA. Flipping FALDA to
be Luoji's *actual* memory is a later, separate decision (not this phase).

## Why a separate adapter (not falda's `falda_tap.py`)

falda's `integrations/external-source/falda_tap.py` assumes each JSONL line is a
flat `{sessionKey, role, content}`. OpenClaw's format is an **event log**: many
event types, and `type=="message"` events nest `role`/`content` under a
`message` object whose `content` is a string (user) or a list of blocks
(assistant/tool). `falda_tap_openclaw.py` keeps the proven byte-offset-checkpoint
design and adds OpenClaw parsing + signal filters.

## Source path — the Option B bind-mount

Reads `~/.openclaw-sessions/luoji`, which is the OpenClaw gateway's
`agents/luoji/sessions` dir surfaced to the host by the spark-ai compose
bind-mount (see `spark-ai/openclaw/docker-compose.yml` and the 2026-07-28 runlog).
The gateway writes session JSONL there; the tap reads it as plain files.

## What it captures (filters decided 2026-07-28)

| Kept | Dropped |
|---|---|
| `type=="message"` with role `user` or `assistant` (non-empty text) | every non-message event (`session`, `trace.*`, `prompt.*`, `model.*`, …) |
| | `toolResult` — ~79% of byte volume, log/file-dump noise, not memory |
| | assistant turns that are `toolCall`-only (no text) |
| | heartbeat turns (`[OpenClaw heartbeat poll]` and `HEARTBEAT_OK`) |
| | `main.jsonl` (empty) and `*.trajectory.jsonl` shards |

Content flattening: string content passes through; list content is the joined
text of `{type:'text'}` blocks (`toolCall` blocks contribute nothing).

## Restart-safe checkpoint

Per-file byte offset in `~/.falda/tap_state_luoji.json`. Offsets advance only on
a 200 from `/stream/add`, and never past a partial trailing line — so a restart
never re-sends or misses a turn. Session id in FALDA is `openclaw:<shard-uuid>`.

## Install

```bash
ln -sf ~/code/spark-fabric/services/falda-tap/falda-tap-luoji.service \
  ~/.config/systemd/user/falda-tap-luoji.service
systemctl --user daemon-reload
systemctl --user enable --now falda-tap-luoji.service
```

Stdlib-only Python — runs under system `/usr/bin/python3`, **not** the sibline
venv. Log: `~/.falda/tap_luoji.log`.

## Verify (VERIFY 4)

```bash
# after a conversation with Luoji:
curl -s -X POST localhost:8077/stream/search -H 'content-type: application/json' \
  -d '{"tenant":"luoji","query":"<phrase you just said>"}'
```

Proven 2026-07-28: backfilled 94 historical turns; restart caused no
duplication; a live Slack round-trip ("remember codeword TANGERINE-CANYON") was
captured (96→99) and is searchable — while `toolResult`/tool-call/heartbeat
events from the same session were correctly excluded.
