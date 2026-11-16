# Identity of this stack: the same owner, repository and tags as the
# foundation, read from the tool's config.yaml like the foundation does.

locals {
  region      = "us-east-1"
  tool_config = yamldecode(file("${path.module}/../config.yaml"))
  account_id  = local.tool_config.aws.account_id

  context = {
    organization = local.tool_config.context.organization
    project      = "jwall-engineering-infra" # Project tag value
    environment  = "prod"
    repository   = "jwallace145/jwall-engineering-infra"
    owner        = local.tool_config.context.owner
  }
}

module "context" {
  source  = "jwallace145/jwall-engineering/aws//modules/context"
  version = "0.23.0"

  project      = local.context.project
  environment  = local.context.environment
  repository   = local.context.repository
  owner        = local.context.owner
  organization = local.context.organization
}
