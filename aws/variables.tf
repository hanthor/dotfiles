# Real values live in terraform.tfvars (gitignored — the repo is public).
# Copy terraform.tfvars.example and fill it in, or pull the Bitwarden note
# `aws-tofu-tfvars` (see README.md).

variable "alert_email" {
  description = "Address that receives AWS Budgets notifications."
  type        = string
}

variable "punjab_ssh_ingress" {
  description = "Source CIDRs allowed to SSH to punjab's public IP, grouped by description. Day-to-day access is over Tailscale."
  type = list(object({
    description = string
    cidrs       = list(string)
  }))
}
