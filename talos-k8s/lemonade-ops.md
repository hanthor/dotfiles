# Lemonade Server — Ops Reference

> Live snapshot from the Bihar+Karnataka cluster, 2026-06-05.
> Lemonade 10.6.0 | API v0.16.1 | 99 models available | AMD Strix Halo iGPU (gfx1151)

## Cluster placement

| Detail | Value |
|--------|-------|
| Node | `karnataka` (192.168.0.6, AMD Strix Halo) |
| Pod | `lemonade-7fd6dc5f4-l7fpt` |
| Image | `ghcr.io/lemonade-sdk/lemonade-server:latest` |
| Resources | req 8 CPU / 48 Gi RAM, lim 16 CPU / 56 Gi RAM, 1× amd.com/gpu |
| Network | `hostNetwork: true`, `hostIPC: true` |
| Port | 13305 (NodePort 31305) |
| WebSocket | auto (port 9000 seen in logs) |
| Tailscale ingress | `ts-lemonade-rtr8t-0` → `*.manatee-basking.ts.net` |
| PVC models | `lemonade-models` 100 Gi, hostPath `/var/tmp/lemonade-models` |
| PVC cache | `lemonade-cache` 100 Gi, hostPath `/var/tmp/lemonade-cache` |
| shm | 16 Gi tmpfs (emptyDir `Memory`) |
| HF token | secret `hf-token` key `token` |

---

## API — Endpoints

Lemonade speaks **OpenAI-compatible** (`/v1/…`) and **Ollama-compatible** (`/api/…`) protocols.
Base URL: `http://<host>:13305`  (or `https://lemonade.manatee-basking.ts.net` via Tailscale).

### Discovery & Status

| Method | Path | Notes |
|--------|------|-------|
| GET | `/v1/models` | OpenAI model list (download-status aware) |
| GET | `/v1/models?show_all=true` | Full model catalog, 99 entries |
| GET | `/api/version` | Server version (`{"version":"0.16.1"}`) |
| GET | `/api/tags` | Ollama: loaded models (local only) |
| GET | `/api/ps` | Ollama: running models |

### Chat / Text Generation

| Method | Path | Protocol |
|--------|------|----------|
| POST | `/v1/chat/completions` | OpenAI chat completions |
| POST | `/api/generate` | Ollama generate (set `"stream": false` for one-shot) |
| POST | `/api/chat` | Ollama chat |

### Embeddings & Reranking

| Method | Path | Notes |
|--------|------|-------|
| POST | `/v1/embeddings` | OpenAI embeddings |
| POST | `/v1/rerank` | Reranking (jina-reranker, bge-reranker) |

### Image Generation

| Method | Path | Notes |
|--------|------|-------|
| POST | `/v1/images/generations` | SD / Flux / Qwen-Image |
| POST | `/v1/images/edits` | Image-to-image (Flux-2-Klein supports `edit` label) |
| POST | `/v1/images/upscale` | RealESRGAN upscaling |

### Audio — Transcription & TTS

| Method | Path | Notes |
|--------|------|-------|
| POST | `/v1/audio/transcriptions` | Whisper models |
| POST | `/v1/audio/translations` | Whisper translate |
| POST | `/v1/audio/speech` | TTS (kokoro-v1) |

### Model Lifecycle (Ollama compat)

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/pull` | Download a model by name |
| POST | `/api/show` | Model info / metadata |
| DELETE | `/api/delete` | Remove a model from disk |
| POST | `/v1/unload` | Unload a running model from memory |

**Auto-download on first use.** Models are fetched from Hugging Face when first requested.
Cache lives at `/opt/lemonade/llama/` (PVC) + `/root/.cache/huggingface/` (PVC).
After download, the model loads into GPU VRAM and serves requests.

---

## Quick recipes

### List all models

```bash
curl -s http://lemonade:13305/v1/models?show_all=true | jq '.data[] | {id, size, labels, recipe}'
```

### Chat with a model (auto-downloads on first use)

```bash
curl -s -X POST http://lemonade:13305/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen3-4B-GGUF",
    "messages": [{"role": "user", "content": "Explain AMD ROCm in one paragraph."}],
    "max_tokens": 200,
    "temperature": 0.7
  }' | jq '.choices[0].message.content'
```

### Ollama-style generate (non-streaming)

```bash
curl -s -X POST http://lemonade:13305/api/generate \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3-4B-GGUF","prompt":"Hello world","stream":false}'
```

### Embeddings

```bash
curl -s -X POST http://lemonade:13305/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"nomic-embed-text-v1-GGUF","input":"your text here"}'
```

### Image generation

```bash
curl -s -X POST http://lemonade:13305/v1/images/generations \
  -H "Content-Type: application/json" \
  -d '{
    "model": "SD-Turbo-GGUF",
    "prompt": "a cyberpunk cat on a neon rooftop",
    "n": 1,
    "size": "512x512"
  }'
