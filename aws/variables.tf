# Real values live in terraform.tfvars (gitignored — the repo is public).
# Copy terraform.tfvars.example and fill it in, or pull the Bitwarden note
# `aws-tofu-tfvars` (see README.md).

variable "alert_email" {
  description = "Address that receives AWS Budgets notifications."
  type        = string
}

variable "cluster_admin_ingress" {
  description = <<-EOT
    Source CIDRs allowed to reach the Talos API (50000) and k8s API (6443) on
    the AWS cluster, grouped by rule description. This allowlist goes stale as
    home/travel IPs change — prune it rather than widening it.
  EOT
  type = list(object({
    description = string
    cidrs       = list(string)
  }))
}

variable "cluster_admin_pmtu_cidrs" {
  description = "CIDRs allowed ICMP type 3 code 4 (path-MTU discovery) to the cluster."
  type        = list(string)
  default     = []
}

variable "punjab_ssh_ingress" {
  description = "Source CIDRs allowed to SSH to punjab's public IP, grouped by description. Day-to-day access is over Tailscale."
  type = list(object({
    description = string
    cidrs       = list(string)
  }))
}
