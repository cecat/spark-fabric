# FALDA findings — for Rick

Running log of what we learn exercising FALDA (`github.com/rick-stevens-ai/falda`)
against two real agents on spark-960b: **Gandalf** (Hermes, sandboxed) and
**Luoji** (OpenClaw, sandboxed). Purpose is evaluation + collaboration, not just
bringup — so this file is the deliverable: confirmed bugs, candidate PRs, rough
edges, and design questions worth Rick's input.

Pinned commit under test: `c9f14bc` (2026-07-19). Config: `FALDA_DIM=768`
(nomic-embed-text via Ollama), loopback-only, one tenant per agent + a
`shared-corpus` pool.

Legend: 🐞 bug (have a fix) · ⚠️ rough edge / footgun · ❓ open question · 💡 idea

---

## 🐞 BUG-1 — gateway binds all interfaces; no auth means off-box exposure

**Where:** `src/gateway.ts`, the `createServer(...).listen(PORT, ...)` call.
**What:** `listen(PORT)` with no host binds `0.0.0.0`. FALDA has no auth of its
own, so on any box with a non-loopback interface (here: Tailscale + LAN) the
entire memory store — all tenants, read and write — is reachable by anything that
can route to the port. The README implies local-only use but nothing enforces it.
**Impact:** silent data exposure / cross-tenant read+write from off-box. High for
anyone who runs FALDA on a networked host.
**Fix (have patch):** add `const HOST = process.env.FALDA_HOST ?? "127.0.0.1";`
and `listen(PORT, HOST, ...)`. Loopback by default; opt into wider binding only
behind an authenticating proxy. Patch: `services/falda/patches/0001-bind-loopback-by-default.patch`.
**PR-ready:** yes — small, backward-compatible (env override preserves current
behavior for anyone who wants it via `FALDA_HOST=0.0.0.0`).

## 🐞 BUG-2 — delete leaves orphaned FTS/vec rows → contentless phantom search hits

**Where:** `src/falda.ts`, `deleteStream()` and `deleteAtoms()`.
**What:** deletes remove the row from the base table (`stream` / `atoms`) but not
the shadow index tables (`*_fts`, `*_vec`). `upsertAtom` already cleans these on
update, so the delete path is just inconsistent with the write path. Orphaned
index rows then surface in hybrid search as hits that score but carry no
`id`/`content`, mixed in with real results.
**Impact:** phantom results pollute recall; worse, a tenant with zero real rows
can still return "hits" (observed on a freshly-emptied tenant). Correctness bug in
the core recall path.
**Fix (have patch):** in `deleteStream` (both the `ids` and `session_id`
branches) and `deleteAtoms`, also `DELETE FROM *_fts` / `*_vec WHERE id=?`,
mirroring `upsertAtom`'s existing cleanup. For the `session_id` branch, collect
ids first, then delete from base + shadows. Patch:
`services/falda/patches/0002-clean-fts-vec-on-delete.patch`.
**PR-ready:** yes. Note for Rick: a defense-in-depth alternative/addition is to
LEFT JOIN the base table in the search query and drop rows with null content, so
pre-existing orphans in the wild also stop surfacing without a migration.

---

## ⚠️ Rough edges

- **RE-1 — README/config drift.** README documents `FALDA_DB` / `FALDA_BLOBS`;
  the source reads `FALDA_ROOT`. Following the README yields a misconfigured
  store. (Low effort doc fix.)
- **RE-2 — API shape undocumented.** Endpoints are POST + JSON body
  (`{tenant, pool, ...}`), not the query-string shape a first reading of the
  README suggests. A short endpoint reference (method + path + body) would save
  every integrator the trial-and-error we did.
- **RE-3 — `sqlite-vec` extension load is environment-fragile.** `stream_vec` /
  `atoms_vec` are virtual tables backed by `vec0.so`; any tool that opens the DB
  without loading the bundled `sqlite-vec-linux-arm64/vec0.so` (e.g. the stock
  `sqlite3` CLI) errors `no such module: vec0`. Worth a one-liner in the README
  for anyone inspecting the DB directly.
