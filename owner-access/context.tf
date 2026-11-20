# Identity of this stack: the same owner, repository and tags as the
# foundation, read from the tool's config.yaml like the foundation does.

locals {
  region      = "us-east-1"
  tool_config = yamldecode(file("${path.module}/../config.yaml"))
  account_id  = local.tool_config.aws.account_id

  # The production account, where everything is moving (config.yaml,
  # `production`), and the development account (config.yaml, `development`),
  # where nothing is built yet. The owner has the same admin access in both.
  production_account_id  = local.tool_config.production.overrides.aws.account_id
  development_account_id = try(local.tool_config.development.account_id, null)

  context = {
    organization = local.tool_config.context.organization
    project      = "jwall-engineering-infra" # Project tag value
    environment  = "prod"
    repository   = "jwallace145/jwall-engineering-infra" # the Repository tag, unchanged in the management account
    owner        = local.tool_config.context.owner
  }
}

module "context" {
  source  = "Jaws-Platform/jaws-foundation/aws//modules/context"
  version = "0.1.0"

  project      = local.context.project
  environment  = local.context.environment
  repository   = local.context.repository
  owner        = local.context.owner
  organization = local.context.organization

  # Stated since the context module lost its organisation-specific defaults:
  # the values this stack has always had.
  name_root  = "jwall-engineering"
  managed_by = "jwall-engineering-infra"
}
