---
name: lemonade-server
description: Call the local Lemonade AI server (OpenAI-compatible API) for chat, vision, image generation, TTS, transcription, and embeddings. Use when the user wants to use Lemonade, generate images, transcribe audio, chat with local models, or needs on-prem AI inference. The server runs at https://lemonade.manatee-basking.ts.net/v1 on the Talos K8s cluster (AMD Strix Halo APU).
---

> **Unavailable as of 2026-08-27:** Lemonade runs on the home Talos cluster
> (bihar/karnataka), which is powered down and in storage. Calls will fail
> until it is back online.

# Lemonade Server API

Local AI runtime on `karnataka` (AMD Strix Halo iGPU, 62GB unified memory).
OpenAI-compatible API at `https://lemonade.manatee-basking.ts.net/v1`.

## Quick reference

```bash
# Chat
curl -s https://lemonade.manatee-basking.ts.net/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"Gemma-4-12B-it-GGUF","messages":[{"role":"user","content":"Hello"}]}'

# List models
curl -s https://lemonade.manatee-basking.ts.net/v1/models | python3 -m json.tool

# Embeddings
curl -s https://lemonade.manatee-basking.ts.net/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model":"Qwen3-Embedding-0.6B-GGUF","input":"text to embed"}'
```

## Models (8/99 downloaded)

| Model | Size | Context | Labels | Best for |
|-------|------|---------|--------|----------|
| Bonsai-1.7B-gguf | 0.25 GB | 32K | tool-calling | Fast tool calls, simple tasks |
| Qwen3-0.6B-GGUF | 0.38 GB | 40K | reasoning, tool-calling | Quick reasoning |
| Qwen3-Embedding-0.6B-GGUF | 0.64 GB | 32K | embeddings | Embeddings/vector search |
| Gemma-4-12B-it-GGUF | 7.12 GB | 262K | tool-calling | General chat, large context |
| Qwen3.6-27B-GGUF | 18.5 GB | 262K | vision, tool-calling | Vision tasks, complex reasoning |
| Gemma-4-31B-it-GGUF | 19.5 GB | 262K | vision, tool-calling, hot | Best general model (kept loaded) |
| Qwen3.6-35B-A3B-MTP-GGUF | 23.8 GB | 262K | vision, tool-calling, mtp | Mixture-of-experts, speculative decoding |
| kokoro-v1 | 0.35 GB | — | tts | Text-to-speech |

Models with `hot` label stay loaded in VRAM. Others auto-load on first request (~15-30s cold start).

## Endpoints

### Chat & text
- `POST /v1/chat/completions` — OpenAI chat (streaming: `"stream":true`)

### Vision
- Use `Gemma-4-31B-it-GGUF` or `Qwen3.6-27B-GGUF` with `image_url` content blocks

### Image generation
- `POST /v1/images/generations` — SD/Flux/Qwen-Image
- `POST /v1/images/edits` — Image-to-image (Flux-2-Klein)
- `POST /v1/images/upscale` — RealESRGAN upscaling

### Audio
- `POST /v1/audio/transcriptions` — Whisper STT (multipart form: model + file)
- `POST /v1/audio/speech` — TTS (`kokoro-v1`, returns audio bytes)

### Embeddings & rerank
- `POST /v1/embeddings` — `Qwen3-Embedding-0.6B-GGUF` (32K ctx)
- `POST /v1/rerank` — jina-reranker, bge-reranker

### Model management
- `POST /api/pull` — Download model from HuggingFace (`{"name":"model-name"}`)
- `DELETE /api/delete` — Remove model from disk
- `POST /v1/unload` — Unload model from VRAM

## Usage notes

- **No auth required** — server is internal-only on Tailnet
- **Streaming**: add `"stream":true` to chat requests, responses come as SSE
- **Cold starts**: models not marked `hot` take 15-30s to load from disk on first request
- **Vision**: pass base64 images or URLs in `image_url` content blocks
- **Context windows**: all downloaded models support 32K+ tokens
- **Auto-download**: requesting an undownloaded model pulls it from HuggingFace (requires `HF_TOKEN` env on server)
