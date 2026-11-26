# shellcheck shell=bash
# Sourced, not executed, by the foundation's `terraform plan` and `terraform
# apply` steps (ci.yml terraform-plan, release-please.yml apply, data-access.yml):
#
#   source ../scripts/databricks-credentials.sh ../config "$NAME_ROOT"
#
# The first argument is the tool configuration: the config/ directory (its
# databricks.yaml is read), or one file holding the databricks section. The
# second is the platform's name root.
#
# A platform may leave databricks.secret_parameter out, and the name then
# follows its name root (/<name_root>/databricks/client-secret), as
# jaws.settings.databricks_defaults derives it. The CLI is not installed yet at
# the steps that source this, and a workflow step does not read the name root
# itself, so the sourcing step passes the one it already holds.
#
# When databricks.enabled is true it reads the service principal's client
# secret from SSM (with the AWS role already assumed), masks it, and exports
# DATABRICKS_ACCOUNT_ID, DATABRICKS_CLIENT_ID and DATABRICKS_CLIENT_SECRET into
# the sourcing step's shell only, where the databricks provider reads them. It
# never writes to the step's environment or output files, so no other step (and
# no third-party action) sees the secret. While databricks.enabled is false it
# does nothing.
_dbx_source=${1:-config}
_dbx_config=$_dbx_source
_dbx_name_root=${2:-}
if [ -d "$_dbx_source" ]; then
  _dbx_config=$_dbx_source/databricks.yaml
fi
_dbx_enabled=$(yq -r .databricks.enabled "$_dbx_config") || return 1
if [ "$_dbx_enabled" != "true" ]; then
  echo "databricks.enabled is $_dbx_enabled in $_dbx_config: no Databricks credential is needed"
  unset _dbx_source _dbx_config _dbx_name_root _dbx_enabled
  return 0
fi
_dbx_parameter=$(yq -r '.databricks.secret_parameter // ""' "$_dbx_config") || return 1
if [ -z "$_dbx_parameter" ]; then
  if [ -z "$_dbx_name_root" ]; then
    echo "::error::databricks.secret_parameter is not set and no name root was passed: source databricks-credentials.sh <config> <name_root>"
    return 1
  fi
  _dbx_parameter=/$_dbx_name_root/databricks/client-secret
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
# `::add-mask::` is a GitHub Actions command; anywhere else (an owner's shell)
# echoing it would print the secret, so it is emitted only inside Actions.
if [ "${GITHUB_ACTIONS:-}" = true ]; then
  echo "::add-mask::$_dbx_secret"
fi
DATABRICKS_ACCOUNT_ID=$(yq -r .databricks.account_id "$_dbx_config") || return 1
DATABRICKS_CLIENT_ID=$(yq -r .databricks.client_id "$_dbx_config") || return 1
DATABRICKS_CLIENT_SECRET=$_dbx_secret
export DATABRICKS_ACCOUNT_ID DATABRICKS_CLIENT_ID DATABRICKS_CLIENT_SECRET
echo "Databricks credential for account $DATABRICKS_ACCOUNT_ID loaded for this step (masked)"
unset _dbx_source _dbx_config _dbx_name_root _dbx_enabled _dbx_parameter _dbx_secret
