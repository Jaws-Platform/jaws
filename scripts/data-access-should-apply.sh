#!/usr/bin/env bash
# Whether the data-access sweep plans and applies: prints `apply` or `skip`.
#
#   FULL=true|false scripts/data-access-should-apply.sh <terraform.tfvars.json>
#
# Run in data-access/ after `terraform init`, with the rendered variables. It
# skips only a run that would change nothing: the rendered fingerprint equals
# the applied state's, and the state reports nothing waiting (no dataset whose
# location is missing, no consumer whose workspace is missing). Everything
# else applies: FULL=true, a state with no fingerprint output (the first
# sweep), a different fingerprint, or something still waiting, whose inputs do
# not change when it becomes ready, so the fingerprint alone would never retry
# it. A render with no fingerprint is an error, never a decision.
set -euo pipefail

tfvars=${1:?usage: data-access-should-apply.sh <terraform.tfvars.json>}
rendered=$(jq -er '.fingerprint | strings' "$tfvars")

decide() {
  [[ "${FULL:-false}" == "true" ]] && return 1
  local applied waiting missing
  applied=$(terraform output -raw fingerprint 2>/dev/null) || return 1
  [[ "$applied" == "$rendered" ]] || return 1
  waiting=$(terraform output -json awaiting_onboarding 2>/dev/null) || return 1
  missing=$(terraform output -json missing_workspaces 2>/dev/null) || return 1
  [[ "$(jq -r 'length' <<<"$waiting")" == 0 && "$(jq -r 'length' <<<"$missing")" == 0 ]]
}

if decide; then
  echo skip
else
  echo apply
fi
