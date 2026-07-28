# Embedder — Ollama + nomic-embed-text

FALDA's `/v1/embeddings` provider. Local and always-on **by design**: the Argo
route (`argo-shim`) is Anthropic-shaped and structurally cannot serve
embeddings, and vectors from different models aren't comparable — so this
component can't fail over. Pinning it locally removes that whole failure class
for ~275 MB. See the plan's Phase 1 for the full rationale.

Binds to **`127.0.0.1:11434` only**. Nothing off-box.

## Pins (recorded 2026-07-28)

| Thing | Value |
|---|---|
| Ollama version | **v0.32.5** (generic `linux-arm64`, not a JetPack build — see below) |
| Ollama tarball sha256 | `aa7e06b5683ee66c4a3ec68ea7236db43b5a5d0821f0dfe2c5a215f4462bddf4` |
| Binary location | `~/opt/ollama/bin/ollama` (user-owned; no root install) |
| Model | `nomic-embed-text:latest`, id `0a109f422b47`, 274 MB |
| Embedding dimension | **768** → `FALDA_DIM=768` (Phase 2) |

### Why the generic arm64 build, not JetPack

The release ships three aarch64 variants: generic `arm64`, `arm64-jetpack5`,
`arm64-jetpack6`. This box (GB10 / DGX Spark) does **not** present as a classic
Tegra/Jetson platform — no `/etc/nv_tegra_release`, no device-tree model — and
runs CUDA 13.0. The JetPack builds target older L4T CUDA stacks, so the generic
build is the safe choice: it bundles its own CUDA libs and falls back to CPU
cleanly. The embedder runs on CPU anyway (a single forward pass), so GPU variant
selection is not load-bearing here.

## Install (what was done)

```bash
# 1. Fetch the pinned generic arm64 build (NOT the .tgz path — assets are .tar.zst)
curl -sSL -o /tmp/ollama-linux-arm64.tar.zst \
  https://github.com/ollama/ollama/releases/download/v0.32.5/ollama-linux-arm64.tar.zst
mkdir -p ~/opt/ollama
tar --use-compress-program=unzstd -xf /tmp/ollama-linux-arm64.tar.zst -C ~/opt/ollama

# 2. Install the user unit (this repo is the source of truth; symlink it)
ln -sf ~/code/spark-fabric/services/embedder/ollama.service \
  ~/.config/systemd/user/ollama.service
systemctl --user daemon-reload
systemctl --user enable --now ollama.service

# 3. Pull the model
OLLAMA_HOST=127.0.0.1:11434 ~/opt/ollama/bin/ollama pull nomic-embed-text
```

The Ollama binary and the model blobs (`~/.ollama/models`) are **not** vendored
in this repo — only the unit and these pins. A rebuild re-runs the steps above.

## Verify

```bash
curl -s http://127.0.0.1:11434/v1/embeddings \
  -H 'Content-Type: application/json' \
  -d '{"model":"nomic-embed-text","input":"cryostat target temperature"}' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(len(d["data"][0]["embedding"]))'
# Expected: 768
```

Also confirm the loopback bind (must be `127.0.0.1`, never `0.0.0.0`):

```bash
ss -ltnp | grep 11434
```
