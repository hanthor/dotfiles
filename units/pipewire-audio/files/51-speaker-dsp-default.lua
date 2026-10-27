-- WirePlumber default-device rule for PipeWire DSP
--
-- Ensures "Speakers (DSP)" and "Microphone (DSP)" are selected as
-- the default audio devices over hardware directly.
--
-- Works in concert with the priority.session values set in the
-- filter-chain configs (speaker-dsp.conf, mic-dsp.conf).
--
-- If the DSP nodes don't appear after PipeWire restart:
--   journalctl --user -u wireplumber -f
--   journalctl --user -u pipewire -f

-- ── Speaker DSP as default sink ──────────────────────────────────
rule_speaker = {
  matches = {
    {
      { "node.name", "equals", "speaker_dsp" },
    }
  },
  apply_properties = {
    ["priority.session"] = 2000,
    ["priority.driver"]  = 2000,
  }
}
table.insert(alsa_monitor.rules, rule_speaker)

-- ── Mic DSP as default source ────────────────────────────────────
rule_mic = {
  matches = {
    {
      { "node.name", "equals", "mic_dsp" },
    }
  },
  apply_properties = {
    ["priority.session"] = 2000,
    ["priority.driver"]  = 2000,
  }
}
table.insert(alsa_monitor.rules, rule_mic)
