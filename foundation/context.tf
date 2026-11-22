# Identity of this stack: who owns it, which repo manages it, and the tag set
# that default_tags stamps on everything. Derived from the library's context
# module so every jaws stack tags resources the same way.

locals {
  region = "us-east-1"

  # From config.yaml (read in ecr.tf), the tool's single source for the account.
  account_id = local.account.aws.account_id

  context = {
    organization = local.account.context.organization
    # Project tag value, and the prefix of this stack's Name tags.
    project     = "jaws"
    environment = "prod"
    repository  = "Jaws-Platform/jaws"

    # The `Repository` tag: the repository that manages this stack.
    repository_tag = "Jaws-Platform/jaws"
    owner          = "jwallace145"

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
    owner_id      = 359185083 # Jaws-Platform
    repository_id = 1420037633
  }

  # Resource name prefix for this stack's own CI roles and Name tags. The
  # role names are fixed by convention (jaws-infra-ci-*), so this
  # is intentionally not module.context.name_prefix, which adds "-prod".
  name_prefix = local.context.project
}

module "context" {
  source  = "Jaws-Platform/jaws-foundation/aws//modules/context"
  version = "0.1.3"

  project      = local.context.project
  environment  = local.context.environment
  repository   = local.context.repository_tag
  owner        = local.context.owner
  organization = local.context.organization
  name_root    = local.context.organization
  managed_by   = local.account.context.managed_by
}
