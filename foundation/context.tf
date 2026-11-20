# Identity of this stack: who owns it, which repo manages it, and the tag set
# that default_tags stamps on everything. Derived from the library's context
# module so every jwall-engineering stack tags resources the same way.

locals {
  region = "us-east-1"

  # From config.yaml (read in ecr.tf), the tool's single source for the account.
  account_id = local.account.aws.account_id

  context = {
    organization = local.account.context.organization
    # Project tag value, and the prefix of this stack's Name tags.
    project     = local.in_production ? "jaws" : "jwall-engineering-infra"
    environment = "prod"
    repository  = "jwallace145/jaws"

    # The `Repository` tag. Unchanged in the management account: its resources
    # leave with the move to production, and retagging 144 of them (a
    # Databricks workspace and a storage credential among them) would buy nothing.
    repository_tag = local.in_production ? "jwallace145/jaws" : "jwallace145/jwall-engineering-infra"
    owner          = "jwallace145"

    # Other names the roles its own workflows assume also trust, because
    # GitHub's OIDC subject contains the name: set the new name here before a
    # rename, and clear it once the rename is done. Empty since jaws.
    repository_aliases = []
  }

  # Numeric GitHub IDs for the immutable OIDC subject form
  # (repo:<owner>@<owner_id>/<name>@<repo_id>:...), which GitHub issues when
  # "use immutable subject" is on for the repository (the default for new
  # repos). Look up with: gh api repos/<owner>/<repo> --jq '{id, owner_id: .owner.id}'
  github = {
    owner_id      = 35950238
    repository_id = 1420037633
  }

  # Resource name prefix for this stack's own CI roles and Name tags. The
  # role names are fixed by convention (jwall-engineering-infra-ci-*), so this
  # is intentionally not module.context.name_prefix, which adds "-prod".
  name_prefix = local.context.project
}

module "context" {
  source  = "jwallace145/jaws-foundation/aws//modules/context"
  version = "0.1.0"

  project      = local.context.project
  environment  = local.context.environment
  repository   = local.context.repository_tag
  owner        = local.context.owner
  organization = local.context.organization
  name_root    = local.context.organization
  managed_by   = local.account.context.managed_by
}