- **RE-4 — `/stream/add` embed cost is silent and unbounded per request.** Each
  message in the batch is embedded inline (synchronously) via the configured
  embedder before the call returns. With the local CPU Ollama embedder, a ~55ms/
  msg warm cost means a large batch (we hit a 99-msg / 50KB session) blows past a
  short client timeout — worse on a cold embedder. There's no server-side cap,
  no partial-progress response, and no async/202 option, so the client must guess
  a safe batch size and timeout. Observed as a client `TimeoutError` on backfill;
  we worked around it by chunking (25/batch) and a 120s client timeout.
  Suggestions for Rick: (a) document the sync-embed cost + a recommended batch
  size; (b) consider an async accept (202 + background embed) or a bounded
  per-request message cap with a clear error; (c) return partial `accepted_ids`
  progress so a client can resume. **CONFIRMED GOOD:** `/stream/add` is correctly
  NON-idempotent (append semantics) — re-posting appends, as it should; dedup is
  the client's job (our tap checkpoints on a monotonic source id).
- **CONFIRMED FIX — patch 0002 holds end-to-end.** Deleting a stream session via
  the gateway `/stream/delete` API (not just direct SQL) drove `stream`,
  `stream_fts`, AND `stream_vec` all to 0 on a real 510-row tenant. The
  orphan-on-delete bug is fixed through the live HTTP path, not just in unit
  isolation.
- **RE-5 — RRF weights are hardcoded; not configurable.** In `src/falda.ts`
  `hybrid()`, dense and lexical rankings are fused with a fixed reciprocal-rank
  term `1 / (RRF_K + i)` applied equally to both lists — there is no way to weight
  dense vs lexical, and `RRF_K`/`limit*2` candidate depth are constants. For
  anyone tuning recall (we wanted a dense/lexical weight knob for an ablation
  harness) this can't be done without patching. **Suggestion for Rick:** accept
  optional per-request `dense_weight`/`lexical_weight` (and maybe `rrf_k`) in the
  search body, defaulting to today's behavior. Small, backward-compatible. We're
  carrying the intended weights in our config and logging intended-vs-actual so
  the gap is on the record; happy to send a PR.
- **BUG-2 addendum — patch 0002 is forward-only; pre-existing orphans still
  surface, now observed in a POOL.** 0002 fixes the delete *path*, but orphans
  written before the fix remain and still appear as phantom score-only hits in
  `/search`. Seeding ONE atom into the `shared-corpus` pool, `/atoms/search`
  returned TWO items (the real one + a `{"score":…}` with no id/content) while the
  authoritative `/atoms/query` correctly returned `total: 1`. So the phantom is
  purely a search-path artifact and it affects pools, not just tenants. This is
  exactly why the earlier "defense-in-depth" note matters: **LEFT JOIN the base
  table in the search query and drop null-content rows** would suppress in-the-wild
  orphans without requiring a migration. Recommend shipping that alongside 0002.

## ❓ Open questions for Rick

- **Q-1 — dim mismatch behavior.** README/plan claim a wrong `FALDA_DIM` "silently
  degrades recall." Does FALDA detect/reject an embedder whose output dim ≠
  configured `DIM`, or just store mismatched vectors? A hard fail at first write
  would be safer. (Not yet tested — will confirm.)
- **Q-2 — distillation retry semantics (T0→T1→T2→T3).** When the distiller's LLM
  is unreachable, does promotion retry/resume idempotently, or can it drop/dup
  atoms? (Relevant to our Argo-backed distiller in a later phase.)
- **Q-3 — pool write semantics.** For a shared pool (`shared-corpus`,
  both agents readwrite), how are concurrent writes from two processes
  serialized? SQLite busy-timeout? Any risk under simultaneous `/stream/add`?

## 💡 Ideas / integration notes (not FALDA bugs)

- Both target agents already have native memory (Hermes `state.db` + FTS5;
  OpenClaw `/workspace/memory/*.md`). FALDA's differentiators we actually want to
  test: **cross-agent shared memory** (the pool) and **tiered distillation**. The
  per-agent shadow taps exist mainly to feed FALDA realistic traffic for that
  test — they are a harness, not the end state.
- **CONFIRMED GOOD — cross-agent pool recall works end-to-end (the headline
  differentiator).** Phase 5c: a fact authored as tenant `luoji` into the
  `shared-corpus` pool was retrieved by tenant `gandalf` *through the pool* and
  surfaced automatically to the Gandalf agent via a Hermes memory-provider
  `prefetch` — the agent answered a question it could only know from FALDA, with
  no explicit search. Pool read isolation held (the fact was absent from
  gandalf's private `self` store, present via the pool). This is the capability
  neither agent's native memory has, and it works.
