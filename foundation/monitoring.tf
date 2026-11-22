# The monitoring and cost platform's account half (config/monitoring.yaml,
# docs/monitoring.md). The stack itself is monitoring/'s, applied in the same
# release right after this one; the organization's AWS export is the owner's
# billing-export/ root, in the management account. Without the monitoring
# section none of this exists.
#
#   billing bucket             monitoring.cost.bucket: every billing source delivers
#                              under raw/, the normalizer writes normalized/; the
#                              management account's exports may deliver into it
#   Databricks billing job     jaws-databricks-billing-export on the shared host,
#                              with monitoring.cost.databricks
#   task run records           each project's task role (bots.tf) may put its own
#                              records under raw/provider=jaws/source=task-runs/
#   jaws-monitoring-ci-plan    trusted for pull_request      tfstate/read, monitoring/read, compute/read
#   jaws-monitoring-ci-apply   trusted for environment:prod  tfstate/write, monitoring/read, monitoring/node,
#                                                            monitoring/config, monitoring/functions,
#                                                            monitoring/backup, compute/read, compute/manage
#
# The roles' project is monitoring, so the stack is named jaws-monitoring and
# tags everything Project = monitoring (monitoring/providers.tf): the
# monitoring/* leaves scope its roles, functions, parameters and EC2 to that
# name and tag. compute/* adds the stack's own VPC (jaws-network's vpc, spec
# 6.5), which no monitoring/* leaf creates. Its state is the monitoring key of
# config/terraform.yaml's key template, listed in state.tf.

locals {
  monitoring      = try(local.tool_config.monitoring, null)
  monitoring_cost = try(local.monitoring.cost, null)

  # The organization's management account, the payer whose export covers every
  # account: billing-export/ creates the export there.
  management_account_id = one([for account in values(local.tool_config.aws.accounts) : account.account_id if account.type == "management"])

  billing_bucket = local.monitoring_cost == null ? null : {
    name                          = local.monitoring_cost.bucket
    aws_export_source_account_ids = try(local.monitoring_cost.aws, true) ? [local.management_account_id] : []
    # Off until the first deliveries are checked (jaws.settings.MonitoringCost).
    protect_raw = try(local.monitoring_cost.protect_raw, false)
  }

  # Each task role's run records (jaws.run_records): `task run` and `task sweep`
  # write them with the project's task role, which task/records lets put objects
  # under its own project's prefix, and nothing else in the bucket (bots.tf).
  task_records = local.billing_bucket == null ? {} : {
    for key in keys(local.bot_task_types) : key => {
      bucket = local.billing_bucket.name
      prefix = "raw/provider=jaws/source=task-runs/project=${key}"
    }
  }

  # Through the shared host, so it waits for its URL as the datasets do.
  databricks_billing = (
    local.monitoring_cost != null &&
    try(local.monitoring_cost.databricks, false) &&
    local.databricks_enabled &&
    local.databricks_host_recorded
  )

  monitoring_ci = {
    project = "monitoring"

    tfstate = {
      bucket_arn = module.state_bucket.arn
      key        = replace(replace(local.tool_config.state.key_template, "{project}", "monitoring"), "{environment}", "prod")
    }

    # The node's one record, in this stack's zone: the catalog takes the zone
    # and the domain together, or neither (a private node).
    monitoring = try(local.monitoring.domain, null) == null ? null : {
      zone_id = module.zone.zone_id
      domain  = local.monitoring.domain
    }
  }
}

# Refuses destroy and replacement (the module's prevent_destroy): taking the
# section out later fails this plan until the owner decides what to keep.
module "billing_bucket" {
  count   = local.billing_bucket == null ? 0 : 1
  source  = "Jaws-Platform/jaws-monitoring/aws//modules/billing-bucket"
  version = "0.8.0"

  bucket_name                   = local.billing_bucket.name
  aws_export_source_account_ids = local.billing_bucket.aws_export_source_account_ids
  protect_raw                   = local.billing_bucket.protect_raw
}

# A daily serverless job on the shared host that writes Databricks' billing
# system tables to the bucket's raw/provider=databricks/ prefix. It runs as the
# service principal this stack applies with, which is granted what it reads.
module "databricks_billing_export" {
  count     = local.databricks_billing ? 1 : 0
  source    = "Jaws-Platform/jaws-databricks/aws//modules/databricks-billing-export"
  version   = "0.2.0"
  providers = { aws = aws, databricks = databricks.shared }

  name             = "${local.context.name_root}-databricks-billing-export"
  bucket_name      = module.billing_bucket[0].name
  owner_group_name = module.databricks_metastore[0].admin_group_name
  component        = "billing"
}

module "monitoring_ci_plan" {
  count   = local.monitoring == null ? 0 : 1
  source  = "Jaws-Platform/jaws-ci/aws//modules/ci-plan-role"
  version = "0.4.0"

  project                    = local.monitoring_ci.project
  name_root                  = local.context.name_root
  repository                 = local.context.repository
  repository_aliases         = local.context.repository_aliases
  repository_alias_owner_ids = local.context.repository_alias_owner_ids
  owner_id                   = local.github.owner_id
  repository_id              = local.github.repository_id
  oidc_provider_arn          = data.aws_iam_openid_connect_provider.github.arn

  policies = ["tfstate/read", "monitoring/read", "compute/read"]

  policy_inputs = {
    tfstate    = local.monitoring_ci.tfstate
    monitoring = local.monitoring_ci.monitoring
  }
}

module "monitoring_ci_apply" {
  count   = local.monitoring == null ? 0 : 1
  source  = "Jaws-Platform/jaws-ci/aws//modules/ci-apply-role"
  version = "0.4.0"

  project                    = local.monitoring_ci.project
  name_root                  = local.context.name_root
  repository                 = local.context.repository
  repository_aliases         = local.context.repository_aliases
  repository_alias_owner_ids = local.context.repository_alias_owner_ids
  owner_id                   = local.github.owner_id
  repository_id              = local.github.repository_id
  oidc_provider_arn          = data.aws_iam_openid_connect_provider.github.arn
  environment                = "prod"

  # Eight managed policies: IAM attaches at most ten to a role by default.
  policies = [
    "tfstate/write",
    "monitoring/read", "monitoring/node", "monitoring/config", "monitoring/functions", "monitoring/backup",
    "compute/read", "compute/manage",
  ]

  policy_inputs = {
    tfstate    = local.monitoring_ci.tfstate
    monitoring = local.monitoring_ci.monitoring
  }
}
