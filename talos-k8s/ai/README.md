# ai

AI/ML workloads targeting the AMD Strix Halo APU on karnataka.

- `lemonade.yaml` — Lemonade omni-modal AI runtime (chat, vision, image gen, speech, transcription)
- `lemonade-ops.md` — Operational notes and troubleshooting
- `lemonade-models.txt` — canonical list of essential models to pre-download
- `lemonade-warmup.sh` — re-downloads the models in `lemonade-models.txt` via the API; see "Disaster recovery" in `lemonade-ops.md`
- `lemonade-backup.yaml` — weekly verified mirror of the models/cache PVCs from karnataka to an in-cluster rsync daemon on bihar (Talos has no sshd), plus a staleness check. Needs the `lemonade-backup-rsync` secret created first — see "Backup to bihar" in `lemonade-ops.md`.
