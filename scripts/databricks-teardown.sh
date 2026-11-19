#!/usr/bin/env bash
# The one-time teardown of Databricks in the management account, before it is
# rebuilt in production (docs/databricks.md, "Moving Databricks to the
# production account"). The owner runs it from a clean checkout of main, in
# their own shell; no CI role could (its state and the Databricks account are
# behind the owner's admin role). Read-only until `go`.
#
#   scripts/databricks-teardown.sh access plan|go      the data-access stack's bindings and grants
#   scripts/databricks-teardown.sh foundation plan|go  the foundation's Databricks resources
#   scripts/databricks-teardown.sh secret              copy the client secret to production's parameter
#
# Order: `access go`; then the Databricks apply workflow's destroy of every
# workspace project; then `foundation go`; then `secret`. Each step refuses
# until the one before it is done.
#
# `foundation go` destroys, in order: the onboarded datasets, the producer
# catalogs, the catalogs' storage, the shared host, the audit log delivery and
# the metastore. Released from state first, and kept: every workspace binding
# and grant (each goes with its securable, which could not be deleted once
# its binding was gone), and the audit-log bucket with its configuration (a
# record; the owner deletes it by hand when satisfied). Data buckets are never
# touched: the datasets' buckets belong to their producers' stacks.
#
#   MANAGEMENT_PROFILE  the owner's management admin profile (default jwall-admin)
#   PRODUCTION_PROFILE  the owner's production admin profile (default jaws-prod)
set -euo pipefail

MANAGEMENT=650503560686
PRODUCTION=570327089884
MANAGEMENT_PROFILE=${MANAGEMENT_PROFILE:-jwall-admin}
PRODUCTION_PROFILE=${PRODUCTION_PROFILE:-jaws-prod}
WORKSPACE_PROJECTS=(databricks-poc braveheart-databricks)

# Every foundation module that holds a Databricks resource, dependents first.
FOUNDATION_STAGES=(
  "module.databricks_dataset"
  "module.producer_catalog"
  "module.dataset_catalog_storage"
  "module.databricks_shared_host"
  "module.databricks_audit_logs"
  "module.databricks_metastore"
)

# The checkout to work in (overridden only by the tests).
root=${TEARDOWN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}
die() { echo "databricks-teardown: $*" >&2; exit 1; }

usage() {
  grep '^#   scripts/databricks-teardown.sh ' "$0" | sed 's/^# *//' >&2
  exit 2
}

use_management() {
  export AWS_PROFILE=$MANAGEMENT_PROFILE
  local account
  account=$(aws sts get-caller-identity --query Account --output text) \
    || die "no credentials for $MANAGEMENT_PROFILE: run aws sso login --sso-session jwall-engineering"
  [ "$account" = "$MANAGEMENT" ] || die "$MANAGEMENT_PROFILE is account $account, not the management account $MANAGEMENT"
}

require_databricks_in_management() {
  [ "$(yq -r .databricks.enabled "$root/config.yaml")" = true ] \
    || die "config.yaml no longer enables Databricks in the management account: run this from a checkout from before the switch"
}

# The number of managed resources in one state object (0 if it does not exist).
state_resources() {
  local bucket key
  bucket=$(yq -r .state.bucket "$root/config.yaml")
  key=$1
  aws s3 cp --only-show-errors "s3://$bucket/$key" - 2>/dev/null \
    | jq '[.resources[]? | select(.mode == "managed")] | length' 2>/dev/null || echo 0
}

