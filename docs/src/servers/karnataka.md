# Karnataka

The main home workload server: k3s with KubeVirt (punjab and the test VMs run
here), GitHub Actions runners, Frappe LMS, Corral, and the cold standby for the
hives. Since late 2026-10 it runs Bluefin, not Talos. The
[Talos page](../archive/talos-home-cluster/karnataka/README.md) is archived.

| | |
|---|---|
| Hardware | AMD Strix Halo APU (32 threads, integrated GPU), 125 GB of RAM |
| Disk | 912 GB NVMe (`/var`), **88% used on 2026-11-18** |
| OS | Bluefin `ghcr.io/projectbluefin/utah:testing` |
| Tailnet | `karnataka` / `100.66.158.127` |
| Access | `ssh james@karnataka` (passwordless sudo). `kubectl` from punjab uses `~/.kube/config` |
| Ansible | Yes: [`host_vars/karnataka.yml`](https://github.com/hanthor/dotfiles/blob/master/host_vars/karnataka.yml) |

## k3s

k3s v1.36.5+k3s1 runs as a binary in `/var/usrlocal/bin`. It binds to the tailnet IP
only, uses flannel on `tailscale0`, and has traefik and servicelb disabled. The kit is in
[`home-k3s/karnataka/`](https://github.com/hanthor/dotfiles/tree/master/home-k3s/karnataka):
- `install-host.sh` installs k3s.
- `apply-stack.sh` installs KubeVirt v1.9.1, CDI v1.66.1, corral-web, the AMD GPU
  device plugin and Lemonade.

See [Home k3s and KubeStellar](home-k3s.md) for the shared design and the firewalld rules.

### Workloads (2026-11-18)

| Namespace | What | Exposed as |
|---|---|---|
| `corral-vms` | KubeVirt VMs: **punjab** (agent box, 500 Gi root), `messages` and the `macos-beeper*` disks (macOS for Beeper/iMessage), tuna-q test VMs, `mandelbrot-visual` (stopped) | punjab is on the tailnet |
| `corral` | `corral-web` (VM manager UI) and its Tailscale sidecar | `https://karnataka.manatee-basking.ts.net/`, tailnet node `corral` |
| `front-door` | Caddy link page and redirects (`/course`, `/learn`, `/frappe`, `/books`, `/corral`) | `http://karnataka/` |
| `lms` | Frappe Learning v16.1.0 (`frappe`, `db`, `redis`), local image from `frappe-lms-image/` | `https://karnataka.manatee-basking.ts.net:8443` |
| `beale` | `beale-course` (course site) | `beale.karnataka.ts.net` |
| `beeper-bridges` | `rustpush` (iMessage bridge) | none |
| `arc-systems`, `tuna-ci`, `tuna-ci-storage` | GitHub Actions runner scale sets `tuna-ci-24.04` (1-6), `tuna-ci-26.04` (0-2), `tuna-iso-gpu` (0-1), with scratch storage | none |
| `lemonade` | Lemonade AMD LLM server, **scaled to 0** | `:13305` (tailscale serve) |
| `open-cluster-management-agent*` | KubeStellar WEC agent for the hub on bihar | none |

`tailscale serve` (tailnet only):
- `:80` goes to front-door.
- `:443` goes to corral-web.
- `:8443` goes to LMS.
- `:8444` goes to `127.0.0.1:8080` (RaveBSD books).
- `:13305` goes to Lemonade.

## Hive standby

`/var/srv/hives` is a copy of the hive data. When bihar is active, bihar pushes it
here every 15 min. The containers stay stopped until the lease on spindle names
karnataka. See [Hives hosting and failover](hives.md).

## Notes

- **Disk:** `/var` is 88% full. The ARC runner PVCs and the macOS VM disks use most of
  the space. Check this before you add VMs.
- punjab is a VM on this host. If karnataka restarts, punjab also restarts.