```

### Audio transcription

```bash
curl -s -X POST http://lemonade:13305/v1/audio/transcriptions \
  -H "Content-Type: multipart/form-data" \
  -F "model=Whisper-Tiny" \
  -F "file=@audio.wav"
```

### Health (basic)

```bash
# HTTP 200 = alive
curl -s -o /dev/null -w "%{http_code}" http://lemonade:13305/
```

---

## Deployment topology (from lemonade.yaml)

```
karnataka (amd.com/gpu=1, 128GB RAM, AMD Strix Halo)
├── lemonade Deployment (1 replica)
│   ├── hostNetwork: true, hostIPC: true
│   ├── SYS_PTRACE capability, seccomp=Unconfined
│   ├── HSA_OVERRIDE_GFX_VERSION=11.5.1
│   ├── PYTORCH_ROCM_ARCH=gfx1151
│   ├── HSA_XNACK=1, HSA_FORCE_FINE_GRAIN_PCIE=1
│   ├── volumes:
│   │   ├── /opt/lemonade/llama        ← PVC lemonade-models (100Gi)
│   │   ├── /root/.cache/huggingface   ← PVC lemonade-cache (100Gi)
│   │   └── /dev/shm                   ← tmpfs 16Gi
│   └── max_loaded_models: 1 (only one model in VRAM at a time)
├── lemonade NodePort Service (31305)
└── Tailscale ts-lemonade-rtr8t-0 Ingress
```

---

## Backend engines & versions

From `resources/backend_versions.json`:

| Engine | Variant | Version |
|--------|---------|---------|
| llamacpp (GGUF) | rocm-stable | b9247 |
| llamacpp (GGUF) | rocm-nightly | b1274 |
| llamacpp (GGUF) | vulkan | b9253 |
| llamacpp (GGUF) | cpu | b9253 |
| whispercpp | rocm | v1.8.4 |
| whispercpp | vulkan | v1.8.4 |
| sd-cpp | rocm-stable | master-616-cde20d5 |
| sd-cpp | cpu | master-616-cde20d5 |
| vllm | rocm | vllm0.20.1-rocm7.12.0 |
| ryzenai-llm | npu | v1.7.0 |
| flm | npu | v0.9.42 |
| kokoro (TTS) | cpu | b17 |
| therock (ROCm runtime) | gfx1151 | 7.13.0 |

---

## Default server config

Key tunables from `resources/defaults.json`:

```json
{
  "port": 13305,
  "host": "localhost",
  "log_level": "info",
  "global_timeout": 300,
  "max_loaded_models": 1,
  "ctx_size": 4096,
  "offline": false,
  "rocm_channel": "stable",
  "llamacpp":  { "backend": "auto", "args": "" },
  "whispercpp": { "backend": "auto", "args": "" },
  "sdcpp":     { "backend": "auto", "steps": 20, "cfg_scale": 7.0 },
  "vllm":      { "backend": "auto", "args": "" }
}
```

To change these, set env vars in the Deployment (e.g. `LEMONADE_LOG_LEVEL=debug`,
`LEMONADE_MAX_LOADED_MODELS=2`, `LEMONADE_CTX_SIZE=8192`).

---

## Model catalog — 99 models across 3 backends

### GGUF / llamacpp (80 models)

Models downloaded from Hugging Face on first use. Labels indicate capabilities.

**Reasoning / chat (small → medium, ≤ 9 GB, fit VRAM easily):**
| Model | Size | Labels |
|-------|------|--------|
| Qwen3-0.6B-GGUF | 0.4 GB | reasoning |
| Qwen3-1.7B-GGUF | 1.1 GB | reasoning |
| Qwen3-4B-GGUF | 2.4 GB | reasoning |
| Qwen3-8B-GGUF | 5.2 GB | reasoning |
| Qwen3-14B-GGUF | 8.5 GB | reasoning |
| DeepSeek-Qwen3-8B-GGUF | 5.2 GB | reasoning |
| Qwen3.5-0.8B-GGUF | 0.8 GB | vision, tool-calling |
| Qwen3.5-2B-GGUF | 2.0 GB | vision, tool-calling |
| Qwen3.5-4B-GGUF | 3.6 GB | vision, tool-calling, hot |
| Qwen3.5-9B-GGUF | 6.9 GB | vision, tool-calling |
| Llama-3.2-1B-Instruct-GGUF | 0.8 GB | — |
| Llama-3.2-3B-Instruct-GGUF | 2.1 GB | — |
| Phi-4-mini-instruct-GGUF | 2.5 GB | — |
| SmolLM3-3B-GGUF | 1.9 GB | — |
| LFM2-1.2B-GGUF | 0.7 GB | — |
| LFM2.5-1.2B-Instruct-GGUF | 0.7 GB | — |
| Bonsai-1.7B/4B/8B-gguf | 0.2–1.2 GB | llamacpp |

**Reasoning / chat (large, > 10 GB):**
| Model | Size | Labels |
|-------|------|--------|
| Qwen3-30B-A3B-GGUF | 17.4 GB | reasoning |
| Qwen3.5-27B-GGUF | 18.5 GB | vision, tool-calling |
| Qwen3.5-35B-A3B-GGUF | 23.1 GB | vision, tool-calling |
| Qwen3.6-27B-GGUF | 18.5 GB | vision, tool-calling |
| Qwen3.6-35B-A3B-GGUF | 23.3 GB | vision, tool-calling, hot |
| Nemotron-3-Nano-30B-A3B-GGUF | 22.8 GB | — |
| Gemma-4-26B-A4B-it-GGUF | 18.1 GB | hot, tool-calling, vision |
| Gemma-4-31B-it-GGUF | 19.5 GB | hot, tool-calling, vision |
| LFM2-8B-A1B-GGUF | 5.0 GB | — |
| LFM2-24B-A2B-GGUF | 14.4 GB | — |
| Llama-4-Scout-17B-16E-Instruct-GGUF | 63.2 GB | vision |
| Qwen3.5-122B-A10B-GGUF | 77.9 GB | vision, tool-calling |
| gpt-oss-120b-GGUF | 62.8 GB | reasoning, tool-calling |

**Coding / tool-calling:**
| Model | Size | Labels |
|-------|------|--------|
| Qwen3-4B-Instruct-2507-GGUF | 2.5 GB | tool-calling |
| Qwen3-30B-A3B-Instruct-2507-GGUF | 17.4 GB | tool-calling |
| Qwen3-Coder-30B-A3B-Instruct-GGUF | 18.6 GB | coding, tool-calling, hot |
| Qwen3-Coder-Next-GGUF | 48.0 GB | coding, tool-calling, hot |
| Qwen2.5-Coder-32B-Instruct-GGUF | 19.9 GB | coding |
| Devstral-Small-2507-GGUF | 14.3 GB | coding, tool-calling |
| Playable1-GGUF | 4.7 GB | coding |
| GLM-4.7-Flash-GGUF | 17.5 GB | tool-calling |
| granite-4.0-h-tiny-GGUF | 4.2 GB | tool-calling |

**Vision (multimodal):**
| Model | Size | Labels |
|-------|------|--------|
| Qwen2.5-VL-3B-Instruct-GGUF | 3.3 GB | vision |
| Qwen2.5-VL-7B-Instruct-GGUF | 6.0 GB | vision |
| Qwen3-VL-4B-Instruct-GGUF | 3.3 GB | vision |
| Qwen3-VL-8B-Instruct-GGUF | 6.2 GB | vision |
| Qwen2.5-Omni-3B-GGUF | 4.7 GB | vision, chat-transcription |
| Qwen2.5-Omni-7B-GGUF | 7.3 GB | vision, chat-transcription |
| Gemma-3-4b-it-GGUF | 3.3 GB | vision |
| Gemma-4-E2B-it-GGUF | 4.1 GB | tool-calling, vision |
| Gemma-4-E4B-it-GGUF | 6.0 GB | tool-calling, vision |
| Ministral-3-3B-Instruct-2512-GGUF | 3.0 GB | vision |
| Cogito-v2-llama-109B-MoE-GGUF | 65.4 GB | vision |

**Embeddings:**
| Model | Size |
|-------|------|
| nomic-embed-text-v1-GGUF | 0.1 GB |
| nomic-embed-text-v2-moe-GGUF | 0.5 GB |
| Qwen3-Embedding-0.6B-GGUF | 0.6 GB |
| Qwen3-Embedding-4B-GGUF | 4.3 GB |
| Qwen3-Embedding-8B-GGUF | 8.1 GB |

**Reranking:**
| Model | Size |
|-------|------|
| bge-reranker-v2-m3-GGUF | 0.6 GB |
| jina-reranker-v1-tiny-en-GGUF | <0.1 GB |

**Other chat:**
GLM-4.5-Air-UD-Q4K-XL-GGUF (67.7 GB, reasoning), gpt-oss-20b-GGUF (11.6 GB),
Jan-nano-128k-GGUF (2.5 GB), Jan-v1-4B-GGUF (2.5 GB),
PromptBridge-0.6b-Alpha-GGUF (0.4 GB), Tiny-Test-Model-GGUF (0.2 GB)

### vLLM backend (ROCm) — 5 models

| Model | Size | Labels |
|-------|------|--------|
| Qwen3.5-0.8B-vLLM | 1.8 GB | reasoning |
| Qwen3.5-2B-vLLM | 4.6 GB | reasoning |
| Qwen3.5-4B-vLLM | 9.3 GB | reasoning, hot |
| Qwen3.5-9B-vLLM | 19.3 GB | reasoning |

### sd-cpp (Stable Diffusion / Flux) — 10 models

| Model | Size | Labels |
|-------|------|--------|
| SD-Turbo-GGUF | 2.0 GB | image |
| SD-Turbo | 5.2 GB | image |
| SD-1.5 | 7.7 GB | image |
| SDXL-Turbo | 6.9 GB | image |
| SDXL-Base-1.0 | 6.9 GB | image |
| Flux-2-Klein-4B | 16.1 GB | image, edit |
| Flux-2-Klein-9B-GGUF | 19.0 GB | image, edit |
| Qwen-Image-GGUF | 18.2 GB | image |
| Qwen-Image-2512-GGUF | 19.4 GB | image |
| Z-Image-Turbo | 20.7 GB | image |

**Upscaling:** RealESRGAN-x4plus (0.1 GB), RealESRGAN-x4plus-anime (<0.1 GB)

### whispercpp (Transcription) — 6 models

| Model | Size | Labels |
|-------|------|--------|
| Whisper-Tiny | 0.1 GB | transcription, realtime-transcription |
| Whisper-Base | 0.1 GB | transcription, realtime-transcription |
| Whisper-Small | 0.5 GB | transcription, realtime-transcription |
| Whisper-Medium | 1.5 GB | transcription, realtime-transcription |
| Whisper-Large-v3 | 3.1 GB | transcription, realtime-transcription |
| Whisper-Large-v3-Turbo | 1.6 GB | transcription, realtime-transcription, hot |

### kokoro (TTS)
- kokoro-v1 — 0.4 GB, cpu backend

### ryzenai-llm (ONNX CPU/NPU/Hybrid) — 50+ models

Full list at `/opt/lemonade/resources/server_models.json` in the pod.
Not detailed here — these target Ryzen AI NPU or CPU fallback.

---

## Diagnosing problems

### Check pod health

```bash
kubectl get pod -n default -l app=lemonade
kubectl logs -n default -l app=lemonade --tail=50
kubectl describe pod -n default -l app=lemonade
```

### Check GPU is visible

```bash
kubectl get pod -n default -l app=lemonade -o jsonpath='{.items[0].status.containerStatuses[0].resources}'
# Should show amd.com/gpu: "1"

