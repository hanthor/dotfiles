# Hive — Upstream Diff Analysis

Last updated: 2026-06-03

## Changes vs upstream (kubestellar/hive v2)

### 1. Source patch: `goose-marker.patch`

**What**: Added `"goose"` to `cliPaneMarkers` in `v2/pkg/agent/manager.go`

**Why**: Goose v1.x doesn't output any of the existing markers (`❯`, `Claude`, `Copilot`, `Gemini`). Without this, hive detects goose sessions as "bare shell" crashes and restarts them every 5 minutes.

**Upstream value**: HIGH. Without this, goat v1.x is unusable as a hive backend. Should be upstreamed as a one-line PR.

```diff
+ 	"goose",
```

### 2. Dockerfile rewrite

**What**: Complete custom Dockerfile vs upstream multi-stage build.

**Why**: 
- Pre-compile Go binaries on host (cross-compilation) → faster CI, avoids building Go in container
- Use apt tmux vs building from source → smaller, faster build
- Remove Claude Code, Copilot CLI, ttyd, Nous → not needed for our use case, cuts image by ~1GB
- Add goose v1.36 binary → DeepSeek backend
- Add goose-wrapper.sh, deepseek-chat.py → compatibility layer

**Upstream value**: MEDIUM. The pre-compile approach is a useful CI optimization. The goose additions are provider-specific.

### 3. Goose wrapper: `goose-wrapper.sh`

**What**: Translates old hive `goose --no-confirm --model X` to `goose v1.x session --max-turns 100`.

**Why**: Goose v1.x completely changed its CLI. Old interface: `goose --no-confirm`. New interface: `goose session --max-turns 100`. Also handles first-run telemetry prompt via `(echo y; exec cat)`.

**Upstream value**: HIGH. Needed for goose v1.x compatibility. Could be upstreamed as `/usr/local/bin/goose` wrapper in the hive image.

### 4. Python fallback: `deepseek-chat.py`

**What**: Direct DeepSeek API calls via OpenAI-compatible endpoint.

**Why**: Fallback when goose isn't available or crashes. Simpler, smaller, avoids goose's ~80MB download and telemetry complexity.

**Upstream value**: MEDIUM. Useful as a lightweight backend template for any OpenAI-compatible API (DeepSeek, OpenRouter, xAI, etc.).

### 5. Project config: `hive.yaml`

**What**: Our specific project configuration.

**Why**: Two repos (tuna-os/tunaos, tuna-os/tacklebox), ACMM L3, ISSUES_AND_PRS mode overrides, surge threshold 50, GitHub App auth.

**Upstream value**: NONE. Project-specific, not upstreamable.

### 6. Auto-close workflow: `auto-close-boot-reports.yml`

**What**: GitHub Action to auto-close boot-report issues after 7 days.

**Why**: Weekly boot reports from tuna-os CI accumulate and inflate hive's issue count, triggering SURGE mode unnecessarily.

**Upstream value**: LOW. Repo-specific automation.

## What we learned

### Goose provider naming
Provider ID is `custom_deepseek` not `deepseek` or `openai_compatible`. Goose's configure wizard lists "DeepSeek" but the actual provider key is different. This is undocumented.

### Goose telemetry
Goose v1.x shows first-run telemetry prompt that reads from `/dev/tty`, not stdin. Pre-configuring `state.json` doesn't suppress it. Workaround: pipe "y\n" via stdin + keep pipe open with `cat`.

### IPv6 / ghcr.io
Talos containerd prefers IPv6 for ghcr.io which times out on some networks. Fix: `/etc/hosts` entry forcing IPv4. This is a cluster-level workaround, not a hive issue.

### ACMM level ≠ agent mode
Setting `acmm_level: 3` alone doesn't make agents create issues. L3 defaults scanner to ADVISORY. Need explicit `mode: ISSUES_AND_PRS` on each agent.

## Recommendations

### Short term (upstream PRs)
1. **goose-marker.patch** → PR to kubestellar/hive v2: add "goose" to cliPaneMarkers
2. **goose-wrapper.sh** → PR: add goose v1.x compatibility wrapper
3. **Document custom_deepseek** → PR: update backends.conf/docs with correct provider ID

### Medium term
4. Abstract the backend compatibility layer so backend CLIs (goose, claude-code, etc.) can declare their own pane markers and startup signals
5. Add a `--provider` flag to agent config that maps to env vars automatically
