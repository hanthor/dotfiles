# AWS Account

One AWS account (credits-funded) hosts three unrelated things. Everything
created by hand has been adopted into **OpenTofu** in
[`aws/`](https://github.com/hanthor/dotfiles/tree/master/aws); the one exception
is `runs-on`, which is its own CloudFormation stack.

| Region | What | Managed by |
|---|---|---|
| `eu-north-1` | [AWS Talos cluster](../aws-k8s/cluster.md) — VPC, 2 × `m6i.xlarge` nodes, EIPs, SGs, pgdata volume | `aws/cluster.tf` |
| `eu-north-1` | Backups — DLM snapshot policy, `hanthor-fleet-backups-*` bucket | `aws/backups.tf` |
| `us-east-1` | [punjab](../punjab/README.md) — `t3.large` agent box, default VPC | `aws/punjab.tf` |
| `us-east-2` | `runs-on` — self-hosted GitHub Actions runners ([runs-on.com](https://runs-on.com)) | CloudFormation stack `runs-on` |
| global | IAM user `james-admin` + policies, DLM role | `aws/iam.tf`, `aws/backups.tf` |
| global | Budgets (spend alarms) | `aws/budgets.tf` |

Default VPCs in each region are untouched and unmanaged.

## OpenTofu layout

```
aws/
├── versions.tf     # provider (eu-north-1 default, us_east_1 alias) + S3 backend
├── cluster.tf      # VPC/subnet/IGW/routes, 3 SGs, 2 Talos nodes, EIPs, pgdata
├── backups.tf      # DLM role + policy, fleet-backups bucket (+ versioning/SSE/lifecycle)
├── punjab.tf       # key pair, SG, instance
├── iam.tf          # james-admin + its policies
├── budgets.tf      # 5 budgets, one for_each
├── imports.tf      # one-time adoption record (no-op once imported)
├── variables.tf
└── terraform.tfvars.example
```

- **State**: `s3://hanthor-fleet-backups-<account>/tofu/aws/terraform.tfstate`
  (versioned, SSE-S3, lockfile). It contains the Talos nodes' `user_data` —
  i.e. cluster PKI — so it never goes in git.
- **Variables**: `aws/terraform.tfvars` holds the alert email and the admin
  IP allowlists. The repo is public, so it is gitignored and stored in the
  Bitwarden secure note **`aws-tofu-tfvars`**.
- **Talos user_data is not in the config.** Every node ignores `user_data`
  and `ami`; node config is `talosctl`'s job. `prevent_destroy` is set on both
  nodes, punjab, the worker EIP (DNS points at it), the pgdata volume and
  the backup bucket.

## Usage

```bash
aws login                 # or james-admin keys; region is per-resource
just aws-plan             # fetches tfvars from Bitwarden if missing, then plan
just aws-apply            # interactive apply
just aws-seed-tfvars      # after editing aws/terraform.tfvars, push it back to BW
```

A plan against the live account should always read **"No changes"**. If it
doesn't, someone changed something in the console. Either codify the change
or revert it. Don't leave drift.

Common edits:

- **Admin IP changed** (Talos/k8s API or punjab SSH): edit
  `cluster_admin_ingress` / `punjab_ssh_ingress` in tfvars → `just aws-apply` →
  `just aws-seed-tfvars`. Prune stale entries; the list only ever grows otherwise.
- **Resize a node**: change `instance_type` in `cluster.tf`. EC2 stops the
  instance for the resize. The control plane must stay ≥ `m6i.xlarge` (see the
  OOM incident in the cluster handbook).

## IAM & access

- **Root** is what `aws login` on punjab currently uses. Root has MFA enabled
  and no access keys. Use it for account-level work only.
- **`james-admin`** is the scoped day-to-day user. It has `ec2:*`, `s3:*`,
  budgets/CE, `iam:PassRole` to EC2 and `dlm:*` + `PassRole` for the DLM role.
  It **cannot manage IAM itself**, so `aws/iam.tf` changes need root.
- No CloudTrail trail, GuardDuty or Route 53 zones exist. DNS is on
  Cloudflare.

## Backups

- **EBS snapshots (DLM `policy-0f074c7d13f94e355`)**: every volume tagged
  `Backup=fleet-daily`, meaning both Talos root volumes. Daily at 03:30 UTC,
  keep 7. Weekly on Sunday at 03:45 UTC, keep 4. These are crash-consistent
  node images, so they cover node loss, including hive-data and synapse
  media, which have no other backup.
- **S3 `hanthor-fleet-backups-*`**: `postgres/` moves to IA at 30 days and
  Glacier IR at 90 days, and expires at 1 year. The bucket is **currently
  empty**. The in-cluster Postgres dump job still writes to a local PVC and
  doesn't upload yet.
- punjab's volume is not in the snapshot policy. Tag its root volume
  `Backup=fleet-daily` in `punjab.tf` if you want it covered.

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
