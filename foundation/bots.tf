# The registry of bot projects (jaws.yaml with
# `components`: a container image and a Lichess bot). Adding a bot means
# adding a line here; each entry gets three CI roles, and a fourth with a
# task runner (config.yaml, projects.*.instance_types):
#
#   jwall-engineering-<key>-ci-plan     trusted for pull_request on THIS repo     tfstate/read, container/read, task/read
#                                                                                 (+ dataset/read with datasets)
#                                                                                 (compute/read for container/read on research)
#   jwall-engineering-<key>-ci-apply    trusted for environment:prod on THIS repo tfstate/write, container/read, container/manage, task/read,
#                                                                                 task/manage, container/schedule
#                                                                                 (+ dataset/read, dataset/manage with datasets)
#                                                                                 (compute/* for container/* on research; no container/schedule)
#   jwall-engineering-<key>-ci-release  trusted for the bot repo's v* tags only   container/release (none on research)
#   jwall-engineering-<key>-ci-task     trusted for the bot repo's pull_request   task/launch, for every task profile
#                                       and main only (never forks)
#
# The bot's infrastructure is planned and applied from this repository (the
# consumer keeps no Terraform and no infra workflow): a bot stack apply can
# replace the instance, so it is a deliberate act here, not a consumer push.
# The consumer's own release workflow only ships images and rolls them out,
# with the release role, which can push to the bot's image repository, write
# /jwall-engineering/<key>/bot/* parameters and run the reconciler, and
# nothing else (it cannot read the Lichess token).
#
# State lives in the shared bucket under project=<key>/ (state.tf).

locals {
  # repository_id: gh api repos/<owner>/<repo> --jq .id
  # owner_id:      gh api repos/<owner>/<repo> --jq .owner.id, for a repository
  #                outside this account (an organisation's); without it the
  #                release and task roles trust local.github_owner_id.
  # One line per entry, `repository` first (the workflows read this block).
  #
  # A bot's key is at most 15 characters: it is repeated in the ARNs of the apply
  # role's container/manage policy, which IAM caps at 6,144 characters, and at 15
  # that policy is about 6,130. A research project's policies are far smaller
  # (compute/manage about 3,900 and task/launch about 4,050 characters at 19), so
  # its key may take the 30 a project name allows (tests/test_bots_registry.py).
  bots = {
    braveheart          = { repository = "Braveheart-Chess/braveheart", repository_id = "1435162673", owner_id = "356866252" }
    braveheart-bot      = { repository = "Braveheart-Chess/braveheart-lichess-bot", repository_id = "1459279608", owner_id = "356866252" }
    braveheart-selfplay = { repository = "Braveheart-Chess/braveheart-selfplay", repository_id = "1459456470", owner_id = "356866252" }
    braveheart-trainer  = { repository = "Braveheart-Chess/braveheart-trainer", repository_id = "1459456509", owner_id = "356866252" }
  }

  # The entries of `bots` without a bot or an image (kind research): their plan
  # and apply roles get compute/* for container/*, and they have no release role.
  #
  # braveheart dropped its bot on 2026-11-15, when the bot moved to braveheart-bot:
  # the engine keeps its task runner and NNUE dataset (docs/research-projects.md,
  # "A bot project that drops its bot"). braveheart-selfplay and braveheart-trainer
  # take over the engine's self-play pipeline and its training from 2026-11-16;
  # until the data moves to their own buckets they have task runners only.
  research_projects = toset(["braveheart", "braveheart-selfplay", "braveheart-trainer"])

  # The guardrails come from config.yaml's `projects`, not from the project
  # file. The launch role is assumed by the consumer's pull requests, so
  # these lists bound what that repository's code can start and which roles
  # it can use, and the consumer's own file must not be able to widen them.
  # A change to them is a reviewed change to config.yaml in this repository.
  #
  # Bots with a task-runner component, and the instance types their task
  # launch role may start.
  bot_task_types = { for k, p in local.tool_config.projects : k => p.instance_types if length(try(p.instance_types, [])) > 0 }

  # Their task profiles: the launch role may pass each profile's instance
  # role, <org>-<key>-task[-<profile>].
  bot_task_profiles = { for k, p in local.tool_config.projects : k => p.task_profiles if length(try(p.task_profiles, [])) > 0 }

  # Bots with dataset components, and their buckets, <Organization>-<project>-<name>.
  # Their plan and apply roles may read and configure these buckets, never
  # their objects. Only the buckets that carry this account's prefix: a project
  # that is moving has its old buckets approved in the management account and
  # its new ones in production, and each account's roles manage their own.
  bot_dataset_names = {
    for k, p in local.tool_config.projects : k => [
      for name in keys(try(p.datasets, {})) : name if startswith(name, "${local.context.organization}-")
    ]
  }
  bot_datasets = { for k, names in local.bot_dataset_names : k => names if length(names) > 0 }

  bot_tfstate = {
    for key, bot in local.served_bots : key => {
      bucket_arn = module.state_bucket.arn
      prefix     = "project=${key}/"
    }
  }
}

