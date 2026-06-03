# easyeffects

**Tags:** `desktop`, `audio`, `easyeffects`  
**Secrets needed:** No  
**Runs on:** Desktop group only

Installs and configures Easy Effects (PipeWire audio processor) via Flatpak with noise-reduced mic input and speaker improvement presets.

## What It Does

1. Creates Flatpak config directories for preset storage
2. Deploys two audio presets:
   - **Input** — RNNoise voice-activity noise suppression + downward compressor
   - **Output** — 15-band equalizer (loudness contour for small speakers) + crystalizer + bass enhancer
3. Creates a GNOME autostart entry so Easy Effects launches on login

## Input Preset: `input-mic-noise-reduction`

| Plugin | Purpose |
|--------|---------|
| RNNoise | Real-time neural network noise suppression with voice activity detection |
| Compressor | Downward compression, -24dB threshold, 2:1 ratio, 5ms attack |

## Output Preset: `output-speaker-improvement`

| Plugin | Purpose |
|--------|---------|
| Equalizer (15-band) | Loudness contour: +6dB sub-bass, scooped mids, +5dB treble |
| Crystalizer | Adds sparkle and clarity to high frequencies |
| Bass Enhancer | Harmonic bass synthesis for small speakers that can't reproduce low frequencies |

## Preset Storage

Presets are deployed to `~/.var/app/com.github.wwmm.easyeffects/config/easyeffects/` (Flatpak config path) in the current Easy Effects JSON schema with `plugins_order` arrays and named plugin instances.

## Notes

- On first login, open Easy Effects and select the presets — they persist across restarts
- To skip: add `skip_easyeffects: true` to `host_vars`
