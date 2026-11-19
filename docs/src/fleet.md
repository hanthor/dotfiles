# Fleet status

Snapshot of **2026-11-18**, made from `tailscale status` and the live hosts.
Update this page when a host changes role. To refresh it, run
`tailscale status --json | jq -r '.Peer[] | [.HostName,.Online,.LastSeen] | @tsv'`.

## How it fits together

```
Internet ─▶ Cloudflare ─▶ spindle (Oracle, Frankfurt): Caddy, Matrix, LiveKit, OMP auth broker, hive failover coordinator
                               │ tailnet
           ┌───────────────────┴────────────────────┐
           ▼                                        ▼
   bihar (home, WiFi)                        karnataka (home)
   k3s + KubeStellar hub                     k3s + KubeVirt + ARC runners + LMS
   hives: ACTIVE ───── hive-sync 15 min ───▶ hives: cold standby
                                             └─ VM: punjab (agent box, Ansible host)
```

## Live hosts

| Host | Kind | OS | Role | Docs |
|---|---|---|---|---|
| **bihar** | Home server (Intel, 62 GB) | Bluefin utah:testing | Active hive host; k3s + KubeStellar hub | [Bihar](servers/bihar.md) |
| **karnataka** | Home server (AMD Strix Halo, 125 GB) | Bluefin utah:testing | k3s: KubeVirt VMs, CI runners, LMS, Corral; hive standby | [Karnataka](servers/karnataka.md) |
| **spindle** | Oracle A1 VM, eu-frankfurt-1 (2 ARM cores, 12 GB) | Ubuntu 24.04 | Public front door (Caddy, `92.5.82.232`), Matrix (`reilly.asia`), LiveKit, OMP auth broker, hive failover coordinator | [Spindle VPS](servers/spindle-vps/README.md) |
| **punjab** | KubeVirt VM on karnataka (12 vCPU, 23 GB, 500 GB) | Ubuntu 24.04 | Agent box and fleet Ansible host. **Disk 96% full.** | [Punjab](servers/punjab/README.md) |
| **corral** | Tailscale sidecar pod on karnataka | n/a | Tailnet name for `corral-web` | [Karnataka](servers/karnataka.md) |
| **pixel-9a** (`termux`) | Phone | Android + Termux | Ansible `termux` host | [Inventory](inventory.md) |

Cross-host services:
- The hives (school, reef, hanthor, hub) are on bihar. If bihar fails, they move to karnataka. See [Hives hosting](servers/hives.md).
- KubeStellar is described in [Home k3s and KubeStellar](servers/home-k3s.md).

## Intermittent (desktops and laptops)

| Host | Last seen | Notes | Docs |
|---|---|---|---|
| kerala (`kerala-1`) | 2026-11-17 | Desktop. Earlier tailnet node `kerala` last seen 2026-08-29 | [Kerala](desktop/kerala/README.md) |
| himachal / himachal-1 | 2026-11-09 / 2026-11-10 | Desktop. Two tailnet nodes; remove the earlier one | [Himachal](desktop/himachal/README.md) |
| dilli | 2026-10-21 | Desktop | [Dilli](desktop/dilli/README.md) |
| kanpur | 2026-07-21 | Desktop or Windows test machine | [Kanpur](desktop/kanpur/README.md) |
| mumbai | 2026-07-20 | Debian VM on the phone | [Inventory](inventory.md) |
| goa | 2026-07-08 | Server | [Goa](servers/goa/README.md) |
| MacBook Air (2 nodes), CMF Phone 1 | 2026-10 | Personal devices, not managed | none |

## Retired

| Host | Retired | Notes | Docs |
|---|---|---|---|
| Home Talos cluster (bihar and karnataka on Talos) | 2026-10/11 | Replaced by Bluefin + k3s on the same hardware | [Archive](archive/talos-k8s.md) |
| AWS Talos cluster (eu-north-1) | 2026-10-25 | Terminated. Configurations kept as recovery material | [Archive](servers/aws-k8s/cluster.md) |
| punjab EC2 (`punjab-aws-retired`, 100.78.73.8) | 2026-10-28 | Replaced by the punjab VM on karnataka | [Punjab](servers/punjab/README.md) |
| matrix (`reilly-asia-matrix`), telengana | 2026-09 | Hetzner VPSes | [Archive](archive/vps/matrix/README.md) |
| Hives on spindle (`/srv/hives`) | 2026-11-18 | Moved to bihar. The copy is stopped and kept for rollback | [Hives hosting](servers/hives.md) |

### Tailnet nodes to remove

The tagged devices from the retired clusters are offline and can be deleted from
the Tailscale admin console. On 2026-11-18 these were:
- since 2026-07: `appflowy*`, `argocd`, `auth`, `forgejo`, `grafana`, `loki`, `prometheus`, `n8n`, `lemonade`, `home`, `kubevirt-manager*`, `default-deepseek-14b`, `repro-ctr-vm-vm`, `gate-*-vm`
- since 2026-10-25: `hive`, `hive-auth-egress-0/1`, `review`, `search`, `spindle-grafana`, `aws-migration-operator`, `tuna-v1-preflight-*`
- since 2026-09: `tailscale-operator*`, `secret-broker`
- since 2026-04: `uisp`, `chuppvm`
- since 2026-07 and 2026-08: `vm`, `WIN-G9NAVN79GN0`

[hanthor/dotfiles#333](https://github.com/hanthor/dotfiles/pull/333) (`scripts/tailnet.py`) automates this cleanup.
