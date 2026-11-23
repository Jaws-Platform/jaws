# The monitoring stack plans the product's neutral platform configuration
# (../tests/fixtures/platform) as written, against mock providers: nothing is called.
# One run, the default path, plans the repository's own config/ (see it below). A run block cannot address resources inside
# a child module, so these assert what the stack hands the monitoring module
# (local.*), the module's outputs, and the tags; the module's own tests
# (terraform-aws-jaws-monitoring) cover what it builds from them.

variables {
  config_path = "../tests/fixtures/platform"
}

mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "222222222222"
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
      arn = "arn:aws:iam::222222222222:role/jaws-monitoring"
    }
  }

  # The off-hours page's certificate is DNS-validated: the module makes one
  # validation record per domain_validation_options entry.
  mock_resource "aws_acm_certificate" {
    defaults = {
      arn = "arn:aws:acm:us-east-1:222222222222:certificate/00000000-0000-0000-0000-000000000000"
      domain_validation_options = [
        {
          domain_name           = "grafana.example.com"
          resource_record_name  = "_0123456789abcdef.grafana.example.com."
          resource_record_type  = "CNAME"
          resource_record_value = "_fedcba9876543210.acm-validations.example.invalid."
        }
      ]
    }
  }

  mock_resource "aws_cloudfront_distribution" {
    defaults = {
      domain_name    = "d1234567890abc.cloudfront.net"
      hosted_zone_id = "Z2FDTNDATAQYW2"
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
    condition     = local.node.domain == "grafana.example.com" && local.node.zone_id == "Z0000000000EXAMPLE"
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
    condition     = local.cost.bucket_name == "jaws-billing-222222222222"
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
    condition     = output.node.parameter_prefix == "/jaws-monitoring/node" && output.node.config_bucket == "jaws-monitoring-config-222222222222"
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
      Organization = "Example-Platform"
      Project      = "monitoring"
      Environment  = "prod"
      Repository   = "Jaws-Platform/jaws"
      ManagedBy    = "JAWS"
      Owner        = "example-owner"
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

run "grafana_shows_a_page_off_hours" {
  command = plan

  # The fixture's monitoring config has a schedule and a domain, so the module's
  # off-hours page plans: a CloudFront page the name points at while the node is stopped.
  assert {
    condition     = module.monitoring[0].off_hours_page_domain_name != null
    error_message = "with a schedule and a domain, Grafana's address shows an off-hours page while the node is stopped"
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
      account_id = "999999999999"
    }
  }

  expect_failures = [data.aws_caller_identity.current]
}

run "reads_its_configuration_from_the_repository_outside_the_image" {
  command = plan

  variables {
    config_path = null
  }

  # The second run that depends on the owner's configuration (the foundation's default-path run
  # is the first): the default path is the repository's own config/, so the plan fails on the
  # mocked neutral credentials (the asserts below are still evaluated). Plan 07 replaces it
  # when config/ leaves the repository.
  expect_failures = [data.aws_caller_identity.current]

  assert {
    condition     = !local.in_image && local.config_path == "./../config"
    error_message = "without /etc/jaws/config the stack reads config/ at the repository root, as the CLI reads ./config"
  }
}

run "takes_its_identity_from_the_configuration" {
  command = plan

  # Values no code spells (foundation/tests/fixtures/relabelled.yaml).
  variables {
    config_path = "../foundation/tests/fixtures/relabelled.yaml"
  }

  assert {
    condition     = module.context.tags["Repository"] == "Example-Org/platform" && module.context.tags["Owner"] == "example-owner" && module.context.tags["ManagedBy"] == "jaws-relabelled"
    error_message = "the tags are the configuration's: the first platform repository, context.owner and context.managed_by"
  }
}
