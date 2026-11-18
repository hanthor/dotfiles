# home-k3s/ — single-node k3s on bihar and karnataka

Each host runs its own k3s on Bluefin, bound to its tailnet IP. These kits were
copied from `~/home-k3s` on each host on 2026-11-18. They replace the archived
`talos-k8s/`.

- `bihar/`: k3s, firewall, `reset-k3s.sh`, and KubeStellar notes (hub: ITS `its1`, WDS `wds1`).
- `karnataka/`: k3s, `apply-stack.sh` (KubeVirt, CDI, corral-web, AMD GPU plugin,
  Lemonade), front-door, and Frappe LMS. Secrets (for example `Secret/lms-secrets`)
  are created out of band and are never stored here.

Handbook: [docs/src/servers/home-k3s.md](../docs/src/servers/home-k3s.md),
[bihar](../docs/src/servers/bihar.md), [karnataka](../docs/src/servers/karnataka.md).
