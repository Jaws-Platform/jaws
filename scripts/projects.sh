#!/usr/bin/env bash
# Prints the projects of the given types onboarded in config/projects.yaml, as a
# JSON array of {"project", "repository", "type"} in the file's order: the
# matrices of ci.yml's bot-plan and databricks-plan jobs, and the lookups of
# bot-apply.yml and databricks-apply.yml. `repository` is <owner>/<name>.
#
# Usage: scripts/projects.sh [--config <config dir or one file>] TYPE...
#        TYPE is site, bot, research or databricks.
set -euo pipefail

config=config
if [ "${1:-}" = "--config" ]; then
  config=${2:?--config needs a path}
  shift 2
fi
if [ $# -eq 0 ]; then
  echo "usage: scripts/projects.sh [--config PATH] TYPE..." >&2
  exit 2
fi
for type in "$@"; do
  case $type in
    site | bot | research | databricks) ;;
    *)
      echo "unknown project type: $type (site, bot, research or databricks)" >&2
      exit 2
      ;;
  esac
done

file=$config
if [ -d "$config" ]; then
  file=$config/projects.yaml
fi

# $owner and $type are yq variables, not shell ones.
# shellcheck disable=SC2016
TYPES=$(printf '%s\n' "$@" | jq -Rnc '[inputs]') yq -o=json -I=0 '
  [
    .projects | to_entries | .[] | .key as $owner
    | .value.projects | to_entries | .[]
    | select(.value.type as $type | env(TYPES) | any_c(. == $type))
    | {"project": .key, "repository": $owner + "/" + .value.repository, "type": .value.type}
  ]' "$file"
