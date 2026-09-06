# Tuna OS agent personas

Six custom agent personas from [tuna-os/hive#12](https://github.com/tuna-os/hive/pull/12)
(which addresses tuna-os/hive#1), adapted for this fleet. **Not yet imported** —
the cluster node went unreachable mid-import on 2026-09-06.

## Split

Assigned by where each persona's target repos actually live:

| Spoke | Personas | Why |
|---|---|---|
| `hive` (school.tunaos.org) — **OS building** | `bootc-curator`, `packager`, `installer-qa` | tunaos, tromso, xfce-linux, remora, tuna-installer-*, bootc-installer*, wootc, tunaos-packages, debian-copr are all in this spoke's 32 repos |
| `hive-reef` (reef.tunaos.org) — **apps** | `desktop-integrator`, `upstream-shepherd`, `desktop-advocate` | blueshell, gtk-office-suite, mandelbrot, mariner, protota, dualcut are in this spoke's 20 repos |

## Changes from the PR

1. **`backend: claude` -> `codex`**, `claude-sonnet-4-6` -> `gpt-5.6-luna`,
   `claude-opus-5` -> `gpt-5.6-sol`. The PR pins the Claude backend, which has no
   working credential on this fleet, and `claude-sonnet-4-6` is not a rung in the
   ladder at all. Importing as written creates six agents that wedge at launch —
   the exact failure hive-watchdog spent 2026-09-06 repairing on hive-hanthor.
   These ids are confirmed present in `codex app-server model/list` and in the
   ladder; hive-rotate re-places by tier on its next pass anyway.
2. **`tunaOS` -> `tunaos`** in the webhook repo lists. The PR uses the display
   casing; the GitHub API list uses the real name.

## Import

`Content-Type: application/yaml` (as the PR README says) is rejected — the route
parses JSON. Convert first, and POST with an owner session cookie;
`X-Hive-Internal` is read-only and 405s on mutations.

```bash
python3 -c 'import yaml,json,sys; json.dump(yaml.safe_load(open(sys.argv[1])), sys.stdout)' bootc-curator.yaml > /tmp/a.json
kubectl cp /tmp/a.json hive/$POD:/tmp/a.json
kubectl exec -n hive $POD -- curl -sS -X POST \
  -H "Cookie: hive_session=$SID" -H 'Content-Type: application/json' \
  --data-binary @/tmp/a.json http://127.0.0.1:3002/api/agents/import
```
