# ── KubeVirt node ─────────────────────────────────────────────────────
# A third Talos worker that only runs KubeVirt VMs (corral's AWS backend).
#
# Why m7i: KubeVirt needs /dev/kvm. EC2 exposes it on virtual instances only
# with nested virtualization, which the m6i nodes don't support (checked
# 2026-09-24: `aws ec2 describe-instance-types` lists `nested-virtualization`
# for m7i.2xlarge in eu-north-1, nothing for m6i.xlarge).
#
# Cost: on-demand $0.4284/h in eu-north-1, so ~$313/mo if it never stopped.
# It is stopped when idle (talos-k8s/kubevirt-aws/idle-stop.yaml) and started
# on demand (scripts/kubevirt-node up). The migration budget's action below
# stops it automatically if gross spend nears the $1400/mo credits.
#
# Joining: no user_data, so Talos boots into maintenance mode and no cluster
# secrets ever reach OpenTofu state; the machine config is applied from
# punjab with `talosctl apply-config --insecure` (admin_bootstrap allows
# punjab on :50000). See docs/src/servers/aws-k8s/kubevirt.md.
resource "aws_instance" "kubevirt" {
  ami           = local.talos_ami
  instance_type = "m7i.2xlarge"
  subnet_id     = aws_subnet.public_a.id
  private_ip    = "10.20.1.12"
  vpc_security_group_ids = [
    aws_security_group.intracluster.id,
    aws_security_group.admin_bootstrap.id,
  ]

  cpu_options {
    nested_virtualization = "enabled"
  }

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    # Talos system + VM disks (local-path). No Backup tag: VM disks are
    # scratch; anything worth keeping lives in a VM snapshot or elsewhere.
    volume_type = "gp3"
    volume_size = 150
  }

  tags = {
    Name = "aws-migration-kubevirt"
    Role = "kubevirt"
    # Opt-in for corral's aws-power plugin (the corral-web power button);
    # the value is the name corral shows.
    "corral:host-power" = "KubeVirt (AWS)"
    "corral:node"       = "ip-10-20-1-12"
  }

  lifecycle {
    ignore_changes = [ami, user_data, user_data_base64]
  }
}

# ── Spend kill switch ─────────────────────────────────────────────────
# If gross spend this month passes $1100 (79% of the $1400/mo credits),
# AWS Budgets stops the KubeVirt node by itself. No human in the loop:
# the one resource that can double the bill turns itself off first.
# Billing data lags ~a day, so the worst-case overshoot is about a day of
# node time (~$10).
resource "aws_iam_role" "budget_action" {
  name = "budget-action-stop-kubevirt"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "budgets.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "budget_action" {
  name = "stop-kubevirt-node"
  role = aws_iam_role.budget_action.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ec2:StopInstances"]
        Resource = aws_instance.kubevirt.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:DescribeInstances", "ec2:DescribeInstanceStatus", "ssm:StartAutomationExecution", "ssm:GetAutomationExecution"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_budgets_budget_action" "stop_kubevirt" {
  budget_name        = aws_budgets_budget.this["migration"].name
  action_type        = "RUN_SSM_DOCUMENTS"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_action.arn

  action_threshold {
    action_threshold_type  = "ABSOLUTE_VALUE"
    action_threshold_value = 1100
  }

  definition {
    ssm_action_definition {
      action_sub_type = "STOP_EC2_INSTANCES"
      region          = "eu-north-1"
      instance_ids    = [aws_instance.kubevirt.id]
    }
  }

  subscriber {
    address           = var.alert_email
    subscription_type = "EMAIL"
  }
}

# ── Idle stop / on-demand start ───────────────────────────────────────
# Credentials for the in-cluster idle-stop CronJob and for starting the node
# from the tailnet. Scoped to this one instance: start, stop, describe.
# The access key is created by hand (never in state or git) and stored in
# the cluster as secret kubevirt-aws/node-power (idle-stop CronJob) and
# tailvm/node-power (corral-web's aws-power plugin).
resource "aws_iam_user" "kubevirt_power" {
  name = "kubevirt-node-power"
}

resource "aws_iam_user_policy" "kubevirt_power" {
  name = "start-stop-kubevirt-node"
  user = aws_iam_user.kubevirt_power.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ec2:StartInstances", "ec2:StopInstances"]
        Resource = aws_instance.kubevirt.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ec2:DescribeInstances"]
        Resource = "*"
      },
    ]
  })
}

output "kubevirt_instance_id" {
  value = aws_instance.kubevirt.id
}

output "kubevirt_public_ip" {
  description = "Only used to apply the Talos config from punjab; day-to-day access is over the tailnet."
  value       = aws_instance.kubevirt.public_ip
}
