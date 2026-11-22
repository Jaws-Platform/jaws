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
    # The tags every jaws stack carries (docs/tagging.md): Organization and
    # ManagedBy from config/tool.yaml (the GitHub owner of this repository, and
    # JAWS), Project jaws as the foundation's, and Repository the repository
    # that manages this stack.
    organization = local.tool_config.context.organization
    project      = "jaws"
    environment  = "prod"
    repository   = "Jaws-Platform/jaws"
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

  # The name root this stack has always had: its names never change.
  name_root  = "jwall-engineering"
  managed_by = local.tool_config.context.managed_by
}
