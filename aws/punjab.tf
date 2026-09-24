# punjab — headless agent/dev box, Ansible-managed like any other fleet host
# (inventory.yml, host_vars/punjab.yml). Stock Ubuntu 24.04, reached over
# Tailscale at 100.78.73.8; the public SSH rule is a break-glass path only.

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

  dynamic "ingress" {
    for_each = var.punjab_ssh_ingress
    content {
      description = ingress.value.description
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = ingress.value.cidrs
    }
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "punjab" {
  provider               = aws.us_east_1
  ami                    = "ami-0045d7fc2ad003464" # ubuntu-noble-24.04-amd64-server-20260923
  instance_type          = "t3.large"
  subnet_id              = "subnet-0598105df43192616" # default VPC, us-east-1d
  key_name               = aws_key_pair.punjab.key_name
  vpc_security_group_ids = [aws_security_group.punjab_ssh.id]

  credit_specification {
    cpu_credits = "unlimited"
  }

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 250
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
