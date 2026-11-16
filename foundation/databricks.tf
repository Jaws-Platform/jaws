# The Databricks account resources this stack owns, and the CI roles of the
# Databricks workspace projects (config.yaml `databricks`, and
# `projects.<key>.databricks` for each project's guardrails).
#
# Account resources, one of each for the whole account:
#
#   the us-east-1 Unity Catalog metastore   every workspace in the region shares it
#   audit log delivery                      jwall-engineering-databricks-audit-logs, audit/
#
# They wait for config.yaml `databricks.enabled`. While it is false (the
# owner has not created the service principal yet) they are not planned, so
# the foundation plan needs no Databricks credential and the databricks
# provider makes no call. The workflows put the credential in the
# environment only when it is true (scripts/databricks-credentials.sh).
#
# The client secret is NOT created here: the owner writes the SSM parameter
# with `jwall-engineering-sites databricks credentials set`, so it is in no
# Terraform state. This stack only builds its ARN for the CI policies.
#
# The registry of Databricks workspace projects (a project file whose only
# component is a databricks-workspace). Each entry gets two CI roles:
#
#   jwall-engineering-<key>-ci-plan   trusted for pull_request on THIS repo     tfstate/read, compute/read, databricks/read
#   jwall-engineering-<key>-ci-apply  trusted for environment:prod on THIS repo tfstate/write, compute/read, compute/manage,
#                                                                               databricks/read, databricks/manage
#
# and no release or task role. Like a bot's, the project's stacks are planned
# and applied from this repository (ci.yml databricks-plan,
# databricks-apply.yml). Both stacks' state (account and workspace) lives
# under project=<key>/ in the shared bucket (state.tf).

locals {
  databricks = local.tool_config.databricks

  databricks_enabled = local.databricks.enabled

  # The one parameter holding the service principal's client secret, and the
  # event-log prefix in the audit bucket (each project appends under
  # <events_prefix>project=<key>/).
  databricks_secret_parameter_arn = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/${trimprefix(local.databricks.secret_parameter, "/")}"
  databricks_events_arn_prefix    = "arn:aws:s3:::${local.databricks.audit_bucket}/${trimsuffix(local.databricks.events_prefix, "/")}/"

  # repository_id: gh api repos/<owner>/<repo> --jq .id
  # One line per entry, as in bots.tf (the workflows read this block).
  databricks_projects = {
    databricks-poc        = { repository = "jwallace145/databricks-poc", repository_id = "1458298100" }
    braveheart-databricks = { repository = "Braveheart-Chess/braveheart-databricks", repository_id = "1458504699" }
  }

  databricks_ci = {
    for key, project in local.databricks_projects : key => {
      tfstate = {
        bucket_arn = module.state_bucket.arn
        prefix     = "project=${key}/"
      }
      databricks = {
        secret_parameter_arn = local.databricks_secret_parameter_arn
        events_object_arn    = "${local.databricks_events_arn_prefix}project=${key}/*"
      }
    }
  }
}

# The config.yaml placeholders must be filled in before `enabled` turns the
# account resources on: the metastore module would make the @example.com
# addresses its admins, and the nil UUID is no account or service principal.
# A failed precondition fails the plan, so nothing is applied. Not planned
# while disabled (the placeholders are expected then). The CLI's settings
# validation refuses the same config.yaml.
locals {
  databricks_nil_uuid = "00000000-0000-0000-0000-000000000000"
  databricks_placeholder_admins = [
    for email in local.databricks.metastore_admins : email
    if endswith(lower(email), "@example.com")
  ]
}

resource "terraform_data" "databricks_config_filled_in" {
  count = local.databricks_enabled ? 1 : 0

  lifecycle {
    precondition {
      condition     = lower(local.databricks.account_id) != local.databricks_nil_uuid
      error_message = "config.yaml databricks.account_id is still the nil UUID placeholder: fill in the Databricks account ID (or set databricks.enabled back to false)."
    }

    precondition {
      condition     = lower(local.databricks.client_id) != local.databricks_nil_uuid
      error_message = "config.yaml databricks.client_id is still the nil UUID placeholder: fill in the service principal's application (client) ID (or set databricks.enabled back to false)."
    }

    precondition {
      condition     = length(local.databricks_placeholder_admins) == 0
      error_message = "config.yaml databricks.metastore_admins still holds the placeholder ${join(", ", local.databricks_placeholder_admins)}: replace it with the owner's real email (an account user) before the foundation makes it a metastore admin."
    }
  }
}

module "databricks_metastore" {
  count     = local.databricks_enabled ? 1 : 0
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-metastore"
  version   = "0.22.0"
  providers = { databricks = databricks.account }

  name                             = local.databricks.metastore_name
  admin_user_names                 = local.databricks.metastore_admins
  service_principal_application_id = local.databricks.client_id
}

module "databricks_audit_logs" {
  count     = local.databricks_enabled ? 1 : 0
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-audit-logs"
  version   = "0.22.0"
  providers = { aws = aws, databricks = databricks.account }

  account_id  = local.databricks.account_id
  bucket_name = local.databricks.audit_bucket
}

# The shared-objects host: a serverless workspace with no VPC, NAT, buckets,
# catalog or users, so metastore-level objects that need a workspace to be
# created through but belong to no project (shared datasets, in
# stacks/databricks-shared) have a home. Only the metastore admin group is
# assigned to it. It has no standing AWS cost.
module "databricks_shared_host" {
  count     = local.databricks_enabled ? 1 : 0
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-host-workspace"
  version   = "0.22.0"
  providers = { databricks = databricks.account }

