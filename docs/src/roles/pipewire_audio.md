# pipewire_audio

**Tags:** `desktop`, `audio`, `pipewire`  
**Secrets needed:** No  
**Runs on:** Desktop group only

Replaces Easy Effects with native PipeWire `filter-chain` modules using LSP LV2 and LADSPA plugins — no Flatpak, no GUI, no D-Bus service.

## What It Does

1. Deploys `speaker-dsp.conf` — a PipeWire filter-chain that creates a virtual "Speakers (DSP)" sink
2. Deploys `mic-dsp.conf` — a PipeWire filter-chain that creates a virtual "Microphone (DSP)" source
3. Configures WirePlumber to prefer the DSP nodes as default devices
4. Cleans up any previous Easy Effects installation (Flatpak, autostart, presets)

## Output Chain: Speaker DSP

Signal path: **16-band Parametric EQ → Bass Enhancer → Exciter → Limiter** (all LSP LV2).

| Stage | LV2 Plugin | What It Does |
|-------|-----------|--------------|
| `eq` | LSP ParaEQ x16 LR | Corrective loudness curve with subsonic HPF @ 120 Hz |
| `bass` | LSP Bass Enhancer | Harmonic bass synthesis for small speakers |
| `exciter` | LSP Exciter | Crystalizer substitute — adds presence and air |
| `lim` | LSP Limiter | Brickwall peak limiter @ -0.5 dBFS |

The EQ curve is a direct translation of the Easy Effects 15-band preset — ~2.5 dB cut through low-mids (220-600 Hz), ~3.5 dB peak at 3.2 kHz, tapering to ~1.5 dB boost above 8 kHz.

**Simplification:** To run just EQ + Limiter (the most critical, crash-proof chain), comment out the `bass` and `exciter` nodes in `speaker-dsp.conf` and remove their links.

## Input Chain: Microphone DSP

Signal path: **RNNoise → Compressor** (LADSPA + LSP LV2).

| Stage | Plugin | What It Does |
|-------|--------|--------------|
| `rnnoise` | librnnoise\_ladspa.so | Real-time neural network noise suppression (VAD-enabled) |
| `comp` | LSP Compressor Stereo | Downward compression, -24 dB threshold, 2:1 ratio |

## Bootc Image Requirements

These packages must be in the bootc image (`Containerfile`):

```
lsp-plugins-lv2
noise-suppression-for-voice
```

The filter-chain configs reference:
- LSP LV2 bundles under `/usr/lib64/lv2/` (Fedora default LV2 path)
- RNNoise LADSPA at `/usr/lib64/ladspa/librnnoise_ladspa.so`

## Verifying

On a target machine after deploy:

```bash
# Check DSP nodes appeared
pw-cli ls Node | grep -E 'speaker_dsp|mic_dsp'

# Check defaults
wpctl status | head -20

# Watch for plugin loading errors
journalctl --user -u pipewire -f | grep -iE 'error|filter-chain|lv2'

# Verify LSP plugins are discoverable
lv2ls | grep lsp-plug
lv2info http://lsp-plug.in/plugins/lv2/para_equalizer_x16_lr | head -5

# Verify LADSPA plugin
ls /usr/lib64/ladspa/librnnoise_ladspa.so
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| DSP node doesn't appear | LSP/LADSPA plugins missing from bootc image | Verify with `lv2ls`, `ls /usr/lib64/ladspa/` |
| Port name mismatch | LSP plugin version changed port symbols | Run `lv2info <uri> \| grep 'port.*symbol'` and update config |
| Audio routing loop | PipeWire/WirePlumber bug | Don't set the DSP sink as default manually; let WirePlumber handle it |
| No bass enhancer/exciter effect | Plugin UID mismatch | Comment them out in config for a leaner chain |

## Notes

- PipeWire must be restarted after deploying configs (handled by Ansible handlers)
- Select "Speakers (DSP)" and "Microphone (DSP)" in GNOME Sound settings if WirePlumber doesn't auto-select them
- The virtual sink approach works because PipeWire prevents self-looping when capture/playback share the same `node.name`
- To skip: use `skip_flatpak: true` or exclude the pipewire_audio tag
