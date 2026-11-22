# The AWS Talos cluster (eu-north-1) was terminated on 2026-10-25. These
# blocks make OpenTofu drop its resources from state WITHOUT destroying or
# recreating anything in the account. Whatever is still live there (EIPs, the
# pgdata volume, security groups, the VPC, IAM users/roles) becomes unmanaged
# and must be checked and cleaned up by hand — see
# docs/src/servers/aws/README.md ("Forgotten cluster resources").
#
# Once an apply has recorded the forget, these blocks are no-ops; keep them
# until every state copy has been applied.
#
# punjab's retired EC2 instance (punjab.tf) is deliberately NOT here: its data
# must be preserved until an explicit cleanup decision.

# ── Nodes (cluster.tf, kubevirt.tf) ───────────────────────────────────
removed {
  from = aws_instance.controlplane
  lifecycle { destroy = false }
}
removed {
  from = aws_instance.worker
  lifecycle { destroy = false }
}
removed {
  from = aws_instance.kubevirt
  lifecycle { destroy = false }
}
removed {
  from = aws_eip.controlplane
  lifecycle { destroy = false }
}
removed {
  from = aws_eip.worker
  lifecycle { destroy = false }
}
removed {
  from = aws_ebs_volume.pgdata
  lifecycle { destroy = false }
}
removed {
  from = aws_volume_attachment.pgdata
  lifecycle { destroy = false }
}

# ── Network (cluster.tf) ──────────────────────────────────────────────
removed {
  from = aws_vpc.migration
  lifecycle { destroy = false }
}
removed {
  from = aws_internet_gateway.migration
  lifecycle { destroy = false }
}
removed {
  from = aws_subnet.public_a
  lifecycle { destroy = false }
}
removed {
  from = aws_route_table.public
  lifecycle { destroy = false }
}
removed {
  from = aws_route_table_association.public_a
  lifecycle { destroy = false }
}
removed {
  from = aws_security_group.intracluster
  lifecycle { destroy = false }
}
removed {
  from = aws_security_group.matrix_public
  lifecycle { destroy = false }
}
removed {
  from = aws_security_group.admin_bootstrap
  lifecycle { destroy = false }
}

# ── KubeVirt node kill switch + power credentials (kubevirt.tf) ───────
# The kubevirt-node-power user's access key was created by hand; forgetting
# the user does not revoke it.
removed {
  from = aws_iam_role.budget_action
  lifecycle { destroy = false }
}
removed {
  from = aws_iam_role_policy.budget_action
  lifecycle { destroy = false }
}
removed {
  from = aws_budgets_budget_action.stop_kubevirt
  lifecycle { destroy = false }
}
removed {
  from = aws_iam_user.kubevirt_power
  lifecycle { destroy = false }
}
removed {
  from = aws_iam_user_policy.kubevirt_power
  lifecycle { destroy = false }
}
