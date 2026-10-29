# TunaOS AWS Account — Retired

**Retired workload and recovery-storage resources were deleted on 2026-10-29 with the owner's explicit approval.** Punjab runs on Karnataka; Matrix, LiveKit and the Hives run on the OCI Spindle VPS. Do not recreate the former AWS deployment.

## Verified final inventory

Authenticated verification covered all **17 enabled regions**. All 102 checks for nonterminated EC2 instances, EBS volumes, owned snapshots, Elastic IP allocations, nondefault VPCs and DLM policies returned empty.

| Retired resource | Final state |
|---|---|
| Punjab EC2 `i-085690e02ca98c95a`, `us-east-1` | Terminated |
| Root volume `vol-09fdb248c28e850ca`, 250 GiB gp3 | Absent after termination |
| Five Punjab recovery snapshots | Deleted |
| `hanthor-fleet-backups-181185361136` | Deleted, including 212 versions and 22 delete markers |
| `runs-on-s3bucketcache-qygxr14wsudh` | Deleted, including 71 versions and 26 delete markers |
| `runs-on-s3bucketlogging-dqtjtzk02gph` | Deleted, including 1,147 versions and 365 delete markers |
| Stockholm migration VPC, subnet, route table, IGW and custom security groups | Deleted |
| Punjab SSH security group | Deleted |
| Both DLM policies and five account budgets | Deleted; each original budget name returns `NotFoundException` |
| Three fleet IAM users, their credentials, three custom roles/instance profiles and custom admin policy | Deleted |

The earlier `runs-on` CloudFormation stack had already reached `DELETE_COMPLETE`. Earlier regional inventories also found no remaining ECS/EKS clusters, Lambda functions, RDS databases, load balancers, NAT gateways, Auto Scaling groups, Spot requests or fleets. CloudWatch logs/alarms/dashboards, EFS, AWS Backup, SSM parameters and scheduled EventBridge rules were empty. There were no customer-managed KMS keys.

The AWS account remains open. Default account networks, AWS-managed KMS keys, service-linked roles and Identity Center metadata were not removed; they are not the retired workload or backup storage. This is not an account-closure claim.

## Backup deletion decision

The owner confirmed the Hives and Spindle were already migrated and that the historical AWS backups were unnecessary. The proposed 182 GB fleet-bucket archive was canceled. Newly created transfer/staging directories on Punjab and Karnataka were removed; **no completed archive of those S3 objects is claimed**.

All three buckets were emptied of every object version and delete marker before deletion. This includes historical Postgres dumps, Hive/media/rollback exports, encrypted cluster-state archives and OpenTofu state containing Talos PKI. Do not describe those cloud copies as retained or recoverable.

Existing off-AWS migration data, previously existing local backups, Bitwarden recovery notes, Atuin archives and the live Spindle/Punjab data were not deleted. Their retention does not establish a complete replacement for the deleted S3 history or EBS snapshots.

Private action logs and the final API-verification receipt are on Punjab at:

```text
~/backups/aws-final-retirement-20261029T015927Z/deletion-actions.jsonl
~/backups/aws-final-retirement-20261029T015927Z/completion.json
```

These are deletion/audit metadata, not application-data archives. The older root-only `/srv/punjab-migration/aws-cutover-receipt.json` records the October 28 stop/EIP release; it is historical evidence, not the final inventory.

## Active replacements

- [Karnataka K3s](../talos-k8s/karnataka/README.md): `https://100.66.158.127:6443`, context `karnataka-k3s`.
- [Punjab VM](../punjab/README.md): `ubuntu@100.103.187.46`, KubeVirt `corral-vms/punjab`.
- [Spindle VPS](../spindle-vps/README.md): OCI-hosted services, not AWS.

After AWS deletion, Karnataka was `Ready` and the Punjab VMI was `Running`. A fresh omp request explicitly using Anthropic had already passed on the migrated VM, independently of AWS/Kiro. The K3s fleet rollout and its unreachable-client limits are recorded in the Karnataka handbook.

## Deployment retirement

The tracked AWS OpenTofu root module, variable/plan/apply recipes, legacy AWS KubeVirt startup helper, provider-update rule and AWS-only CI job were removed. Historical source is available at [commit `dcbbfbc`](https://github.com/hanthor/dotfiles/tree/dcbbfbc/aws). Restoring that source can recreate paid infrastructure; do not treat it as the desired current state.

Untracked private files such as `aws/terraform.tfvars`, cached state/plans and provider caches were not swept or published. Historical Kubernetes manifests remain recovery reference, not instructions to apply to Karnataka. General AWS CLI tools remain available for billing administration.

## Remaining billing

Kiro's live subscription API reported both Enterprise Power and Pro Plus as `CANCELLED`, expiring **2026-10-31 23:59:59.999 UTC**. Their end-of-period cancellation was requested on October 25. Existing October charges can continue through that period; [Kiro's cancellation documentation](https://kiro.dev/docs/enterprise/subscription-management/) explains the timing and separate SSO-assignment cleanup.

Final, prorated, request, transfer or minimum-storage-duration charges can arrive after resource deletion, and Cost Explorer is delayed. No zero-dollar final-invoice claim is made. The deleted compute, volumes, snapshots and buckets are no longer retained resources to accrue ongoing storage/compute charges.