  account_id       = local.databricks.account_id
  workspace_name   = "jwall-engineering-shared"
  metastore_id     = module.databricks_metastore[0].metastore_id
  admin_group_name = module.databricks_metastore[0].admin_group_name

  tags = merge(module.context.tags, {
    CostCenter = "jwall-engineering-infra"
    Workspace  = "jwall-engineering-shared"
  })
}

# ------------------------------------------------------- shared datasets

# Dataset buckets shared, read-only, with Databricks workspace projects
# (config.yaml projects.<producer>.datasets.<bucket>.databricks_share). Each gets
# one read-only external location, registered once through the host and bound
# to every consumer: Unity Catalog refuses overlapping locations in a
# metastore. The share role reads only because the producer's bucket policy
# names it as a reader (the CLI adds it to the producer's readers), so the
# project that owns the data grants access. Names match settings.py
# (share_name, share_role_name).
locals {
  databricks_shares = local.databricks_enabled ? {
    for share in flatten([
      for producer, guardrails in local.tool_config.projects : [
        for bucket, retention in try(guardrails.datasets, {}) : {
          name      = trimprefix(bucket, "${local.context.organization}-")
          producer  = producer
          bucket    = bucket
          prefix    = retention.databricks_share.prefix
          consumers = sort(retention.databricks_share.consumers)
        } if try(retention.databricks_share, null) != null
      ]
    ]) : share.name => share
  } : {}

  # Workspaces are named <project>-<environment>, environment prod.
  databricks_share_consumers = distinct(flatten([for s in values(local.databricks_shares) : s.consumers]))
}

data "databricks_mws_workspaces" "all" {
  count    = length(local.databricks_shares) > 0 ? 1 : 0
  provider = databricks.account
}

# A consumer must exist before a share names it: its workspace ID is looked up
# by name, and binding to a workspace that does not exist would fail anyway.
resource "terraform_data" "databricks_share_consumers_exist" {
  count = length(local.databricks_shares) > 0 ? 1 : 0

  lifecycle {
    precondition {
      condition = alltrue([
        for c in local.databricks_share_consumers : contains(keys(data.databricks_mws_workspaces.all[0].ids), "${c}-prod")
      ])
      error_message = "A databricks_share consumer has no workspace yet: ${join(", ", [for c in local.databricks_share_consumers : c if !contains(keys(data.databricks_mws_workspaces.all[0].ids), "${c}-prod")])}. Run the Databricks apply for it first, then this release."
    }
  }
}

module "databricks_shared_dataset" {
  for_each  = local.databricks_shares
  source    = "jwallace145/jwall-engineering/aws//modules/databricks-shared-dataset"
  version   = "0.22.0"
  providers = { aws = aws, databricks = databricks.shared }

  name_root         = local.context.organization
  name              = each.key
  bucket            = each.value.bucket
  prefix            = each.value.prefix
  host_workspace_id = module.databricks_shared_host[0].workspace_id
  owner_group_name  = module.databricks_metastore[0].admin_group_name

  consumers = {
    for c in each.value.consumers : c => {
      workspace_id     = data.databricks_mws_workspaces.all[0].ids["${c}-prod"]
      users_group_name = "${c}-workspace-users"
    }
  }

  depends_on = [terraform_data.databricks_share_consumers_exist]
}

module "databricks_ci_plan" {
  for_each = local.databricks_projects
  source   = "jwallace145/jwall-engineering/aws//modules/ci-plan-role"
  version  = "0.22.0"

  project           = each.key
  repository        = local.context.repository
  owner_id          = local.github.owner_id
  repository_id     = local.github.repository_id
  oidc_provider_arn = data.aws_iam_openid_connect_provider.github.arn

  policies = ["tfstate/read", "compute/read", "databricks/read"]

  policy_inputs = {
    tfstate    = local.databricks_ci[each.key].tfstate
    databricks = local.databricks_ci[each.key].databricks
  }
}

module "databricks_ci_apply" {
  for_each = local.databricks_projects
  source   = "jwallace145/jwall-engineering/aws//modules/ci-apply-role"
  version  = "0.22.0"

  project           = each.key
  repository        = local.context.repository
  owner_id          = local.github.owner_id
  repository_id     = local.github.repository_id
  oidc_provider_arn = data.aws_iam_openid_connect_provider.github.arn
  environment       = "prod"

  policies = ["tfstate/write", "compute/read", "compute/manage", "databricks/read", "databricks/manage"]

  policy_inputs = {
    tfstate    = local.databricks_ci[each.key].tfstate
    databricks = local.databricks_ci[each.key].databricks
  }
}

# A registered project without its central guardrails would get roles but no
# network range or compute policies; one that is also a site or a bot would
# share (and overwrite) that project's state prefix entry in state.tf.
check "databricks_projects_have_guardrails" {
  assert {
    condition = alltrue([
      for key in keys(local.databricks_projects) :
      try(local.tool_config.projects[key].databricks, null) != null
    ])
    error_message = "Every entry of local.databricks_projects needs a projects.<key>.databricks entry in config.yaml."
  }

  assert {
    condition     = length(setintersection(keys(local.databricks_projects), concat(keys(local.bots), keys(local.projects)))) == 0
    error_message = "A Databricks project must not also be a site or a bot: they would share the project=<key>/ state prefix."
  }
}
