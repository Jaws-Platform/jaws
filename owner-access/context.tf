# Identity of this stack. It lives in the organization's management account
# (the account of type management in config/aws.yaml), where AWS Organizations
# and IAM Identity Center are, and grants the owner admin access there, in the
# primary account (production) and in the development account.
#
# Its names and tags are the ones it was first applied with, stated here rather
# than read from config/tool.yaml, whose context is the primary account's.

locals {
  region = "us-east-1"

  # The tool configuration's files, read as one document (foundation/config.tf).
  tool_config_dir = "${path.module}/../config"
  tool_config = merge([
    for name in sort(fileset(local.tool_config_dir, "*.yaml")) :
    yamldecode(file("${local.tool_config_dir}/${name}"))
  ]...)
  accounts = local.tool_config.aws.accounts

  account_id             = one([for account in values(local.accounts) : account.account_id if account.type == "management"])
  production_account_id  = local.accounts[local.tool_config.aws.primary].account_id
  development_account_id = one([for account in values(local.accounts) : account.account_id if account.type == "development"])

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
  version = "0.2.0"

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
