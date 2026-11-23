# The platform's own repositories (config/sites.yaml, platform.repositories): the
# repositories whose workflows this account's CI roles trust. Their order matters:
# the first is the platform's own, the repository that manages this stack, so it is
# the Repository tag, the zone comment's owner and the repository the CI roles
# are scoped to; the others are trusted as the config says.

locals {
  platform_repositories = local.tool_config.platform.repositories
  platform_repository   = local.platform_repositories[0]
}
