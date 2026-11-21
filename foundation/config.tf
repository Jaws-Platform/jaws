# The tool configuration, and the account it describes.
#
# config.yaml describes the one account jaws builds in, the JWall Engineering
# production account. Its sections are read here as `local.account`; the
# management and development accounts it records are owner-access's, never this
# root's.

variable "config_file" {
  description = "Path to the tool configuration. Null reads config.yaml at the repository root; the tests pass a fixture."
  type        = string
  default     = null
}

locals {
  # config.yaml lives at the repository root, next to the CLI that reads it.
  tool_config = yamldecode(file(var.config_file == null ? "${path.module}/../config.yaml" : var.config_file))

  # The sections that name things in the account.
  account = {
    aws        = local.tool_config.aws
    context    = local.tool_config.context
    state      = local.tool_config.state
    ecr        = local.tool_config.ecr
    databricks = local.tool_config.databricks
  }
}

# The credentials must be the account's, or the plan stops here: applied with
# another account's credentials, this root would create its names there.
data "aws_caller_identity" "current" {
  lifecycle {
    postcondition {
      condition     = self.account_id == local.account.aws.account_id
      error_message = "These credentials belong to account ${self.account_id}, but config.yaml's account is ${local.account.aws.account_id}: use that account's credentials."
    }

    postcondition {
      condition     = can(regex("^arn:aws:iam::${local.account.aws.account_id}:role/", local.account.aws.admin_role_arn))
      error_message = "config.yaml's aws.admin_role_arn is not a role in ${local.account.aws.account_id}. Without it the hardened bucket policies would lock the owner out."
    }
  }
}