# In-pod: check ROCm
kubectl exec -n default deploy/lemonade -- /opt/lemonade/lemonade --help
# Note: needs full path /opt/lemonade/lemonade
```

### Check model download progress

Downloads stream `Progress: X%` lines to stdout. Watch with:
```bash
kubectl logs -n default -l app=lemonade -f | grep -E 'Progress|Download|Fetching'
```

### Model not found / empty response

The error message will tell you if a model doesn't exist:
```json
{"error":{"code":"model_not_found","message":"Model 'X' was not found. Available models include: ..."}}
```
Use the exact model ID from `GET /v1/models?show_all=true`.

### No models on disk after pod restart?

The PVCs are persistent but models weren't pre-downloaded. They download on first use.
Check disk:
```bash
kubectl exec -n default deploy/lemonade -- du -sh /opt/lemonade/llama /root/.cache/huggingface
```

### GPU-related env vars

| Var | Value | Purpose |
|-----|-------|---------|
| `HSA_OVERRIDE_GFX_VERSION` | 11.5.1 | ROCm: tell runtime the GPU ISA (Strix Point/Halo) |
| `PYTORCH_ROCM_ARCH` | gfx1151 | PyTorch: same ISA target |
| `HSA_XNACK` | 1 | Enable XNACK (unified memory) |
| `HSA_FORCE_FINE_GRAIN_PCIE` | 1 | Force fine-grained PCIe memory (iGPU unified memory) |
| `HF_HOME` | /root/.cache/huggingface | Hugging Face cache dir |
| `HF_TOKEN` | from secret | Hugging Face API token for gated models |

### Known warnings (benign)

```
rops_pt_init_destroy_netlink: netlink bind failed
```
ROCm sysfs netlink warning — doesn't affect inference. Safe to ignore.

---

## Connecting from outside the cluster

### Tailscale (recommended)

```
https://lemonade.manatee-basking.ts.net
```

OpenAI-compatible base URL:
```python
from openai import OpenAI
client = OpenAI(
    base_url="https://lemonade.manatee-basking.ts.net/v1",
    api_key="not-needed"
)
```

### Direct (same LAN)

```
http://192.168.0.6:31305   # NodePort
http://192.168.0.6:13305   # Direct (hostNetwork)
```
