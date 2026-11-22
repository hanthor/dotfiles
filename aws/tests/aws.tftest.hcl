# Plan-only against a mocked AWS provider — never touches the real account.
# Run via tests/run.sh (see there for why not plain `tofu test`). Every
# variable is set here so the gitignored terraform.tfvars is irrelevant.

# Mock values the provider validates at plan time (random strings fail).
mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/mock" }
  }
  mock_resource "aws_eip" {
    defaults = { public_ip = "192.0.2.10" }
  }
}

mock_provider "aws" {
  alias = "us_east_1"

  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_resource "aws_iam_policy" {
    defaults = { arn = "arn:aws:iam::123456789012:policy/mock" }
  }
  mock_resource "aws_eip" {
    defaults = { public_ip = "192.0.2.10" }
  }
}

variables {
  alert_email = "alerts@example.com"
  punjab_ssh_ingress = [
    { description = "admin", cidrs = ["198.51.100.1/32"] },
    { description = "backup", cidrs = ["203.0.113.9/32"] },
  ]
}

run "punjab_ssh_mirrors_variable" {
  command = plan

  assert {
    condition     = length(aws_security_group.punjab_ssh.ingress) == length(var.punjab_ssh_ingress)
    error_message = "one ssh rule per punjab_ssh_ingress entry"
  }

  assert {
    condition = alltrue([
      for e in var.punjab_ssh_ingress : length([
        for r in aws_security_group.punjab_ssh.ingress : r
        if r.description == e.description && toset(r.cidr_blocks) == toset(e.cidrs)
        && r.from_port == 22 && r.to_port == 22 && r.protocol == "tcp"
      ]) == 1
    ])
    error_message = "punjab ssh rules must mirror punjab_ssh_ingress on tcp/22"
  }
}

run "punjab_ssh_closed_when_empty" {
  command = plan

  variables {
    punjab_ssh_ingress = []
  }

  assert {
    condition     = length(aws_security_group.punjab_ssh.ingress) == 0
    error_message = "no punjab_ssh_ingress entries must mean no public ssh"
  }
}

run "budgets" {
  command = plan

  assert {
    condition = toset(keys(aws_budgets_budget.this)) == toset([
      "account_total", "bedrock", "credits_exhausted", "kiro", "migration",
    ])
    error_message = "expected exactly the 5 managed budgets"
  }

  assert {
    condition = {
      for k, b in aws_budgets_budget.this : k => length(b.notification)
      } == {
      migration         = 4
      bedrock           = 3
      kiro              = 3
      credits_exhausted = 1
      account_total     = 3
    }
    error_message = "notification counts (actual + forecasted) drifted"
  }

  assert {
    condition = alltrue(flatten([
      for b in aws_budgets_budget.this : [
        for n in b.notification : n.subscriber_email_addresses == toset(["alerts@example.com"])
      ]
    ]))
    error_message = "every notification must go to alert_email"
  }

  assert {
    condition = alltrue([
      for n in aws_budgets_budget.this["account_total"].notification : n.threshold_type == "PERCENTAGE"
    ])
    error_message = "account_total thresholds are percentages"
  }

  assert {
    condition     = length(aws_budgets_budget.this["bedrock"].cost_filter) == 1 && length(aws_budgets_budget.this["migration"].cost_filter) == 0
    error_message = "service budgets filter by Service; account-wide ones don't"
  }

  assert {
    condition     = length(aws_budgets_budget.this["kiro"].cost_types) == 1 && length(aws_budgets_budget.this["credits_exhausted"].cost_types) == 0
    error_message = "gross budgets exclude credits; net budgets use the default cost_types"
  }
}

# punjab is internet-facing; these are the guardrails from securing it.
run "punjab_hardening" {
  command = plan

  assert {
    condition     = aws_instance.punjab.metadata_options[0].http_tokens == "required" && aws_instance.punjab.metadata_options[0].http_put_response_hop_limit == 1
    error_message = "punjab must require IMDSv2 with hop limit 1"
  }

  assert {
    condition     = aws_instance.punjab.disable_api_termination == true
    error_message = "punjab must have termination protection"
  }

  assert {
    condition     = aws_instance.punjab.iam_instance_profile == aws_iam_instance_profile.punjab.name
    error_message = "punjab needs the SSM instance profile (break-glass path)"
  }

  assert {
    condition     = aws_instance.punjab.root_block_device[0].tags["Backup"] == "fleet-daily"
    error_message = "punjab's root volume must be in the snapshot policy"
  }

  assert {
    condition     = aws_ebs_encryption_by_default.us_east_1.enabled && aws_ebs_encryption_by_default.eu_north_1.enabled
    error_message = "EBS encryption by default must stay on in both regions"
  }
}

# The backup writer must never gain delete (it's what makes a leaked key harmless).
run "postgres_backup_writer_is_write_only" {
  command = plan

  assert {
    condition     = !strcontains(aws_iam_user_policy.postgres_backup.policy, "Delete")
    error_message = "postgres-backup-writer must not be able to delete objects"
  }
}

# Nothing in the backup bucket may expire until an explicit cleanup decision.
run "backups_never_expire" {
  command = plan

  assert {
    condition = alltrue([
      for r in aws_s3_bucket_lifecycle_configuration.fleet_backups.rule :
      length(r.expiration) == 0 && length(r.noncurrent_version_expiration) == 0
    ])
    error_message = "fleet-backups lifecycle rules must not expire objects or noncurrent versions"
  }
}

# The drift role is assumable only from master of this repo, and read-only.
run "drift_role_is_scoped" {
  command = plan

  assert {
    condition     = strcontains(aws_iam_role.tofu_drift.assume_role_policy, "\"repo:hanthor/dotfiles:ref:refs/heads/master\"") && !strcontains(aws_iam_role.tofu_drift.assume_role_policy, "*")
    error_message = "drift role trust must be pinned to hanthor/dotfiles master with no wildcards"
  }

  assert {
    condition     = aws_iam_role_policy_attachment.tofu_drift_readonly.policy_arn == "arn:aws:iam::aws:policy/ReadOnlyAccess"
    error_message = "drift role must only carry ReadOnlyAccess"
  }
}
