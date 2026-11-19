# shellcheck shell=bash
# Sourced, not executed, by the foundation's `terraform plan` and `terraform
# apply` steps (ci.yml terraform-plan, release-please.yml apply):
#
#   source ../scripts/databricks-credentials.sh ../config.yaml [management|production]
#
# The second argument is the account being planned (management by default):
# for production, `production.overrides.databricks.enabled` decides when
# config.yaml gives it one. When Databricks is enabled for the account it reads the service
# principal's client secret from SSM (with the AWS role already assumed),
# masks it, and exports DATABRICKS_ACCOUNT_ID, DATABRICKS_CLIENT_ID and
# DATABRICKS_CLIENT_SECRET into the sourcing step's shell only, where the
# databricks provider reads them. It never writes to GITHUB_ENV or
# GITHUB_OUTPUT, so no other step (and no third-party action) sees the
# secret. While databricks.enabled is false it does nothing.

_dbx_config=${1:-config.yaml}
_dbx_account=${2:-management}
case "$_dbx_account" in
  management | production) ;;
  *)
    echo "::error::databricks-credentials.sh: account must be management or production, got $_dbx_account"
    unset _dbx_config _dbx_account
    return 1
    ;;
esac
_dbx_enabled=$(yq -r .databricks.enabled "$_dbx_config") || return 1
if [ "$_dbx_account" = "production" ]; then
  # Production's own setting, when config.yaml gives it one (production.overrides).
  _dbx_override=$(yq -r .production.overrides.databricks.enabled "$_dbx_config") || return 1
  if [ "$_dbx_override" != "null" ]; then _dbx_enabled=$_dbx_override; fi
  unset _dbx_override
fi
if [ "$_dbx_enabled" != "true" ]; then
  echo "databricks.enabled is $_dbx_enabled for the $_dbx_account account in $_dbx_config: no Databricks credential is needed"
  unset _dbx_config _dbx_enabled _dbx_account
  return 0
fi
_dbx_parameter=$(yq -r .databricks.secret_parameter "$_dbx_config") || return 1
if [ "$_dbx_account" = "production" ]; then
  # Production's own parameter, when config.yaml gives it one: the secret is
  # stored in each account under that account's name.
  _dbx_override=$(yq -r .production.overrides.databricks.secret_parameter "$_dbx_config") || return 1
  if [ "$_dbx_override" != "null" ]; then _dbx_parameter=$_dbx_override; fi
  unset _dbx_override
fi
_dbx_secret=$(aws ssm get-parameter --with-decryption --name "$_dbx_parameter" \
  --query Parameter.Value --output text) || return 1
# A mask covers one line; refuse anything else without printing it.
if [ -z "$_dbx_secret" ] || [[ "$_dbx_secret" == *$'\n'* ]]; then
  echo "::error::$_dbx_parameter is empty or spans several lines; set it again with databricks credentials set"
  unset _dbx_secret
  return 1
fi
# Mask first: nothing may print or use the secret before this line.
# `::add-mask::` is a GitHub Actions command; anywhere else (an owner's shell,
# scripts/databricks-teardown.sh) echoing it would print the secret, so it is
# emitted only inside Actions.
if [ "${GITHUB_ACTIONS:-}" = true ]; then
  echo "::add-mask::$_dbx_secret"
fi
DATABRICKS_ACCOUNT_ID=$(yq -r .databricks.account_id "$_dbx_config") || return 1
DATABRICKS_CLIENT_ID=$(yq -r .databricks.client_id "$_dbx_config") || return 1
DATABRICKS_CLIENT_SECRET=$_dbx_secret
export DATABRICKS_ACCOUNT_ID DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET
echo "Databricks credential for account $DATABRICKS_ACCOUNT_ID loaded for this step (masked)"
unset _dbx_config _dbx_enabled _dbx_account _dbx_parameter _dbx_secret
