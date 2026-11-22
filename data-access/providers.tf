# The account API, to find each consumer's workspace ID by its name
# (<project>-prod). Credentials come from the environment only
# (DATABRICKS_ACCOUNT_ID, DATABRICKS_CLIENT_ID, DATABRICKS_CLIENT_SECRET, set
# by scripts/databricks-credentials.sh), as in the foundation, so the secret
# is in no plan or state.
provider "databricks" {
  alias     = "account"
  host      = "https://accounts.cloud.databricks.com"
  auth_type = "oauth-m2m"
}

# The shared-objects host's workspace API: the foundation created every
# onboarded dataset's external location through it, and this stack binds and
# grants through it. Its URL is config/databricks.yaml databricks.shared_host_url, which
# `access render` writes into the variables.
provider "databricks" {
  alias     = "host"
  host      = var.host_workspace_url
  auth_type = "oauth-m2m"
}
