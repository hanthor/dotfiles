# fleet_facts

Publishes each machine's **public** device facts for the live fleet view at
[reilly.asia/infra](https://reilly.asia/infra/#fleet).

- **Runs on:** every host (opt out with `fleet_facts_publish: false`), last in
  the play, including the no-secrets daily timer
- **Tags:** `facts`, `fleet_facts`
- **Needs:** a logged-in `gh` CLI (skipped quietly otherwise)

Each run writes `facts/<host>.json` to the **`fleet-facts`** branch of this
repo through the GitHub contents API. There's no clone and no merge, and
`master` isn't touched. The Worker behind reilly.asia/infra reads those files.

| Field | Source |
|---|---|
| `os.{name,version,codename,kernel}` | Ansible distribution facts |
| `hardware.model` | Android `getprop`, else device-tree model (Pi), else DMI product name (placeholders like "System Product Name" dropped) |
| `hardware.{vendor,form_factor,arch,cpu,cpu_threads,memory_gb}` | Ansible hardware facts |
| `hardware.gpus` | `lspci -mm` display devices (unnamed virtual adapters dropped) |
| `virtualization`, `uptime_days`, `last_apply` | Ansible facts, `~/.cache/dotfiles/last-apply.json` |

**Never published:** IP/MAC addresses, serial numbers, usernames, anything
from Bitwarden.
