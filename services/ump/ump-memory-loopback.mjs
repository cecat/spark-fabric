#!/usr/bin/env node
// Loopback UMP memory server — Phase 10.
//
// Faithful reimplementation of the package's `ump memory` bin
// (@universalmemoryprotocol/core dist/bin/memory.js), with ONE change: the HTTP
// server binds 127.0.0.1 instead of 0.0.0.0.
//
// WHY A WRAPPER (not a patch): the stock `ump memory --http <port>` calls
// `.listen(port)` with no host, so Node binds ALL interfaces. UMP has no auth
// beyond the owner scope, and this box has Tailscale + LAN IPs, so the stock
// server would expose the whole memory store off-box — the exact exposure the
// plan's SECURITY note forbids (same class as FALDA BUG-1). UMP is a GLOBAL npm
// package, so patching dist/ would vanish on reinstall; a wrapper that imports
// the package's public API and controls the bind itself is rebuild-safe.
//
// Env (same as the stock bin, plus UMP_HOST):
//   UMP_DIR    data dir (default ~/.ump)
//   UMP_HTTP   HTTP port (REQUIRED here; we run HTTP, not stdio)
//   UMP_STORE  json | markdown (default json)
//   UMP_AUDIT  "off" to disable (default on)
//   UMP_HOST   bind address (default 127.0.0.1 — do not widen without auth)
//
// This runs the HTTP binding only (the substrate/interchange endpoint). The
// stdio MCP transport that the stock bin also attaches is for a single parent
// process; agent MCP wiring is handled separately per agent (Hermes mcp_servers,
// OpenClaw MCP), pointing at this HTTP endpoint or spawning ump-memory directly.

// UMP is a GLOBAL npm package, which ESM `import "<name>"` can't resolve from an
// out-of-tree script. Resolve its dist/index.js by absolute path instead. Set
// UMP_CORE_INDEX to override (the systemd unit derives it from `npm root -g`).
import { homedir } from "os";
import { join } from "path";
import { mkdirSync, readFileSync, writeFileSync, existsSync, chmodSync } from "fs";
import { pathToFileURL } from "url";

const coreIndex = process.env.UMP_CORE_INDEX
  || join(homedir(), ".nvm/versions/node/v22.22.3/lib/node_modules/@universalmemoryprotocol/core/dist/index.js");
const {
  JsonFileStore,
  JsonlAuditLog,
  MarkdownDirectoryStore,
  UmpServer,
  createHttpServer,
  generateKeyPair,
} = await import(pathToFileURL(coreIndex).href);

const dir = process.env.UMP_DIR || join(homedir(), ".ump");
const storeKind = process.env.UMP_STORE || "json";
const auditOn = process.env.UMP_AUDIT !== "off";
const host = process.env.UMP_HOST || "127.0.0.1";
const httpPort = process.env.UMP_HTTP ? Number(process.env.UMP_HTTP) : undefined;

function log(msg) {
  process.stderr.write(`[ump-memory-loopback] ${msg}\n`);
}

function loadOrCreateKey(path) {
  if (existsSync(path)) {
    try {
      const { seed } = JSON.parse(readFileSync(path, "utf8"));
      return generateKeyPair(Uint8Array.from(Buffer.from(seed, "base64")));
    } catch {
      log(`warning: could not read ${path}, generating a new key`);
    }
  }
  const kp = generateKeyPair();
  writeFileSync(path, JSON.stringify({ seed: Buffer.from(kp.privateKey).toString("base64") }), { mode: 0o600 });
  try { chmodSync(path, 0o600); } catch {}
  return kp;
}

if (!httpPort) {
  log("UMP_HTTP is required (this wrapper serves HTTP only). Refusing to start.");
  process.exit(2);
}

mkdirSync(dir, { recursive: true });
const key = loadOrCreateKey(join(dir, "key.json"));
const store = storeKind === "markdown"
  ? await MarkdownDirectoryStore.open(join(dir, "memory.d"))
  : await JsonFileStore.open(join(dir, "memory.ump.json"));
const audit = auditOn ? await JsonlAuditLog.open(join(dir, "audit.log.jsonl"), { key }) : undefined;

const server = new UmpServer({
  name: "ump-memory",
  version: "0.1.0",
  conformance: "L2",
  store,
  key,
  audit,
});

createHttpServer(server, { wellKnown: { owner: key.did } }).listen(httpPort, host, () => {
  log(`HTTP binding on ${host}:${httpPort}`);
  log(`data ${dir}  store ${storeKind}  audit ${audit ? "on" : "off"}  owner ${key.did}`);
});
