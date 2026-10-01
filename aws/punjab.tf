# punjab — headless agent/dev box, Ansible-managed like any other fleet host
# (inventory.yml, host_vars/punjab.yml). Stock Ubuntu 24.04, reached over
# Tailscale at 100.78.73.8. No public inbound by default: break-glass access is
# SSM Session Manager (`aws ssm start-session --target <id>`), which needs no
# open port. var.punjab_ssh_ingress can re-open 22 temporarily if SSM is down.

resource "aws_key_pair" "punjab" {
  provider   = aws.us_east_1
  key_name   = "punjab"
  public_key = "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQDiAhiG3nENI7eON08aLsMKH1xeBYNCtAjS3yQF4fvXszgDD13fmJ10lDjp6YMgqk+ytBUmGIuioEdxk2u8ulxM+PnkpQffbw6pJKmM4XIneJp0Htn5ioCLyZi15wMHBd0YrDo1BQ9l2Zm6sK3kmLfKObuJvHcoh9n5B6jd/P/fp+m8hX/LppDeNL2Wt7N5jcaucuTkYx0O0Lbr/ev7uq1e7UvgJ2eHLIOPtNGFVUkwvhH0OsmJsqxjpW7LlRikH+UynCD02SqB5xYpZl4Wm6NgPoBxonECkOLKUfDAbsfFg9kolctT++v8um2FSE5nlO4DSg6Yz8r6xed4urG9xRF1 punjab"

  lifecycle {
    # EC2 doesn't return public_key on import; without this tofu would
    # replace the key pair on every plan.
    ignore_changes = [public_key]
  }
}

# In the us-east-1 default VPC.
resource "aws_security_group" "punjab_ssh" {
  provider    = aws.us_east_1
  name        = "punjab-ssh"
  description = "SSH box punjab: SSH from admin IP only"

  # Attribute syntax (not dynamic blocks) so an empty list really means "no
  # inbound" — omitted ingress blocks would leave existing rules unmanaged.
  ingress = [for rule in var.punjab_ssh_ingress : {
    description      = rule.description
    from_port        = 22
    to_port          = 22
    protocol         = "tcp"
    cidr_blocks      = rule.cidrs
    ipv6_cidr_blocks = []
    prefix_list_ids  = []
    security_groups  = []
    self             = false
  }]

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Only what Session Manager needs. Anything running on punjab can read these
# creds from IMDS, so keep this role minimal — admin work uses real users.
resource "aws_iam_role" "punjab" {
  name = "punjab-ssm"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "punjab_ssm" {
  role       = aws_iam_role.punjab.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "punjab" {
  name = "punjab-ssm"
  role = aws_iam_role.punjab.name
}

resource "aws_instance" "punjab" {
  provider               = aws.us_east_1
  ami                    = "ami-0045d7fc2ad003464" # ubuntu-noble-24.04-amd64-server-20260923
  instance_type          = "t3.large"
  subnet_id              = "subnet-0598105df43192616" # default VPC, us-east-1d
  key_name               = aws_key_pair.punjab.key_name
  vpc_security_group_ids = [aws_security_group.punjab_ssh.id]
  iam_instance_profile   = aws_iam_instance_profile.punjab.name

  disable_api_termination = true

  credit_specification {
    cpu_credits = "unlimited"
  }

  metadata_options {
    http_tokens = "required"
    # 1 = only the host itself can reach IMDS (no containers hopping to the
    # instance role's creds).
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 250
    tags = {
      Backup = "fleet-daily" # aws_dlm_lifecycle_policy.punjab
    }
  }

  tags = {
    Name = "punjab"
  }

  lifecycle {
    prevent_destroy = true
    # The box is configured by Ansible, not by re-imaging.
    ignore_changes = [ami, user_data, user_data_base64]
  }
}

# Stable public IP: it's allowlisted on the Talos cluster's admin SG so punjab
# can run talosctl/kubectl against it (an ephemeral IP would change on every
# stop/start).
resource "aws_eip" "punjab" {
  provider = aws.us_east_1
  domain   = "vpc"
  instance = aws_instance.punjab.id
  tags = {
    Name = "punjab"
  }
}

# DLM is regional, so punjab (us-east-1) needs its own policy. Same schedule
# as the cluster's: daily ×7, weekly ×4.
resource "aws_dlm_lifecycle_policy" "punjab" {
  provider           = aws.us_east_1
  description        = "punjab root volume daily and weekly snapshots"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]
    target_tags = {
      Backup = "fleet-daily"
    }

    schedule {
      name        = "daily-7d"
      copy_tags   = true
      tags_to_add = { dlm-schedule = "daily-7d" }
      create_rule {
        cron_expression = "cron(30 3 * * ? *)"
      }
      retain_rule {
        count = 7
      }
    }

    schedule {
      name        = "weekly-4w"
      copy_tags   = true
      tags_to_add = { dlm-schedule = "weekly-4w" }
      create_rule {
        cron_expression = "cron(45 3 ? * SUN *)"
      }
      retain_rule {
        count = 4
      }
    }
  }
}
