# The monitoring and cost platform (docs/monitoring.md): the root module of
# Jaws-Platform/jaws-monitoring/aws, the billing normalizer and the monitoring
# node wired together, in a VPC of its own. Everything is named jaws-monitoring
# (<name_root>-monitoring), the name the stack's CI roles are scoped to
# (foundation/ci-roles.tf).
#
#   network     jaws-network's vpc: one public subnet, no NAT, like a bot's
#   normalizer  jaws-monitoring-normalizer, hourly, from the billing bucket's raw/
#               into normalized/
#   node        jaws-monitoring: Grafana at monitoring.domain, on monitoring.schedule
#
# Built from config/monitoring.yaml only: no variable is set by hand. The
# foundation creates what this stack reads first: the billing bucket, the
# Databricks billing job and this stack's roles and state prefix. The owner sets
# the secrets (`jaws monitoring secrets`) and applies billing-export/, which
# delivers the AWS bill. Planned on pull requests (ci.yml monitoring-plan) and
# applied by the release's monitoring-apply job after the foundation's apply
# (release-please.yml).

locals {
  enabled = local.monitoring != null
  name    = "${local.name_root}-monitoring"

  # The node's zone: pinned, since moving it means a new subnet, instance and
  # data volume. The plan stops if the instance type is not offered there.
  availability_zones = ["us-east-1a"]

  # billing-export/'s export (the owner's root): AWS delivers under
  # <aws_export_prefix>/<name>/, the billing bucket's aws_export_prefix.
  aws_export = {
    prefix = "raw/provider=aws/source=data-exports"
    name   = "${local.name_root}-focus-daily"
  }

  # Databricks billing arrives once the foundation's job runs: with
  # monitoring.cost.databricks, Databricks enabled and its shared host recorded,
  # as foundation/monitoring.tf creates it.
  databricks_billing = (
    try(local.cost_config.databricks, false) &&
    try(local.tool_config.databricks.enabled, false) &&
    try(local.tool_config.databricks.shared_host_url, null) != null
  )

  # The owner's secrets, outside the stack's own /<name>/ parameters (which its
  # CI roles may write): jaws.settings.MONITORING_SECRETS_PREFIX.
  secrets_prefix = "/jaws/monitoring/"

  # Terraform's yamldecode reads a bare `on:` or `off:` key as a YAML 1.1 boolean,
  # the keys "true" and "false"; the CLI reads YAML 1.2. Either spelling works.
  schedule_config = try(local.monitoring.schedule, null)
  schedule = local.schedule_config == null ? null : {
    timezone = local.schedule_config.timezone
    days     = local.schedule_config.days
    on       = try(local.schedule_config["on"], local.schedule_config["true"])
    off      = try(local.schedule_config["off"], local.schedule_config["false"])
  }

  node = !local.enabled ? null : {
    instance_type = try(local.monitoring.instance_type, "t9g.medium")
    ami_name      = local.monitoring.ami
    domain        = try(local.monitoring.domain, null)
    # The ci-policies catalog takes the zone and the domain together, or neither.
    zone_id = try(local.monitoring.domain, null) == null ? null : local.tool_config.dns.zone_id
    grafana_admin = {
      user_parameter     = "${local.secrets_prefix}grafana-admin-user"
      password_parameter = "${local.secrets_prefix}grafana-admin-password"
    }
    snapshots = try(local.monitoring.snapshots, false) ? { enabled = true } : null
    schedule  = local.schedule
    slack = try(local.monitoring.slack, null) == null ? null : {
      channels = local.monitoring.slack.channels
      routes   = local.monitoring.slack.routes
    }
    thresholds = try(local.monitoring.thresholds, null)
  }

  cost = local.cost_config == null ? null : {
    bucket_name = local.cost_config.bucket
    aws         = try(local.cost_config.aws, true) ? { delivery_prefix = "${local.aws_export.prefix}/${local.aws_export.name}" } : null
    # Usage that carries no Project tag takes its workspace's: the shared host
    # is the platform's (the foundation's Project tag, jaws), and each
    # Databricks project's workspace, <project>-prod, its project's. By name:
    # matched once the names are known (the job's include_workspaces, or the
    # normalizer's workspace_names).
    databricks = !local.databricks_billing ? null : {
      workspace_projects = merge(
        { "${local.name_root}-shared" = "jaws" },
        { for key, project in local.registry : "${key}-prod" => key if project.type == "databricks" },
      )
    }
    # Written by `task run` and `task sweep` (jaws.run_records), joined to the
    # billing rows on the tags each task instance and volume carry.
    runs = {
      prefixes  = ["raw/provider=jaws/source=task-runs"]
      join_tags = ["RunId", "TaskId"]
    }
    budgets                  = try(local.cost_config.budgets, null)
    anomaly_floor_usd        = try(local.cost_config.anomaly_floor_usd, null)
    databricks_workspace_tag = "Workspace"
  }
}

# Plan-time: the pinned zone must offer the instance type (T9g reached general
# availability on 2026-11-20 and is not in every zone).
# tflint-ignore: terraform_unused_declarations # read for its postcondition alone
data "aws_ec2_instance_type_offerings" "zone" {
  count = local.enabled ? 1 : 0

  location_type = "availability-zone"

  filter {
    name   = "instance-type"
    values = [local.node.instance_type]
  }

  filter {
    name   = "location"
    values = local.availability_zones
  }

  lifecycle {
    postcondition {
      condition     = alltrue([for zone in local.availability_zones : contains(self.locations, zone)])
      error_message = "${local.node.instance_type} (monitoring.instance_type) is not offered in ${join(", ", local.availability_zones)}: pin a zone that offers it (local.availability_zones in monitoring/main.tf) before the node's first apply."
    }
  }
}

module "network" {
  count   = local.enabled ? 1 : 0
  source  = "Jaws-Platform/jaws-network/aws//modules/vpc"
  version = "0.1.2"

  name               = local.name
  availability_zones = local.availability_zones
}

module "monitoring" {
  count   = local.enabled ? 1 : 0
  source  = "Jaws-Platform/jaws-monitoring/aws"
  version = "0.9.1"

  name        = local.name
  bucket_name = local.cost.bucket_name
  vpc_id      = module.network[0].vpc_id
  subnet_id   = module.network[0].public_subnet_ids[0]

  instance_type = local.node.instance_type
  ami_name      = local.node.ami_name
  domain        = local.node.domain
  zone_id       = local.node.zone_id
  grafana_admin = local.node.grafana_admin
  snapshots     = local.node.snapshots
  schedule      = local.node.schedule
  # Acts only with a schedule and a domain: Grafana's name points at a page while the node is stopped.
  off_hours_page = true
  slack          = local.node.slack
  thresholds     = local.node.thresholds

  aws                      = local.cost.aws
  databricks               = local.cost.databricks
  runs                     = local.cost.runs
  budgets                  = local.cost.budgets
  anomaly_floor_usd        = local.cost.anomaly_floor_usd
  databricks_workspace_tag = local.cost.databricks_workspace_tag
}
