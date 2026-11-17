# One root, two accounts.
#
# Everything is moving from the management account, where it lives today, to
# the production account. config.yaml describes the management account, and
# its `production` section says what differs in production and which projects
# have a stack there. `var.account` chooses which of the two this root is
# planned and applied for; each has its own state (backend/<account>.hcl).
#
# Nothing here is specific to one account: a name, an account ID or a bucket
# that differs comes from `local.account`, and every registry is filtered to
# the projects this account serves. When the last project has moved, the
# `production` section is folded into the top level and this file goes.

variable "account" {
  description = "The account this root is planned and applied for: `management` (config.yaml as written) or `production` (with `production.overrides` applied)."
  type        = string
  default     = "management"

  validation {
    condition     = contains(["management", "production"], var.account)
    error_message = "account must be `management` or `production`."
  }
}

variable "config_file" {
  description = "Path to the tool configuration. Null reads config.yaml at the repository root; the tests pass a fixture."
  type        = string
  default     = null
}

locals {
  # config.yaml lives at the repository root, next to the CLI that reads it.
  tool_config = yamldecode(file(var.config_file == null ? "${path.module}/../config.yaml" : var.config_file))

  in_production = var.account == "production"

  # The sections that differ between the accounts, as this account sees them:
  # in production, each `production.overrides` section merged over the section
  # of that name (settings.py builds the CLI's view the same way).
  account = {
    aws        = local.in_production ? merge(local.tool_config.aws, try(local.tool_config.production.overrides.aws, {})) : local.tool_config.aws
    context    = local.in_production ? merge(local.tool_config.context, try(local.tool_config.production.overrides.context, {})) : local.tool_config.context
    state      = local.in_production ? merge(local.tool_config.state, try(local.tool_config.production.overrides.state, {})) : local.tool_config.state
    ecr        = local.in_production ? merge(local.tool_config.ecr, try(local.tool_config.production.overrides.ecr, {})) : local.tool_config.ecr
    databricks = local.in_production ? merge(local.tool_config.databricks, try(local.tool_config.production.overrides.databricks, {})) : local.tool_config.databricks
  }

  # Where each project stands: absent (management only), `moving` (a stack in
  # both accounts) or `moved` (production only).
  production_projects = try(local.tool_config.production.projects, {})

  registered_projects = concat(keys(local.projects), keys(local.bots), keys(local.databricks_projects))

  # Whether this account's foundation creates a project's roles and buckets.
  # Management keeps a moving project's: they are what destroys its old stack.
  serves = {
    for key in local.registered_projects : key => (
      local.in_production
      ? contains(keys(local.production_projects), key)
      : try(local.production_projects[key], "") != "moved"
    )
  }

  served_sites = { for key, project in local.projects : key => project if local.serves[key] }

  # A site that has moved keeps its old bucket here. A move never destroys a
  # bucket: the owner deletes it by hand when satisfied. Only the bucket stays;
  # its roles, its state prefix and its policy inputs go with the site.
  retained_site_buckets = toset([
    for key in keys(local.projects) : key
    if !local.in_production && try(local.production_projects[key], "") == "moved"
  ])
  served_bots                = { for key, bot in local.bots : key => bot if local.serves[key] }
  served_databricks_projects = { for key, project in local.databricks_projects : key => project if local.serves[key] }
}

# The credentials and the configuration must be the chosen account's, or the
# plan stops here: applied with the other account's credentials, this root
# would create one account's names in the other.
data "aws_caller_identity" "current" {
  lifecycle {
    postcondition {
      condition     = self.account_id == local.account.aws.account_id
      error_message = "These credentials belong to account ${self.account_id}, but the ${var.account} account in config.yaml is ${local.account.aws.account_id}: use that account's credentials, or pass -var account=<the other account>."
    }

    postcondition {
      condition     = can(regex("^arn:aws:iam::${local.account.aws.account_id}:role/", local.account.aws.admin_role_arn))
      error_message = "config.yaml has no admin_role_arn for the ${var.account} account that is a role in ${local.account.aws.account_id} (in production it is production.overrides.aws.admin_role_arn, known once owner-access is applied). Without it the hardened bucket policies would lock the owner out."
    }

    postcondition {
      condition     = length(setsubtract(keys(local.production_projects), local.registered_projects)) == 0
      error_message = "config.yaml production.projects lists ${join(", ", setsubtract(keys(local.production_projects), local.registered_projects))}, which is in no registry (foundation/projects.tf, bots.tf, databricks.tf)."
    }
  }
}
