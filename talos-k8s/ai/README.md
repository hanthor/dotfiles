# ai

AI/ML workloads targeting the AMD Strix Halo APU on karnataka.

- `lemonade.yaml` — Lemonade omni-modal AI runtime (chat, vision, image gen, speech, transcription)
- `lemonade-ops.md` — Operational notes and troubleshooting
- `lemonade-backup.yaml` — weekly rsync-over-SSH of the models/cache PVCs to bihar, plus a staleness check. Needs a `lemonade-backup-ssh` secret and a writable path on bihar seeded manually first — see the comments at the top of the file.
