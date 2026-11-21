#!/usr/bin/env bash
# Applies the jwall-engineering repository settings to this repo with the GitHub
# CLI. Run once, after the conventions PR is merged and CI has run at least
# once (ruleset status checks must name existing checks).
#
#   ./scripts/apply-repo-settings.sh [owner/repo]
set -euo pipefail

REPO="${1:-Jaws-Platform/jaws}"

echo "==> Merge methods, squash commit format, auto-delete head branches ($REPO)"
gh api -X PATCH "repos/$REPO" \
  -F allow_squash_merge=true \
  -F allow_rebase_merge=true \
  -F allow_merge_commit=false \
  -f squash_merge_commit_title=PR_TITLE \
  -f squash_merge_commit_message=BLANK \
  -F delete_branch_on_merge=true \
  -F allow_update_branch=true \
  >/dev/null

echo "==> Ruleset on main"
existing_id="$(gh api "repos/$REPO/rulesets" --jq '.[] | select(.name == "main") | .id' || true)"

ruleset='{
  "name": "main",
  "target": "branch",
  "enforcement": "active",
  "bypass_actors": [],
  "conditions": { "ref_name": { "include": ["~DEFAULT_BRANCH"], "exclude": [] } },
  "rules": [
    { "type": "deletion" },
    { "type": "non_fast_forward" },
    { "type": "required_linear_history" },
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": false,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": false,
        "require_extra_approval_for_unattributed_changes": true,
        "required_reviewers": [],
        "allowed_merge_methods": ["squash", "rebase"]
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "do_not_enforce_on_create": false,
        "required_status_checks": [
          { "context": "Commit messages" },
          { "context": "PR title" },
          { "context": "Terraform fmt, validate, tflint" },
          { "context": "Terraform plan" },
          { "context": "Python lint, types, tests" },
          { "context": "Site stack validate, tflint" },
          { "context": "Image build and smoke test" },
          { "context": "Bot stack validate, tflint" },
          { "context": "Databricks account stack validate, tflint" },
          { "context": "Databricks workspace stack validate, tflint" },
          { "context": "Stack plans against mock providers" },
          { "context": "Databricks projects" },
          { "context": "Owner access stack validate, tflint, test" },
          { "context": "Data access stack validate, tflint, test" },
          { "context": "Data access plan" }
        ]
      }
    }
  ]
}'

if [ -n "$existing_id" ]; then
  echo "$ruleset" | gh api -X PUT "repos/$REPO/rulesets/$existing_id" --input - >/dev/null
  echo "    updated ruleset $existing_id"
else
  echo "$ruleset" | gh api -X POST "repos/$REPO/rulesets" --input - >/dev/null
  echo "    created"
fi

echo "==> Done. Verify at https://github.com/$REPO/settings/rules"
