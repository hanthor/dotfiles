# pipewire_audio

**Unit:** `units/pipewire-audio.sh`  
**Tags:** `desktop`, `audio`, `pipewire`  
**Secrets needed:** No  
**Runs on:** desktops, except `skip_pipewire_audio: true` or `machine_profile: vm-test`.

The unit deploys native PipeWire filter chains from `units/pipewire-audio/`. It detects the LSP LV2 plugin and chooses the LSP speaker chain or built-in biquad fallback. It installs the RNNoise microphone chain and user `mic-dsp-link.service` when the RNNoise LADSPA plugin is found. `mic_hardware_volume_pct` comes from the environment, host/group variables or unit defaults and must be 0–100.

DSP prerequisites are installed with supported dnf, rpm-ostree or Arch package managers; these operations require root or non-interactive sudo. Other platforms report `PARTIAL`; bootc images must supply the prerequisites themselves. If plugin discovery is inconclusive, existing microphone configuration or speaker configuration is retained rather than assumed absent.

Only absent or recognized managed audio files are replaced or removed; custom configs and services are preserved and reported. The old managed WirePlumber rule is removed without deleting other rules. Restart requests are persisted under `~/.local/state/pipewire-audio` until the user systemd manager successfully reloads/restarts the affected services. A live user systemd session is required. GNOME over-amplification is best effort.

The unit removes the Easy Effects autostart entry and, if present, stops and uninstalls the system Flatpak; user presets and settings are preserved. Installation does not establish that DSP or microphone routing works on a particular device; inspect `wpctl status`, `pw-cli`, and the user PipeWire journal on the target.