state_key() { # project [stack]
  local template
  template=$(yq -r .state.key_template "$root/config.yaml")
  local key=${template//\{project\}/$1}
  key=${key//\{environment\}/prod}
  if [ -n "${2:-}" ]; then key="${key%.tfstate}-$2.tfstate"; fi
  echo "$key"
}

confirm() {
  local answer
  read -r -p "Type 'destroy' to $1: " answer
  [ "$answer" = destroy ] || die "not confirmed; nothing was destroyed"
}

credentials() {
  # shellcheck disable=SC1091 # sourced from this checkout
  source "$root/scripts/databricks-credentials.sh" "$root/config.yaml" management
}

access_step() {
  local mode=$1
  use_management
  require_databricks_in_management
  cd "$root/data-access"
  terraform init -input=false -reconfigure -backend-config=backend/prod.hcl >/dev/null
  (cd "$root" && GH_TOKEN=${GH_TOKEN:-$(gh auth token)} uv run jaws --account management access render --out data-access)
  credentials
  terraform plan -destroy -input=false -lock-timeout=60s -out=teardown.tfplan
  if [ "$mode" = plan ]; then
    rm -f teardown.tfplan
    echo "access plan: nothing was changed"
    return
  fi
  confirm "destroy the data-access stack's bindings and grants in the management account"
  terraform apply -input=false -lock-timeout=60s teardown.tfplan
  rm -f teardown.tfplan
  echo "access: destroyed. Next: the Databricks apply workflow with action destroy for ${WORKSPACE_PROJECTS[*]}"
}

foundation_step() {
  local mode=$1
  use_management
  require_databricks_in_management
  [ "$(state_resources "$(state_key data-access)")" = 0 ] \
    || die "the data-access stack still holds resources: run \`$0 access go\` first"
  local project stack
  for project in "${WORKSPACE_PROJECTS[@]}"; do
    for stack in workspace account; do
      [ "$(state_resources "$(state_key "$project" "$stack")")" = 0 ] \
        || die "$project's $stack stack still holds resources: destroy it first (Databricks apply, action destroy)"
    done
  done
  cd "$root/foundation"
  terraform init -input=false -reconfigure -backend-config=backend/management.hcl >/dev/null
  credentials
  local releases
  releases=$(terraform state list | grep -E \
    '^module\.(databricks_dataset|producer_catalog|dataset_catalog_storage)\[[^]]*\]\.databricks_(workspace_binding|grants)\.|^module\.databricks_audit_logs\[0\]\.aws_s3_bucket(_[a-z_]+)?\.this$' || true)
  local targets=()
  local stage
  for stage in "${FOUNDATION_STAGES[@]}"; do targets+=("-target=$stage"); done
  echo "== released from state and kept:"
  printf '%s\n' "${releases:-  (none)}"
  echo "== destroyed:"
  terraform plan -destroy -input=false -lock-timeout=120s -var account=management "${targets[@]}"
  if [ "$mode" = plan ]; then
    echo "foundation plan: nothing was changed (the plan above still lists the released resources; go releases them first)"
    return
  fi
  confirm "destroy Databricks in the management account (metastore, shared host, catalogs, datasets, audit log delivery)"
  if [ -n "$releases" ]; then
    # shellcheck disable=SC2086 # one address per line, none with spaces
    terraform state rm -lock-timeout=120s $releases
  fi
  for stage in "${FOUNDATION_STAGES[@]}"; do
    echo "== destroying $stage"
    terraform destroy -auto-approve -input=false -lock-timeout=120s -var account=management "-target=$stage"
  done
  local left
  left=$(terraform state list | grep -E '\.databricks_[a-z_]+\.' | grep -v -E '_ci_(plan|apply)' || true)
  [ -z "$left" ] || die "Databricks resources are still in the management state:
$left"
  echo "foundation: destroyed. Kept: $(yq -r .databricks.audit_bucket "$root/config.yaml"). Next: \`$0 secret\`"
}

secret_step() {
  local parameter production_parameter value
  parameter=$(yq -r .databricks.secret_parameter "$root/config.yaml")
  production_parameter=$(yq -r .production.overrides.databricks.secret_parameter "$root/config.yaml")
  [ "$production_parameter" != null ] || die "config.yaml gives production no databricks.secret_parameter"
  [ "$(AWS_PROFILE=$PRODUCTION_PROFILE aws sts get-caller-identity --query Account --output text)" = "$PRODUCTION" ] \
    || die "$PRODUCTION_PROFILE is not the production account $PRODUCTION"
  use_management
  # Never printed: read into a variable, written from it, then unset.
  value=$(aws ssm get-parameter --with-decryption --name "$parameter" --query Parameter.Value --output text)
  [ -n "$value" ] || die "$parameter is empty"
  AWS_PROFILE=$PRODUCTION_PROFILE aws ssm put-parameter --name "$production_parameter" --type SecureString \
    --overwrite --value "$value" >/dev/null
  unset value
  echo "secret: copied $parameter (management) to $production_parameter (production); it was not printed"
}

case "${1:-}" in
  access) case "${2:-}" in plan | go) access_step "$2" ;; *) usage ;; esac ;;
  foundation) case "${2:-}" in plan | go) foundation_step "$2" ;; *) usage ;; esac ;;
  secret) secret_step ;;
  *) usage ;;
esac
