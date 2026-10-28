# Punjab

> **TunaOS infrastructure.** This runs in the TunaOS AWS account and serves
> the TunaOS project (Hive, Matrix, CI), not James's personal fleet. See
> [TunaOS AWS Account & IaC](../aws/README.md).

Headless agent/dev box — the fleet's AWS-hosted Ansible host. It runs in the
same AWS account as the former [AWS Talos cluster](../aws-k8s/cluster.md),
but is an ordinary fleet member, not a cluster node. The Talos cluster was
terminated; Matrix and the Hives now run on the [OCI VPS](../spindle-vps/README.md).

## Migration status

The Karnataka `corral-vms/punjab` VM is a staging guest, not the EC2 host.
Its host key was verified against its console. The separate Tailscale device
`punjab-migration` is online at `100.103.187.46`; direct SSH was verified
against that same host key. The initial home copy completed on 2026-10-28 into
root-restricted `/srv/punjab-migration/` on the guest; it is not activated as
its home, service state or Tailscale identity. The source remains running, so
the copy needs final synchronization and validation before cutover.
A metadata-based dry run after the initial copy found 577 regular files to
transfer (about 996 MB) and 485 new filesystem entries. The follow-up sync
completed successfully. The comparison did not checksum all contents or
check for deletions, and the live source can still change.

The guest resolved and reached `api.github.com` over HTTPS and connected to
the Spindle broker's TCP port. These checks do not prove broker authentication.

The staged Kiro Crew 0.10.0 executable and dashboard were exercised in an
isolated network namespace with a disposable home overlay, cron and tunnels
disabled. The gateway reported ready and its loopback dashboard returned HTTP
200. This is not a test of live credentials, background jobs or migration of
the running source service.

EC2 snapshot `snap-0bc709516bb003e9a` was created on 2026-10-28 while Punjab
was live; it is crash-consistent, not a verified application-consistent restore.
Do not stop the source until transfers, final synchronization, recovery and
service checks are complete. Existing tmux processes cannot move live.
S3 contains older backups with no offsite copy and remains retained.

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
- **AWS CLI**: the scoped admin user can inspect EC2, S3 and costs, but was
  denied CloudFormation, ECS, Secrets Manager, API Gateway and SQS inventory.
  An authorized administrator session is needed to audit those resources.

## Host hardening

- sshd drop-in (`sshd_harden: true`): no root login, no passwords/kbd-interactive,
  no X11, `MaxAuthTries 3`.
- `unattended-upgrades` on (Ubuntu default).
- Kiro Crew dashboard binds localhost only — the `kirocrew` role asserts it.

## Ansible notes (`host_vars/punjab.yml`)

- `skip_proxy: true` — no podman on stock Ubuntu, so no Caddy quadlet.
- Not a desktop: no GNOME/flatpak/browser roles.
- `syncthing` only runs if its brew binary exists (it currently doesn't).
