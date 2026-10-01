# TunaOS AWS Account

> **TunaOS infrastructure.** This AWS account belongs to the TunaOS project.
> It hosts the Hive agent fleet, Matrix/ESS and the CFP dashboard, plus punjab,
> the box they're administered from. James's personal fleet (desktops, goa,
> the home Talos cluster) lives elsewhere in this handbook.

One AWS account (credits-funded) hosts three unrelated things. Everything
created by hand has been adopted into **OpenTofu** in
[`aws/`](https://github.com/hanthor/dotfiles/tree/master/aws); the one exception
is `runs-on`, which is its own CloudFormation stack.

| Region | What | Managed by |
|---|---|---|
| `eu-north-1` | [AWS Talos cluster](../aws-k8s/cluster.md) — VPC, control plane `m6i.2xlarge` + worker `m6i.xlarge`, Elastic IPs, security groups, pgdata volume | `aws/cluster.tf` |
| `eu-north-1` | Backups — DLM snapshot policy, the fleet-backups bucket | `aws/backups.tf` |
| `us-east-1` | [punjab](../punjab/README.md) — `t3.large` agent box, default VPC | `aws/punjab.tf` |
| `us-east-2` | `runs-on` — self-hosted GitHub Actions runners ([runs-on.com](https://runs-on.com)) | CloudFormation stack `runs-on` |
| global | A scoped admin IAM user + policies, DLM role, a write-only backup user, punjab's SSM instance role | `aws/iam.tf`, `aws/backups.tf`, `aws/punjab.tf` |
| both | EBS encryption by default | `aws/account.tf` |
| global | Budgets (spend alarms) | `aws/budgets.tf` |

Default VPCs in each region are untouched and unmanaged.

## OpenTofu layout

```
aws/
├── versions.tf     # provider (eu-north-1 default, us_east_1 alias) + S3 backend
├── cluster.tf      # VPC/subnet/IGW/routes, 3 SGs, 2 Talos nodes, EIPs, pgdata
├── backups.tf      # DLM role + policy, fleet-backups bucket (+ versioning/SSE/lifecycle)
├── punjab.tf       # key pair, SG, instance, EIP, SSM role, DLM
├── account.tf      # EBS encryption by default (both regions)
├── iam.tf          # scoped admin user + its policies
├── budgets.tf      # 5 budgets, one for_each
├── imports.tf      # one-time adoption record (no-op once imported)
├── variables.tf
└── terraform.tfvars.example
```

- **State**: in the fleet-backups bucket under `tofu/aws/`
  (versioned, SSE-S3, lockfile). It contains the Talos nodes' `user_data` —
  i.e. cluster PKI — so it never goes in git.
- **Variables**: `aws/terraform.tfvars` holds the alert email and the admin
  ingress allowlists. The repo is public, so it is gitignored and stored in the
  Bitwarden secure note **`aws-tofu-tfvars`**.
- **Talos user_data is not in the config.** Every node ignores `user_data`
  and `ami`; node config is `talosctl`'s job. `prevent_destroy` is set on both
  nodes, punjab, the worker EIP (DNS points at it), the pgdata volume and
  the backup bucket.

## Usage

```bash
aws login                 # or the scoped admin user's keys; region is per-resource
just aws-plan             # fetches tfvars from Bitwarden if missing, then plan
just aws-apply            # interactive apply
just aws-seed-tfvars      # after editing aws/terraform.tfvars, push it back to BW
```

A plan against the live account should always read **"No changes"**. If it
doesn't, someone changed something in the console. Either codify the change
or revert it. Don't leave drift.

Common edits:

- **Admin IP changed**: edit the admin ingress allowlist variables in tfvars →
  `just aws-apply` → `just aws-seed-tfvars`. Prune stale entries; the list only
  ever grows otherwise.
- **Resize a node**: change `instance_type` in `cluster.tf`. EC2 stops the
  instance for the resize. The control plane must stay ≥ `m6i.2xlarge` (see the
  OOM incident in the cluster handbook).

## IAM & access

- **Root** has MFA and no access keys. Use `aws login` as root only for IAM
  changes, then let the session lapse rather than leaving root credentials
  cached on a shared box.
- **A scoped admin user** is the day-to-day identity. It has `ec2:*`, `s3:*`,
  budgets/CE, `iam:PassRole` to EC2, `dlm:*`, **read-only IAM** (so it can run
  `just aws-plan`) and SSM Session Manager. It **cannot change IAM**, so
  applies that touch IAM need root. Keys: Bitwarden `aws-james-admin`.
- **A write-only backup user**: put/get under `postgres/` in the backup bucket,
  **no delete**. Key in Bitwarden `postgres-backup-s3` and k8s Secret
  `postgres/postgres-backup-s3` — created out of band, never in tofu state.
- **punjab's instance role**: `AmazonSSMManagedInstanceCore` only.
- No CloudTrail trail, GuardDuty or Route 53 zones exist. DNS is on
  Cloudflare.

## Backups

- **EBS snapshots (DLM)**: every volume tagged
  `Backup=fleet-daily`, meaning both Talos root volumes. Daily at 03:30 UTC,
  keep 7. Weekly on Sunday at 03:45 UTC, keep 4. These are crash-consistent
  node images, so they cover node loss, including hive-data and synapse
  media, which have no other backup.
- **S3 fleet-backups bucket**: the nightly Postgres job uploads each
  verified dump to `postgres/<date>/` and checks the uploaded size (first
  upload 2026-09-24: synapse 2.9 GB, mas 852 KB). `postgres/` moves to IA at
  30 days, Glacier IR at 90, expires at 1 year.
- **punjab**: its own DLM policy in us-east-1 (DLM is regional), same schedule.

## Cost

Credits cover the bill. The budgets, all emailing the tfvars `alert_email`:

| Budget | Limit | Basis |
|---|---|---|
| `migration-monthly-spend` | $1400/mo | gross (before credits); alerts at $500/$800/$1400 + forecast |
| `bedrock-monthly-spend` | $200/mo | gross, Bedrock only |
| `kiro-monthly-spend` | $500/mo | gross, Kiro only |
| `tuna-os-account-total` | $120/mo | net; 50/80/90% |
| `credits-exhausted-alarm` | $5/mo | net; fires at $1, meaning credits ran out |

`runs-on-app-daily-budget` belongs to the runs-on stack.
