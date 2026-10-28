# pipewire_audio

**Unit:** `units/pipewire-audio.sh`  
**Tags:** `desktop`, `audio`, `pipewire`  
**Secrets needed:** No  
**Runs on:** desktops, except `skip_pipewire_audio: true` or `machine_profile: vm-test`.

The unit deploys native PipeWire filter chains from `units/pipewire-audio/`. It detects the LSP LV2 plugin and chooses the LSP speaker chain or built-in biquad fallback. It installs the RNNoise microphone chain and user `mic-dsp-link.service` when the RNNoise LADSPA plugin is found. The service extracts the source name from `pactl`'s tab-separated output and escapes the volume percent for systemd; the unmodified Ansible service is recognized and upgraded. `mic_hardware_volume_pct` comes from the environment, host/group variables or unit defaults and must be 0–100.

DSP prerequisites are installed with supported dnf, rpm-ostree or Arch package managers; these operations require root or non-interactive sudo. When rpm-ostree and dnf are both present, rpm-ostree is used. Other platforms report `PARTIAL`; bootc images must supply the prerequisites themselves and the unit does not attempt host package changes. If plugin discovery is inconclusive, existing microphone configuration or speaker configuration is retained rather than assumed absent.

Only absent or recognized managed audio files are replaced or removed; custom configs and services are preserved and reported. The old managed WirePlumber rule is removed without deleting other rules. Restart requests are persisted under `~/.local/state/pipewire-audio` until the user systemd manager successfully reloads/restarts the affected services. After a PipeWire or WirePlumber restart, the managed microphone link service is also restarted to recreate its audio links; failed restarts are retried on the next apply. A live user systemd session is required. GNOME over-amplification is best effort.

The unit removes the Easy Effects autostart entry and, if present, stops and uninstalls the system Flatpak; user presets and settings are preserved. Installation does not establish that DSP or microphone routing works on a particular device; inspect `wpctl status`, `pw-cli`, and the user PipeWire journal on the target.

The link service selects the first ALSA input, assumes stereo capture ports, and waits up to five seconds for it. It tolerates missing devices and link failures, so an active oneshot does not prove routing succeeded; it does not automatically relink after later hotplug or an audio-daemon restart outside this unit.