module "bot_ci_plan" {
  for_each = local.served_bots
  source   = "jwallace145/jwall-engineering/aws//modules/ci-plan-role"
  version  = "0.27.0"

  project            = each.key
  name_root          = local.context.organization
  repository         = local.context.repository
  repository_aliases = local.context.repository_aliases
  owner_id           = local.github.owner_id
  repository_id      = local.github.repository_id
  oidc_provider_arn  = data.aws_iam_openid_connect_provider.github.arn

  policies = concat(
    contains(local.research_projects, each.key) ? ["tfstate/read", "compute/read", "task/read"] : ["tfstate/read", "container/read", "task/read"],
    contains(keys(local.bot_datasets), each.key) ? ["dataset/read"] : [],
  )

  policy_inputs = {
    tfstate = local.bot_tfstate[each.key]
    dataset = contains(keys(local.bot_datasets), each.key) ? { bucket_names = local.bot_datasets[each.key] } : null
  }
}

module "bot_ci_apply" {
  for_each = local.served_bots
  source   = "jwallace145/jwall-engineering/aws//modules/ci-apply-role"
  version  = "0.27.0"

  project            = each.key
  name_root          = local.context.organization
  repository         = local.context.repository
  repository_aliases = local.context.repository_aliases
  owner_id           = local.github.owner_id
  repository_id      = local.github.repository_id
  oidc_provider_arn  = data.aws_iam_openid_connect_provider.github.arn
  environment        = "prod"

  policies = concat(
    contains(local.research_projects, each.key) ? ["tfstate/write", "compute/read", "compute/manage", "task/read", "task/manage"] : ["tfstate/write", "container/read", "container/manage", "task/read", "task/manage", "container/schedule"],
    contains(keys(local.bot_datasets), each.key) ? ["dataset/read", "dataset/manage"] : [],
  )

  policy_inputs = {
    tfstate = local.bot_tfstate[each.key]
    dataset = contains(keys(local.bot_datasets), each.key) ? { bucket_names = local.bot_datasets[each.key] } : null
  }
}

module "bot_ci_release" {
  for_each = { for key, bot in local.served_bots : key => bot if !contains(local.research_projects, key) }
  source   = "jwallace145/jwall-engineering/aws//modules/ci-release-role"
  version  = "0.27.0"

  project           = each.key
  name_root         = local.context.organization
  repository        = each.value.repository
  owner_id          = try(each.value.owner_id, local.github_owner_id)
  repository_id     = each.value.repository_id
  oidc_provider_arn = data.aws_iam_openid_connect_provider.github.arn

  policies = ["container/release"]
}

# Launches, runs and terminates the bot's ephemeral CI task instances from
# the consumer's own workflows (`task run`). Trusted for the consumer's
# pull_request and main events only: GitHub issues no OIDC token to fork
# pull requests, and the remote-task workflow refuses every other event.
module "bot_ci_task" {
  for_each = { for key, types in local.bot_task_types : key => types if try(local.serves[key], false) }
  source   = "jwallace145/jwall-engineering/aws//modules/ci-task-role"
  version  = "0.27.0"

  project           = each.key
  name_root         = local.context.organization
  repository        = local.bots[each.key].repository
  owner_id          = try(local.bots[each.key].owner_id, local.github_owner_id)
  repository_id     = local.bots[each.key].repository_id
  oidc_provider_arn = data.aws_iam_openid_connect_provider.github.arn

  policies = ["task/launch"]

  policy_inputs = {
    task = { instance_types = each.value, profiles = local.bot_task_profiles[each.key] }
  }
}
