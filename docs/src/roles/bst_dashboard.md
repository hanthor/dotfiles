# bst_dashboard

**Tags:** `services`, `bst_dashboard`  
**Secrets needed:** No  
**Runs on:** Machines with build infrastructure

Deploys a BuildStream build monitoring dashboard.

## What It Does

1. Creates dashboard directory based on hostname
2. Deploys dashboard web UI files
3. Configures dashboard to track local BuildStream build queues

## Access

Proxied through Caddy at `https://<host>.manatee-basking.ts.net/bst/`.

## Notes

- Used to monitor BuildStream build jobs on machines that run builds
- Dashboard shows build queue status, job history, and artifact cache
