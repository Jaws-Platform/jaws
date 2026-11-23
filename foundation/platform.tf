# The platform's own repositories (config/sites.yaml, platform.repositories): the
# repositories whose workflows this account's CI roles trust. Their order matters:
# the first is the platform's own, the repository that manages this stack, so it is
# the Repository tag, the zone comment's owner and the repository the CI roles
# are scoped to; the others are trusted as the config says.

locals {
  platform_repositories = local.tool_config.platform.repositories
  platform_repository   = local.platform_repositories[0]

  # What the platform's own CI roles trust: the first repository's fields, and every
  # further one (jaws-ci's additional_repositories).
  platform_trust = {
    repository              = local.platform_repository.repository
    owner_id                = local.platform_repository.owner_id
    repository_id           = local.platform_repository.repository_id
    additional_repositories = slice(local.platform_repositories, 1, length(local.platform_repositories))
  }

  # The hub (platform.hub), whose pull requests also plan every site, and its entry
  # of platform.repositories, which holds the IDs its subjects carry. Empty without a
  # hub, or when the hub is not listed (the OIDC provider's precondition stops that).
  hub       = try(local.tool_config.platform.hub, null)
  hub_trust = local.hub == null ? [] : [for r in local.platform_repositories : r if r.repository == local.hub.repository]
}
