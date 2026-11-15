provider "aws" {
  region = local.region

  # Every resource this stack creates carries the organisation-wide tag set.
  # Per-resource `tags` add `Component` and `Name` on top.
  default_tags {
    tags = module.context.tags
  }
}

# The Databricks account API, for the metastore and audit log delivery
# (databricks.tf). Credentials come from the environment only
# (DATABRICKS_ACCOUNT_ID, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET, set
# by scripts/databricks-credentials.sh), never from variables, so the
# secret is in no plan or state. While config.yaml databricks.enabled is false
# nothing uses this provider and it makes no call.
provider "databricks" {
  alias     = "account"
  host      = "https://accounts.cloud.databricks.com"
  auth_type = "oauth-m2m"
}

# The shared-objects host's workspace API (databricks.tf), for the shared
# datasets' credentials, locations, bindings and grants. Same service
# principal and environment credentials as the account provider; the host is
# the workspace this stack created, so its URL is known from state. Rebuilding
# the foundation from nothing therefore takes two applies: the host first, with
# no databricks_share in config.yaml, then the shares.
provider "databricks" {
  alias     = "shared"
  host      = local.databricks_enabled ? module.databricks_shared_host[0].workspace_url : null
  auth_type = "oauth-m2m"
}
