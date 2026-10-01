# ai

AI/ML workloads targeting the AMD Strix Halo APU on karnataka.

- `lemonade.yaml` — Lemonade omni-modal AI runtime (chat, vision, image gen, speech, transcription)
- `lemonade-ops.md` — Operational notes and troubleshooting
- `lemonade-models.txt` — canonical list of essential models to pre-download
- `lemonade-warmup.sh` — re-downloads the models in `lemonade-models.txt` via the API; see "Disaster recovery" in `lemonade-ops.md`
- `lemonade-backup.yaml` — weekly rsync-over-SSH of the models/cache PVCs to bihar, plus a staleness check. Needs a `lemonade-backup-ssh` secret and a writable path on bihar seeded manually first — see the comments at the top of the file.
