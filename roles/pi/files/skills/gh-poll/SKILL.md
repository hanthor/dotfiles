---
name: gh-poll
description: Poll a GitHub Actions workflow run in the foreground with a configurable polling loop, then download and inspect artifacts. Blocks until the run completes or the max polls are exhausted, printing a status timestamp each iteration. Use when the user wants to wait for a CI run to finish, monitor a dispatched workflow, or when watch_workflow_run / wait tools are unavailable or failing.
---

# gh-poll

Poll a `gh run` to completion with a foreground loop, then download artifacts for diagnosis.

## Quick Start

```bash
for i in $(seq 1 12); do
  sleep 300
  status=$(gh run view <run-id> --json status,conclusion -q '[.status, .conclusion] | join(" ")' 2>&1)
  echo "$(date +%H:%M:%S) $status"
  if echo "$status" | grep -q "completed"; then break; fi
done
```

## Parameters

| Parameter | Default | Purpose |
|-----------|---------|---------|
| polls | 12 | Max iterations |
| interval | 300 | Seconds between checks (5 min) |

Timeout = polls × interval. Example: 12 × 300s = 60 min.

## Variation: shorter polls

For fast workflows (<10 min expected):

```bash
for i in $(seq 1 30); do
  sleep 60
  status=$(gh run view <run-id> --json status,conclusion -q '[.status, .conclusion] | join(" ")' 2>&1)
  echo "$(date +%H:%M:%S) $status"
  if echo "$status" | grep -q "completed"; then break; fi
done
```

## After completion: inspect results

```bash
# Conclusion only
gh run view <run-id> --json conclusion -q .conclusion

# Failed jobs
gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | .name'

# Error log tail
gh run view <run-id> --log 2>&1 | grep -iE "error|fatal|exit status|command not found" | tail -20
```

## After completion: download artifacts for deep diagnosis

Boot gate workflows upload serial logs and screenshots as artifacts. Download and inspect them:

```bash
# List artifacts
gh run view <run-id> --json jobs --jq '.jobs[] | select(.name | contains("Gate")) | .databaseId'

# Download an artifact by name (get name from the workflow log "Upload ... evidence" step)
gh run download <run-id> -n boot-gate-yellowfin-gnome -D /tmp/gate-artifact

# Inspect serial log
tail -80 /tmp/gate-artifact/serial.log

# Search for key markers
grep -iE "TUNAOS_DESKTOP_CONTRACT|TUNAOS_LIVE_READY|gdm|graphical|poweroff|shutdown" /tmp/gate-artifact/serial.log

# Check screenshot (download as .ppm or .png)
ls -la /tmp/gate-artifact/*.png /tmp/gate-artifact/*.ppm
```
