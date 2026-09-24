# Punjab

Headless agent/dev box — the fleet's only AWS-hosted Ansible host. Lives in
the AWS account alongside the [AWS Talos cluster](../aws-k8s/cluster.md), but
in a different region and VPC; it is an ordinary fleet member, not a cluster
node.

## Hardware

- EC2 `t3.large` (2 vCPU, 8 GiB, unlimited CPU credits), `us-east-1d`
- 250 GB gp3 root volume (unencrypted)
- Instance `i-085690e02ca98c95a`, default VPC, private IP `172.31.32.13`
- Public IP is ephemeral (no Elastic IP) — changes on stop/start
- Tailscale: `punjab` / `100.78.73.8`

The instance, its security group and key pair are codified in
[`aws/punjab.tf`](https://github.com/hanthor/dotfiles/blob/master/aws/punjab.tf) —
see [AWS Account](../aws/README.md).

## OS

Ubuntu 24.04 LTS (stock `ubuntu-noble-24.04-amd64-server` AMI), AWS kernel.

## Role

- Agent host: Claude Code, Kiro, `pi`, run in tmux
- **Kiro Crew gateway** — `kirocrew.service` (system unit, runs as `ubuntu`,
  binary `~/.local/bin/kirocrew`, env `/etc/kirocrew/kirocrew.env`). Installed
  by hand; **not managed by Ansible**.
- AWS admin box: `awscli` + `opentofu` (via `extra_brews`) for the
  [AWS IaC](../aws/README.md)

## Access

- Normal: `ssh punjab` over Tailscale (inventory uses the tailnet IP).
- Break-glass: public SSH as `ubuntu` with the `punjab` EC2 key pair, allowed
  only from the CIDRs in `punjab_ssh_ingress` (tfvars). Update the allowlist
  with `just aws-apply` rather than in the console.
- AWS CLI: `aws login` (browser-based). It is currently logged in as the
  account **root** — prefer the scoped `james-admin` user for day-to-day work.

## Ansible notes (`host_vars/punjab.yml`)

- `skip_proxy: true` — no podman on stock Ubuntu, so no Caddy quadlet.
- Not a desktop: no GNOME/flatpak/browser roles.
- `syncthing` only runs if its brew binary exists (it currently doesn't).
