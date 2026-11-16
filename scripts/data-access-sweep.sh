#!/usr/bin/env bash
# One data-access sweep: plan, and apply exactly what the plan found.
#
#   scripts/data-access-sweep.sh
#
# Run in data-access/ after `terraform init`, with the rendered variables and
# the Databricks credential in the environment. Every sweep plans: the plan,
# not a record in the state, says whether the live bindings and grants match
# the render, so a failed or cancelled apply is retried by the next sweep, and
# drift (a grant made by hand, a recreated workspace) is undone or reported.
# Writes result=no-changes or result=applied to $GITHUB_OUTPUT when it is set.
set -euo pipefail

record() {
  if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    echo "result=$1" >>"$GITHUB_OUTPUT"
  fi
  echo "sweep: $1"
}

set +e
terraform plan -no-color -lock-timeout=60s -out=tfplan -detailed-exitcode
code=$?
set -e

case "$code" in
  0) record no-changes ;;
  2)
    terraform apply -no-color -lock-timeout=60s tfplan
    record applied
    ;;
  *)
    echo "sweep: the plan failed (exit $code); nothing was applied" >&2
    exit "$code"
    ;;
esac
