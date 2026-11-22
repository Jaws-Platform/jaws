# The tool configuration's files, read as one document (foundation/config.tf).
# This root lives in the organization's management account (the account of
# type management in config/aws.yaml), the payer whose bill covers every
# account, and delivers into the billing bucket the foundation creates in the
# primary account (config/monitoring.yaml monitoring.cost.bucket).

locals {
  region = "us-east-1"

  tool_config_dir = "${path.module}/../config"
  tool_config = merge([
    for name in sort(fileset(local.tool_config_dir, "*.yaml")) :
    yamldecode(file("${local.tool_config_dir}/${name}"))
  ]...)
  accounts = local.tool_config.aws.accounts

  account_id         = one([for account in values(local.accounts) : account.account_id if account.type == "management"])
  primary_account_id = local.accounts[local.tool_config.aws.primary].account_id
  name_root          = local.tool_config.context.name_root
  cost               = try(local.tool_config.monitoring.cost, null)
}

module "context" {
  source  = "Jaws-Platform/jaws-foundation/aws//modules/context"
  version = "0.2.0"

  project      = "monitoring"
  environment  = "prod"
  repository   = "Jaws-Platform/jaws"
  owner        = local.tool_config.context.owner
  organization = local.tool_config.context.organization
  name_root    = local.name_root
  managed_by   = local.tool_config.context.managed_by
}

# The credentials must be the management account's: only the payer's export
# covers the whole organization.
# tflint-ignore: terraform_unused_declarations # read for its condition alone
data "aws_caller_identity" "current" {
  lifecycle {
    postcondition {
      condition     = self.account_id == local.account_id
      error_message = "These credentials belong to account ${self.account_id}, but the export is created in the management account (config/aws.yaml), ${local.account_id}: use the owner's jwall-admin profile."
    }
  }
}
