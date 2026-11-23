# The monitoring stack plans the tool configuration (config/) as written, against
# mock providers: nothing is called. A run block cannot address resources inside
# a child module, so these assert what the stack hands the monitoring module
# (local.*), the module's outputs, and the tags; the module's own tests
# (terraform-aws-jaws-monitoring) cover what it builds from them.

mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "570327089884"
    }
  }

  mock_data "aws_region" {
    defaults = {
      region = "us-east-1"
    }
  }

  mock_data "aws_ec2_instance_type_offerings" {
    defaults = {
      locations = ["us-east-1a"]
    }
  }

  mock_data "aws_subnet" {
    defaults = {
      availability_zone = "us-east-1a"
    }
  }

  mock_data "aws_ami" {
    defaults = {
      id = "ami-0123456789abcdef0"
    }
  }

  mock_resource "aws_vpc" {
    defaults = {
      id = "vpc-0123456789abcdef0"
    }
  }

  mock_resource "aws_subnet" {
    defaults = {
      id = "subnet-0123456789abcdef0"
    }
  }

  mock_resource "aws_instance" {
    defaults = {
      id        = "i-0123456789abcdef0"
      public_ip = "198.51.100.7"
    }
  }

  mock_resource "aws_ebs_volume" {
    defaults = {
      id = "vol-0123456789abcdef0"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::570327089884:role/jaws-monitoring"
    }
  }
}

mock_provider "archive" {}

run "the_stack_reads_its_config" {
  command = plan

  assert {
    condition     = local.node.instance_type == "t9g.medium" && local.node.ami_name == "al2023-ami-2023.12.20261026.1-kernel-6.18-arm64"
    error_message = "the node's type and image are config/monitoring.yaml's monitoring.instance_type and monitoring.ami"
  }

  assert {
    condition     = local.node.domain == "grafana.jwall.engineering" && local.node.zone_id == "Z0644006DW6W2HALU9BI"
    error_message = "Grafana is served at monitoring.domain, in the dns zone of config/sites.yaml (dns.zone_id)"
  }

  assert {
    condition = local.node.grafana_admin == {
      user_parameter     = "/jaws/monitoring/grafana-admin-user"
      password_parameter = "/jaws/monitoring/grafana-admin-password"
    }
    error_message = "the Grafana admin is the owner's /jaws/monitoring/grafana-admin-* parameters (jaws monitoring secrets), never the stack's own /jaws-monitoring/ ones"
  }

  assert {
    condition = jsonencode(local.node.slack) == jsonencode({
      channels = { costs = "/jaws/monitoring/slack/costs", platform = "/jaws/monitoring/slack/platform" }
      routes   = { cost = "costs", host = "platform", pipeline = "platform" }
    })
    error_message = "the Slack channels and routes are monitoring.slack's"
  }

  assert {
    condition     = local.cost.bucket_name == "jaws-billing-570327089884"
    error_message = "the normalizer and the node read the foundation's billing bucket, monitoring.cost.bucket"
  }

  assert {
    condition     = local.cost.aws == { delivery_prefix = "raw/provider=aws/source=data-exports/jaws-focus-daily" }
    error_message = "the AWS source is where billing-export/'s jaws-focus-daily export delivers, under the bucket's aws_export_prefix"
  }

  assert {
    condition = jsonencode(local.cost.databricks.workspace_projects) == jsonencode({
      "braveheart-databricks-prod" = "braveheart-databricks"
      "jaws-shared"                = "jaws"
    })
    error_message = "Databricks usage without a Project tag takes its workspace's project: jaws-shared is the platform's (jaws), each <project>-prod workspace its project's"
  }

  assert {
    condition     = local.cost.runs == { prefixes = ["raw/provider=jaws/source=task-runs"], join_tags = ["RunId", "TaskId"] }
    error_message = "task-run records are read from where `task run` writes them (jaws.run_records) and joined on the RunId and TaskId tags"
  }

  assert {
    condition     = local.cost.budgets.total == 100 && local.cost.anomaly_floor_usd == 2 && local.cost.databricks_workspace_tag == "Workspace"
    error_message = "the budgets and the anomaly floor are monitoring.cost's, and a Databricks workspace's AWS rows are named by its Workspace tag"
  }

  assert {
    condition     = local.node.snapshots == { enabled = true }
    error_message = "monitoring.snapshots turns the data volume's daily snapshots on"
  }
}

run "the_node_is_named_for_the_platform" {
  command = plan

  assert {
    condition     = local.name == "jaws-monitoring"
    error_message = "the stack is <name_root>-monitoring: the CI policies of its roles are scoped to that name"
  }

  assert {
    condition     = output.node.parameter_prefix == "/jaws-monitoring/node" && output.node.config_bucket == "jaws-monitoring-config-570327089884"
    error_message = "the node's own parameters and config bucket are named for jaws-monitoring"
  }

  assert {
    condition     = output.normalizer.function_name == "jaws-monitoring-normalizer"
    error_message = "the normalizer is jaws-monitoring-normalizer"
  }

  # The monitoring/* and compute/* policies scope EC2 by aws:RequestTag/Project and
  # aws:ResourceTag/Project = monitoring, the roles' project: this tag is load-bearing.
  assert {
    condition = jsonencode(module.context.tags) == jsonencode({
      Organization = "Jaws-Platform"
      Project      = "monitoring"
      Environment  = "prod"
      Repository   = "Jaws-Platform/jaws"
      ManagedBy    = "JAWS"
      Owner        = "jwallace145"
    })
    error_message = "every resource is tagged Project = monitoring, with the platform's Organization, Environment, Repository, ManagedBy and Owner"
  }

  assert {
    condition     = output.vpc_id == "vpc-0123456789abcdef0" && jsonencode(local.availability_zones) == jsonencode(["us-east-1a"])
    error_message = "the node runs in the stack's own VPC, one public subnet in its pinned zone"
  }
}

run "the_stack_runs_on_its_schedule" {
  command = plan

  # Terraform's yamldecode reads a bare on: and off: key as YAML 1.1 booleans, the
  # keys "true" and "false"; the stack reads them either way.
  assert {
    condition = jsonencode(local.node.schedule) == jsonencode({
      days     = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
      off      = "24:00"
      on       = "08:00"
      timezone = "America/Denver"
    })
    error_message = "the node runs from 08:00 to midnight every day in America/Denver: monitoring.schedule"
  }
}

run "refuses_a_zone_that_does_not_offer_the_instance_type" {
  command = plan

  override_data {
    target = data.aws_ec2_instance_type_offerings.zone
    values = {
      locations = []
    }
  }

  expect_failures = [data.aws_ec2_instance_type_offerings.zone]
}

run "refuses_another_accounts_credentials" {
  command = plan

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "650503560686"
    }
  }

  expect_failures = [data.aws_caller_identity.current]
}

run "reads_its_configuration_from_the_repository_outside_the_image" {
  command = plan

  assert {
    condition     = !local.in_image && local.config_path == "./../config"
    error_message = "without /etc/jaws/config the stack reads config/ at the repository root, as the CLI reads ./config"
  }
}
