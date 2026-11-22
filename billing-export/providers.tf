# The management account, with the owner's own credentials (the jwall-admin
# profile): never a CI role's. The plan stops on any other account (config.tf).
provider "aws" {
  region = local.region

  # The platform's tags with Project = monitoring, as on the monitoring stack.
  default_tags {
    tags = module.context.tags
  }
}
