# AWS Talos cluster (eu-north-1). Handbook:
# docs/src/servers/aws-k8s/cluster.md
#
# Nodes are configured by talosctl, not here: their user_data is the Talos
# machine config (cluster PKI) and is deliberately NOT in this repo —
# ignore_changes keeps tofu from ever diffing or rewriting it.

# ── Network ───────────────────────────────────────────────────────────
resource "aws_vpc" "migration" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags = {
    Name = "migration-vpc"
  }
}

resource "aws_internet_gateway" "migration" {
  vpc_id = aws_vpc.migration.id
  tags = {
    Name = "migration-igw"
  }
}

# Single AZ, public only — no NAT gateway (unneeded, ~$32/mo).
resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.migration.id
  cidr_block              = "10.20.1.0/24"
  availability_zone       = "eu-north-1a"
  map_public_ip_on_launch = true
  tags = {
    Name = "migration-public-a"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.migration.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.migration.id
  }

  tags = {
    Name = "migration-public-rt"
  }
}

resource "aws_route_table_association" "public_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

# ── Security groups ───────────────────────────────────────────────────
resource "aws_security_group" "intracluster" {
  name        = "migration-intracluster"
  description = "Intra-cluster Talos/k8s traffic"
  vpc_id      = aws_vpc.migration.id

  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# 80/443 → Traefik hostPorts; 8448 federation; 30001/30002 + 32700-32767 are
# the NodePorts the ESS chart's MatrixRTC SFU exposes.
resource "aws_security_group" "matrix_public" {
  name        = "migration-matrix-public"
  description = "Public Matrix federation/web ports"
  vpc_id      = aws_vpc.migration.id

  dynamic "ingress" {
    for_each = [
      { port = 80, to = 80, proto = "tcp", desc = "" },
      { port = 443, to = 443, proto = "tcp", desc = "" },
      { port = 8448, to = 8448, proto = "tcp", desc = "" },
      { port = 30001, to = 30001, proto = "tcp", desc = "matrix-rtc-sfu-tcp" },
      { port = 30002, to = 30002, proto = "udp", desc = "matrix-rtc-sfu-udp" },
      { port = 32700, to = 32767, proto = "udp", desc = "matrix-rtc-sfu-udp-range" },
    ]
    content {
      description = ingress.value.desc
      from_port   = ingress.value.port
      to_port     = ingress.value.to
      protocol    = ingress.value.proto
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Talos API + k8s API from admin IPs only (see var.cluster_admin_ingress).
# Only the control-plane carries this group.
resource "aws_security_group" "admin_bootstrap" {
  name        = "migration-admin-bootstrap"
  description = "Temporary admin access for Talos/k8s API during bootstrap - restricted to admin IP"
  vpc_id      = aws_vpc.migration.id

  dynamic "ingress" {
    for_each = flatten([
      for rule in var.cluster_admin_ingress : [
        for port in [6443, 50000] : merge(rule, { port = port })
      ]
    ])
    content {
      description = ingress.value.description
      from_port   = ingress.value.port
      to_port     = ingress.value.port
      protocol    = "tcp"
      cidr_blocks = ingress.value.cidrs
    }
  }

  dynamic "ingress" {
    for_each = length(var.cluster_admin_pmtu_cidrs) > 0 ? [1] : []
    content {
      from_port   = 3
      to_port     = 4
      protocol    = "icmp"
      cidr_blocks = var.cluster_admin_pmtu_cidrs
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ── Nodes ─────────────────────────────────────────────────────────────
locals {
  talos_ami = "ami-082ff045afa7ed0b3" # Talos Image Factory AMI the nodes were built from
}

# Control plane also runs hive (its PVC is node-bound local-path), so it must
# stay m6i.xlarge — see the 2026-08-27 OOM incident in the handbook.
resource "aws_instance" "controlplane" {
  ami           = local.talos_ami
  instance_type = "m6i.xlarge"
  subnet_id     = aws_subnet.public_a.id
  private_ip    = "10.20.1.10"
  vpc_security_group_ids = [
    aws_security_group.intracluster.id,
    aws_security_group.admin_bootstrap.id,
    aws_security_group.matrix_public.id,
  ]

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 100
    tags = {
      Backup = "fleet-daily" # picked up by aws_dlm_lifecycle_policy.fleet_daily
    }
  }

  tags = {
    Name = "aws-migration-controlplane-hive"
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [ami, user_data, user_data_base64, user_data_replace_on_change]
  }
}

resource "aws_instance" "worker" {
  ami           = local.talos_ami
  instance_type = "m6i.xlarge"
  subnet_id     = aws_subnet.public_a.id
  private_ip    = "10.20.1.11"
  vpc_security_group_ids = [
    aws_security_group.intracluster.id,
    aws_security_group.matrix_public.id,
  ]

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 100
    tags = {
      Backup = "fleet-daily"
    }
  }

  tags = {
    Name = "aws-migration-worker-matrix"
  }

  lifecycle {
    prevent_destroy = true
    # pgdata is attached via aws_volume_attachment, not inline.
    ignore_changes = [ami, user_data, user_data_base64, user_data_replace_on_change, ebs_block_device]
  }
}

resource "aws_eip" "controlplane" {
  domain   = "vpc"
  instance = aws_instance.controlplane.id
  tags = {
    Name = "migration-controlplane"
  }
}

# DNS for matrix/auth/call/hive points here — changing it is an outage.
resource "aws_eip" "worker" {
  domain   = "vpc"
  instance = aws_instance.worker.id
  tags = {
    Name = "migration-worker-matrix"
  }
  lifecycle {
    prevent_destroy = true
  }
}

# Attached at the EC2 level but NOT yet mounted by Talos — Postgres still
# runs on local-path on the root volume. Unfinished work; see handbook.
resource "aws_ebs_volume" "pgdata" {
  availability_zone = "eu-north-1a"
  type              = "gp3"
  size              = 50
  tags = {
    Name = "migration-pgdata"
  }
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_volume_attachment" "pgdata" {
  device_name = "/dev/xvdb"
  volume_id   = aws_ebs_volume.pgdata.id
  instance_id = aws_instance.worker.id
}
