# Identity of this stack: who owns it, which repo manages it, and the tag set
# that default_tags stamps on everything. Derived from the library's context
# module so every jaws stack tags resources the same way. The owner, the
# organization and the repository come from the configuration (config/tool.yaml
# context, and the first of platform.repositories in platform.tf).

locals {
  region = "us-east-1"

  # The primary account of the registry (config/aws.yaml, read in config.tf), the
  # tool's single source for the account.
  account_id = local.account.aws.account_id

  context = {
    # The root of every name (config/tool.yaml context.name_root): jaws-infra-ci-*,
    # jaws-<project>-*. The Organization tag is context.organization, the GitHub
    # owner of this repository (docs/tagging.md).
    name_root    = local.account.context.name_root
    organization = local.account.context.organization
    # Project tag value, and the prefix of this stack's Name tags.
    project     = "jaws"
    environment = "prod"

    # The `Repository` tag: the repository that manages this stack.
    repository_tag = local.platform_repository.repository
    owner          = local.account.context.owner
  }

  # Resource name prefix for this stack's own CI roles and Name tags. The
  # role names are fixed by convention (jaws-infra-ci-*), so this
  # is intentionally not module.context.name_prefix, which adds "-prod".
  name_prefix = local.context.project
}

module "context" {
  source  = "Jaws-Platform/jaws-foundation/aws//modules/context"
  version = "0.2.0"

  project      = local.context.project
  environment  = local.context.environment
  repository   = local.context.repository_tag
  owner        = local.context.owner
  organization = local.context.organization
  name_root    = local.context.name_root
  managed_by   = local.account.context.managed_by
  extra_tags   = try(local.account.context.tags, {})
}
