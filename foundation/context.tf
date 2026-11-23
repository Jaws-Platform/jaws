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
    repository  = local.platform_repository.repository

    # The `Repository` tag: the repository that manages this stack.
    repository_tag = local.platform_repository.repository
    owner          = local.account.context.owner

    # Other names the roles its own workflows assume also trust, because
    # GitHub's OIDC subject contains the name: set the new name here before a
    # rename or transfer (with the new owner's ID in repository_alias_owner_ids
    # for a transfer), and clear both once the move is done. Empty since the
    # transfer to Jaws-Platform on 2026-11-21. IAM compares the subject
    # case-sensitively: names are spelled exactly as GitHub sends the login.
    repository_aliases         = []
    repository_alias_owner_ids = {}
  }

  # Numeric GitHub IDs for the immutable OIDC subject form
  # (repo:<owner>@<owner_id>/<name>@<repo_id>:...), which GitHub issues when
  # "use immutable subject" is on for the repository (the default for new
  # repos). Look up with: gh api repos/<owner>/<repo> --jq '{id, owner_id: .owner.id}'
  github = {
    owner_id      = local.platform_repository.owner_id
    repository_id = local.platform_repository.repository_id
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
}
