# Identity of this stack. It lives in the organization's management account
# (config.yaml `management`), where AWS Organizations and IAM Identity Center
# are, and grants the owner admin access there, in production (config.yaml
# `aws`) and in development (config.yaml `development`).
#
# Its names and tags are the ones it was first applied with, stated here rather
# than read from config.yaml, whose context is the production account's.

locals {
  region      = "us-east-1"
  tool_config = yamldecode(file("${path.module}/../config.yaml"))
  account_id  = local.tool_config.management.account_id

  production_account_id  = local.tool_config.aws.account_id
  development_account_id = try(local.tool_config.development.account_id, null)

  context = {
    organization = "jwall-engineering"
    project      = "jwall-engineering-infra" # Project tag value
    environment  = "prod"
    repository   = "jwallace145/jwall-engineering-infra" # the Repository tag it was first applied with
    owner        = local.tool_config.context.owner
  }
}

module "context" {
  source  = "Jaws-Platform/jaws-foundation/aws//modules/context"
  version = "0.1.3"

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
