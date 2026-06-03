# syncthing

**Tags:** `services`, `syncthing`  
**Secrets needed:** No  
**Runs on:** All except VPS

Deploys Syncthing as a systemd user service for continuous file synchronization.

## What It Does

1. Creates systemd user directory
2. Deploys `syncthing.service` user unit
3. Enables and starts the service

## Notes

- Runs as the user's systemd service (not system-wide)
- Web UI available at `http://localhost:8384`
- Skipped on VPS hosts (no file sync needed)
