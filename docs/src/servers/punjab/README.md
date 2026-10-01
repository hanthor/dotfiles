# Punjab

> **TunaOS infrastructure.** This runs in the TunaOS AWS account and serves
> the TunaOS project (Hive, Matrix, CI), not James's personal fleet. See
> [TunaOS AWS Account & IaC](../aws/README.md).

Headless agent/dev box — the fleet's only AWS-hosted Ansible host. Lives in
the AWS account alongside the [AWS Talos cluster](../aws-k8s/cluster.md), but
in a different region and VPC; it is an ordinary fleet member, not a cluster
node.

## Hardware

- EC2 `t3.large` (2 vCPU, 8 GiB, unlimited CPU credits), `us-east-1d`
- 250 GB gp3 root volume (unencrypted — predates EBS encryption-by-default;
  snapshotted daily ×7 / weekly ×4 by DLM)
- Default VPC, stable Elastic IP
- IMDSv2 required, hop limit 1; termination protection on
- Instance role: Session Manager only
- Tailscale: `punjab` (MagicDNS)

The instance, its security group and key pair are codified in
[`aws/punjab.tf`](https://github.com/hanthor/dotfiles/blob/master/aws/punjab.tf) —
see [AWS Account](../aws/README.md).

## OS

Ubuntu 24.04 LTS (stock `ubuntu-noble-24.04-amd64-server` AMI), AWS kernel.

## Role

- Agent host: Claude Code, Kiro, `pi`, run in tmux
- **Kiro Crew gateway** — `kirocrew.service` (system unit, runs as `ubuntu`,
  binary `~/.local/bin/kirocrew`, env `/etc/kirocrew/kirocrew.env`). Installed
  with Kiro's own installer; the [`kirocrew`](../../roles/kirocrew.md) role keeps
  it running, its env file root-only, and its dashboard on localhost.
- AWS admin box: `awscli` + `opentofu` (via `extra_brews`) for the
  [AWS IaC](../aws/README.md)

## Access

- **Normal**: `ssh punjab` over Tailscale.
- **Break-glass** (Tailscale down): SSM Session Manager, no open port needed:
  ```bash
  aws ssm start-session --region us-east-1 --target <instance-id>
  ```
  (needs `session-manager-plugin`; the instance ID is in the OpenTofu state).
- **Cluster**: `kubectl`/`talosctl` work from here with
  `~/.kube/config-aws-migration` / `~/.talos/config-aws-migration`.
- **AWS CLI**: prefer the scoped admin user; it can plan the whole config
  (read-only IAM). Log in as root (`aws login`) only for IAM changes, and don't
  leave a root session lying around on a shared box.

## Host hardening

- sshd drop-in (`sshd_harden: true`): no root login, no passwords/kbd-interactive,
  no X11, `MaxAuthTries 3`.
- `unattended-upgrades` on (Ubuntu default).
- Kiro Crew dashboard binds localhost only — the `kirocrew` role asserts it.

## Ansible notes (`host_vars/punjab.yml`)

- `skip_proxy: true` — no podman on stock Ubuntu, so no Caddy quadlet.
- Not a desktop: no GNOME/flatpak/browser roles.
- `syncthing` only runs if its brew binary exists (it currently doesn't).
