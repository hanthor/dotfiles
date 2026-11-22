# aws/ — AWS account IaC (OpenTofu)

Codifies the TunaOS AWS account except the `runs-on` CloudFormation stack:
punjab (retired EC2 instance, data preserved), backups, IAM, budgets and the
read-only drift role. The terminated eu-north-1 Talos cluster is forgotten via
`removed.tf`; anything of it still live is unmanaged.

```bash
just aws-plan    # review every action; credits are exhausted
just aws-apply   # never blindly
```

Full handbook: [docs/src/servers/aws/README.md](../docs/src/servers/aws/README.md).
State is in S3 and `terraform.tfvars` is in Bitwarden (`aws-tofu-tfvars`).
Neither is in git.
