# One root, two accounts. `var.account` chooses the management account (the
# configuration as written, where everything lives today) or the production
# account (the same file with `production.overrides` applied), and the
# foundation creates roles and buckets only for the projects with a stack in
# that account.
#
# The production runs plan against fixtures (tests/fixtures/*.yaml, kept equal
# to config.yaml plus a few values by tests/test_foundation_fixtures.py), so
# they state where each project stands and don't change with every move. The
# default run plans config.yaml as written.
# Mock providers: nothing is called.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "650503560686"
    }
  }

  mock_data "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::650503560686:oidc-provider/token.actions.githubusercontent.com"
    }
  }
}

mock_provider "databricks" {
  alias = "account"
}

mock_provider "databricks" {
  alias = "shared"
}

mock_provider "time" {}

# Check blocks compare module outputs with ARNs the stack derives; mocked,
# those outputs are unknown at plan, so each run gives them the derived values
# of the account it plans.

run "management_is_unchanged_by_default" {
  command = plan

  override_module {
    target = module.databricks_shared_host
    outputs = {
      workspace_id  = 7474644508802918
      workspace_url = "https://dbc-46322154-036c.cloud.databricks.com"
    }
  }

  override_module {
    target = module.sites_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:650503560686:repository/jwall-engineering-sites"
    }
  }

  override_module {
    target = module.site_bucket["main-site"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-main-site"
    }
  }

  override_module {
    target = module.site_bucket["cs-survival-guide"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-cs-survival-guide"
    }
  }

  override_module {
    target = module.site_bucket["guitar-knowledge-base"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-guitar-knowledge-base"
    }
  }

  override_module {
    target = module.dataset_catalog_storage
    outputs = {
      url                     = "s3://jwall-engineering-dataset-catalogs/managed"
      external_location_name  = "jwall-engineering-dataset-catalogs"
      storage_credential_name = "jwall-engineering-dataset-catalogs"
      bucket_name             = "jwall-engineering-dataset-catalogs"
      uc_role_arn             = "arn:aws:iam::650503560686:role/jwall-engineering-dataset-catalogs"
    }
  }

  assert {
    condition     = var.account == "management" && !local.in_production
    error_message = "the default account is management: a plan with no variable must be today's plan"
  }

  assert {
    condition     = local.state_bucket_name == "jwall-engineering-tfstate"
    error_message = "management's state bucket is jwall-engineering-tfstate"
  }

  assert {
    condition     = module.infra_ci_plan.role_name == "jwall-engineering-infra-ci-plan" && module.infra_ci_apply.role_name == "jwall-engineering-infra-ci-apply"
    error_message = "management's own roles keep their names"
  }

  assert {
    condition     = toset(keys(module.site_bucket)) == toset(keys(local.projects)) && toset(keys(module.site_ci_apply)) == toset([for k in keys(local.projects) : k if try(local.production_projects[k], "") != "moved"])
    error_message = "management keeps every registered site's bucket, and serves every site that has not moved"
  }

  assert {
    condition     = toset(keys(module.bot_ci_plan)) == toset([for k in keys(local.bots) : k if try(local.production_projects[k], "") != "moved"]) && toset(keys(module.bot_ci_apply)) == toset(keys(module.bot_ci_plan))
    error_message = "management serves every registered bot and research project that has not moved"
  }

  assert {
    condition     = toset(keys(module.databricks_ci_plan)) == toset([for k in keys(local.databricks_projects) : k if try(local.production_projects[k], "") != "moved"])
    error_message = "management serves every registered Databricks project that has not moved"
  }

  assert {
    condition     = module.bot_ci_plan["braveheart-trainer"].role_name == "jwall-engineering-braveheart-trainer-ci-plan"
    error_message = "a project's roles in management keep the jwall-engineering prefix"
  }

  assert {
    condition = jsonencode(module.context.tags) == jsonencode({
      Organization = "jwall-engineering"
      Project      = "jwall-engineering-infra"
      Environment  = "prod"
      Repository   = "jwallace145/jwall-engineering-infra"
      ManagedBy    = "jwall-engineering-infra"
      Owner        = "jwallace145"
    })
    error_message = "management's tags must not change, the Repository tag included: the rename does not retag the account"
  }

  assert {
    condition     = contains(local.bucket_admin_principal_arns, "arn:aws:iam::650503560686:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_22a17d3bc2bca2d3")
    error_message = "the owner's admin role in management stays exempt from the hardened bucket policies"
  }

  assert {
    condition     = length(module.databricks_metastore) == 0 && length(module.databricks_shared_host) == 0 && length(module.producer_catalog) == 0
    error_message = "Databricks moved to production as a whole (2026-11-19): management plans none of it"
  }
}

run "production_starts_empty" {
  command = plan

  variables {
    account     = "production"
    config_file = "tests/fixtures/production.yaml"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "570327089884"
    }
  }

  override_module {
    target = module.sites_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:570327089884:repository/jaws-cli"
    }
  }

  assert {
    condition     = local.account_id == "570327089884"
    error_message = "production is account 570327089884"
  }

  assert {
    condition     = local.state_bucket_name == "jaws-terraform-state-570327089884"
    error_message = "production's state bucket is jaws-terraform-state-570327089884"
  }

  assert {
    condition     = module.infra_ci_plan.role_name == "jaws-infra-ci-plan" && module.infra_ci_apply.role_name == "jaws-infra-ci-apply"
    error_message = "production's own roles are jaws-infra-ci-plan and jaws-infra-ci-apply"
  }

  assert {
    condition     = local.sites_image_repository_arn == "arn:aws:ecr:us-east-1:570327089884:repository/jaws-cli"
    error_message = "production's tool image repository is jaws-cli"
  }

  assert {
    condition     = local.databricks_secret_parameter_arn == "arn:aws:ssm:us-east-1:570327089884:parameter/jaws/databricks/client-secret" && local.databricks_events_arn_prefix == "arn:aws:s3:::jaws-databricks-audit-logs/events/"
    error_message = "the roles created in production must name production's Databricks secret and audit bucket, never the management account's"
  }

  assert {
    condition     = length(module.site_bucket) == 0 && length(module.site_ci_plan) == 0 && length(module.site_ci_preview) == 0 && length(module.site_ci_apply) == 0
    error_message = "no site is in production yet"
  }

  assert {
    condition     = length(module.bot_ci_plan) == 0 && length(module.bot_ci_apply) == 0 && length(module.bot_ci_release) == 0 && length(module.bot_ci_task) == 0
    error_message = "no bot or research project is in production yet"
  }

  assert {
    condition     = length(module.databricks_ci_plan) == 0 && length(module.databricks_ci_apply) == 0
    error_message = "no Databricks project is in production yet"
  }

  assert {
    condition     = length(module.databricks_metastore) == 0 && length(module.databricks_audit_logs) == 0 && length(module.databricks_shared_host) == 0 && length(module.databricks_dataset) == 0
    error_message = "Databricks is off in production until it moves as a whole"
  }

  assert {
    condition = jsonencode(module.context.tags) == jsonencode({
      Organization = "jaws"
      Project      = "jaws"
      Environment  = "prod"
      Repository   = "jwallace145/jaws"
      ManagedBy    = "jaws"
      Owner        = "jwallace145"
    })
    error_message = "production's tags are Organization=jaws, Project=jaws, ManagedBy=jaws"
  }

  assert {
    condition = length(local.bucket_admin_principal_arns) == 3 && slice(local.bucket_admin_principal_arns, 0, 2) == [
      "arn:aws:iam::570327089884:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_0123456789abcdef",
      "arn:aws:iam::570327089884:root",
    ]
    error_message = "production's break-glass principals are its own admin role and its own root, then its apply role"
  }
}

run "production_takes_its_managed_by_from_the_configuration" {
  command = plan

  # production.overrides.context.managed_by is a value no code spells.
  variables {
    account     = "production"
    config_file = "tests/fixtures/relabelled.yaml"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "570327089884"
    }
  }

  override_module {
    target = module.sites_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:570327089884:repository/jaws-cli"
    }
  }

  assert {
    condition     = module.context.tags["ManagedBy"] == "jaws-relabelled"
    error_message = "production's ManagedBy tag is config.yaml's production.overrides.context.managed_by, as the CLI stamps it on every stack it renders"
  }

  assert {
    condition     = module.context.tags["Organization"] == "jaws" && module.context.tags["Project"] == "jaws"
    error_message = "only ManagedBy differs from production's usual tags"
  }
}

run "a_moving_project_has_roles_in_production" {
  command = plan

  variables {
    account     = "production"
    config_file = "tests/fixtures/moving.yaml"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "570327089884"
    }
  }

  override_module {
    target = module.sites_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:570327089884:repository/jaws-cli"
    }
  }

  override_module {
    target = module.site_bucket["main-site"]
    outputs = {
      arn = "arn:aws:s3:::jaws-main-site"
    }
  }

  assert {
    condition     = keys(module.bot_ci_plan) == ["braveheart-trainer"] && keys(module.bot_ci_apply) == ["braveheart-trainer"]
    error_message = "production serves exactly the bot and research projects listed under production.projects"
  }

  assert {
    condition     = module.bot_ci_plan["braveheart-trainer"].role_name == "jaws-braveheart-trainer-ci-plan" && module.bot_ci_apply["braveheart-trainer"].role_name == "jaws-braveheart-trainer-ci-apply"
    error_message = "a project's roles in production carry the jaws prefix"
  }

  assert {
    condition     = local.bot_datasets["braveheart-trainer"] == ["jaws-braveheart-trainer-nets"]
    error_message = "a project's roles in production manage only its bucket with the jaws prefix, never the management account's"
  }

  assert {
    condition     = keys(module.bot_ci_task) == ["braveheart-trainer"] && module.bot_ci_task["braveheart-trainer"].role_name == "jaws-braveheart-trainer-ci-task"
    error_message = "a research project in production has its task role there"
  }

  assert {
    condition     = keys(local.state_prefix_access) == ["project=braveheart-trainer/", "project=data-access/env=prod/data-access-prod.tfstate", "project=infra/env=prod/infra-prod.tfstate", "project=main-site/"]
    error_message = "production's state bucket admits exactly the stacks that live there"
  }

  assert {
    condition     = keys(module.site_ci_apply) == ["main-site"] && module.site_ci_apply["main-site"].role_name == "jaws-main-site-ci-apply"
    error_message = "a site that has moved has its roles in production"
  }

  assert {
    condition     = local.project_ci["main-site"].static_site.bucket_arn == "arn:aws:s3:::jaws-main-site"
    error_message = "a site's bucket in production is jaws-<site>"
  }
}

run "a_moving_project_keeps_its_roles_in_management" {
  command = plan

  variables {
    config_file = "tests/fixtures/moving.yaml"
  }

  override_module {
    target = module.databricks_shared_host
    outputs = {
      workspace_id  = 7474644508802918
      workspace_url = "https://dbc-46322154-036c.cloud.databricks.com"
    }
  }

  override_module {
    target = module.sites_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:650503560686:repository/jwall-engineering-sites"
    }
  }

  override_module {
    target = module.site_bucket["cs-survival-guide"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-cs-survival-guide"
    }
  }

  override_module {
    target = module.site_bucket["guitar-knowledge-base"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-guitar-knowledge-base"
    }
  }

  override_module {
    target = module.dataset_catalog_storage
    outputs = {
      url                     = "s3://jwall-engineering-dataset-catalogs/managed"
      external_location_name  = "jwall-engineering-dataset-catalogs"
      storage_credential_name = "jwall-engineering-dataset-catalogs"
      bucket_name             = "jwall-engineering-dataset-catalogs"
      uc_role_arn             = "arn:aws:iam::650503560686:role/jwall-engineering-dataset-catalogs"
    }
  }

  assert {
    condition     = contains(keys(module.bot_ci_apply), "braveheart-trainer") && module.bot_ci_apply["braveheart-trainer"].role_name == "jwall-engineering-braveheart-trainer-ci-apply"
    error_message = "while a project is moving, its old stack's roles stay in management: they are what destroys it"
  }

  assert {
    condition     = local.bot_datasets["braveheart-trainer"] == ["jwall-engineering-braveheart-trainer-nets"]
    error_message = "in management a moving project keeps its approved buckets"
  }

  assert {
    condition     = !contains(keys(module.site_ci_plan), "main-site") && !contains(keys(module.site_ci_preview), "main-site") && !contains(keys(module.site_ci_apply), "main-site")
    error_message = "a site that has moved has no roles left in the management account"
  }

  assert {
    condition     = toset(keys(module.site_bucket)) == toset(["main-site", "cs-survival-guide", "guitar-knowledge-base"])
    error_message = "a site that has moved keeps its old bucket in the management account: buckets are never destroyed by a move, the owner deletes them by hand"
  }

  assert {
    condition     = local.retained_site_buckets == toset(["main-site"]) && !contains(keys(local.project_ci), "main-site")
    error_message = "the old bucket of a moved site is retained without any CI role or policy input of its own"
  }

  assert {
    condition     = !contains(keys(local.state_prefix_access), "project=main-site/")
    error_message = "a moved site's state prefix is closed in the management account"
  }
}

run "a_moved_bot_leaves_management" {
  command = plan

  variables {
    config_file = "tests/fixtures/moved.yaml"
  }

  override_module {
    target = module.databricks_shared_host
    outputs = {
      workspace_id  = 7474644508802918
      workspace_url = "https://dbc-46322154-036c.cloud.databricks.com"
    }
  }

  override_module {
    target = module.sites_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:650503560686:repository/jwall-engineering-sites"
    }
  }

  override_module {
    target = module.site_bucket["main-site"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-main-site"
    }
  }

  override_module {
    target = module.site_bucket["cs-survival-guide"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-cs-survival-guide"
    }
  }

  override_module {
    target = module.site_bucket["guitar-knowledge-base"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-guitar-knowledge-base"
    }
  }

  override_module {
    target = module.dataset_catalog_storage
    outputs = {
      url                     = "s3://jwall-engineering-dataset-catalogs/managed"
      external_location_name  = "jwall-engineering-dataset-catalogs"
      storage_credential_name = "jwall-engineering-dataset-catalogs"
      bucket_name             = "jwall-engineering-dataset-catalogs"
      uc_role_arn             = "arn:aws:iam::650503560686:role/jwall-engineering-dataset-catalogs"
    }
  }

  assert {
    condition     = !contains(keys(module.bot_ci_plan), "braveheart-bot") && !contains(keys(module.bot_ci_apply), "braveheart-bot") && !contains(keys(module.bot_ci_release), "braveheart-bot")
    error_message = "a bot that has moved has no roles left in the management account"
  }

  assert {
    condition     = toset(keys(module.bot_ci_plan)) == setsubtract(toset(keys(local.bots)), ["braveheart-bot"])
    error_message = "the other bot and research projects keep their roles in management"
  }

  assert {
    condition     = !contains(keys(local.state_prefix_access), "project=braveheart-bot/")
    error_message = "a moved bot's state prefix is closed in the management account"
  }
}

run "rejects_an_unknown_account" {
  command = plan

  variables {
    account = "dev"
  }

  expect_failures = [var.account]
}

run "rejects_a_production_project_that_is_not_registered" {
  command = plan

  variables {
    account     = "production"
    config_file = "tests/fixtures/unregistered.yaml"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "570327089884"
    }
  }

  expect_failures = [data.aws_caller_identity.current]
}

run "rejects_the_other_accounts_credentials" {
  command = plan

  # The mock's caller is the management account.
  variables {
    account     = "production"
    config_file = "tests/fixtures/production.yaml"
  }

  expect_failures = [data.aws_caller_identity.current]
}

run "rejects_production_before_its_admin_role_is_known" {
  command = plan

  # config.yaml before the bootstrap: production has no admin_role_arn of its
  # own. A fixture, so this run survives the pull request that adds one.
  variables {
    account     = "production"
    config_file = "tests/fixtures/unbootstrapped.yaml"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "570327089884"
    }
  }

  expect_failures = [data.aws_caller_identity.current]
}

# Databricks moves as a whole: both accounts use the one Databricks account,
# which holds one metastore per region, so it is enabled in one at a time
# (tests/test_databricks_accounts.py). Production builds it in two releases:
# the metastore, the audit logs and the shared host first; then, once the
# host's URL is recorded in config.yaml, the onboarded datasets.
run "databricks_in_production_starts_with_the_host" {
  command = plan

  variables {
    account     = "production"
    config_file = "tests/fixtures/databricks-switched.yaml"
  }

  # The host exists after this apply and config.yaml does not name its URL yet:
  # the check says so on every plan until the next release records it.
  expect_failures = [check.shared_host_url]

  override_module {
    target = module.databricks_shared_host
    outputs = {
      workspace_id  = 1111111111111111
      workspace_url = "https://dbc-0f0f0f0f-aaaa.cloud.databricks.com"
    }
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "570327089884"
    }
  }

  override_module {
    target = module.sites_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:570327089884:repository/jaws-cli"
    }
  }

  assert {
    condition     = length(module.databricks_metastore) == 1 && length(module.databricks_audit_logs) == 1 && length(module.databricks_shared_host) == 1
    error_message = "the first release in production creates the metastore, the audit log delivery and the shared host"
  }

  assert {
    condition     = local.databricks.metastore_name == "jaws-us-east-1" && local.databricks.audit_bucket == "jaws-databricks-audit-logs" && local.databricks_host_name == "jaws-shared"
    error_message = "production's metastore, audit bucket and shared host carry production's names"
  }

  assert {
    condition     = length(local.onboarded_datasets) == 0 && length(module.dataset_catalog_storage) == 0 && length(module.producer_catalog) == 0 && length(module.databricks_dataset) == 0
    error_message = "no dataset is onboarded before the host's URL is recorded: their provider is configured from it"
  }

  assert {
    condition     = keys(module.databricks_ci_plan) == ["braveheart-databricks"] && module.databricks_ci_plan["braveheart-databricks"].role_name == "jaws-braveheart-databricks-ci-plan" && module.databricks_ci_apply["braveheart-databricks"].role_name == "jaws-braveheart-databricks-ci-apply"
    error_message = "a workspace project that has moved has its roles in production, under production's names"
  }
}

run "databricks_in_production_onboards_once_the_host_is_recorded" {
  command = plan

  variables {
    account     = "production"
    config_file = "tests/fixtures/databricks-onboarded.yaml"
  }

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "570327089884"
    }
  }

  override_module {
    target = module.sites_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:570327089884:repository/jaws-cli"
    }
  }

  override_module {
    target = module.databricks_shared_host
    outputs = {
      workspace_id  = 1111111111111111
      workspace_url = "https://dbc-0f0f0f0f-aaaa.cloud.databricks.com"
    }
  }

  override_module {
    target = module.dataset_catalog_storage
    outputs = {
      url                     = "s3://jaws-dataset-catalogs/managed"
      external_location_name  = "jaws-dataset-catalogs"
      storage_credential_name = "jaws-dataset-catalogs"
      bucket_name             = "jaws-dataset-catalogs"
      uc_role_arn             = "arn:aws:iam::570327089884:role/jaws-dataset-catalogs"
    }
  }

  assert {
    condition     = jsonencode(keys(local.onboarded_datasets)) == jsonencode(["braveheart-selfplay-positions"]) && length(module.dataset_catalog_storage) == 1 && jsonencode(keys(module.producer_catalog)) == jsonencode(["braveheart_selfplay"])
    error_message = "with the host recorded, production onboards the registry's datasets under their producers' catalogs"
  }

  assert {
    condition     = local.onboarded_datasets["braveheart-selfplay-positions"].platform_name == "jaws-ds-braveheart-selfplay-positions" && local.onboarded_datasets["braveheart-selfplay-positions"].bucket == "jaws-braveheart-selfplay-positions"
    error_message = "production's dataset role and the bucket it reads carry production's names: nothing points at the management account"
  }
}

run "management_has_no_databricks_after_the_switch" {
  command = plan

  variables {
    config_file = "tests/fixtures/databricks-switched.yaml"
  }

  override_module {
    target = module.sites_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:650503560686:repository/jwall-engineering-sites"
    }
  }

  override_module {
    target = module.site_bucket["main-site"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-main-site"
    }
  }

  override_module {
    target = module.site_bucket["cs-survival-guide"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-cs-survival-guide"
    }
  }

  override_module {
    target = module.site_bucket["guitar-knowledge-base"]
    outputs = {
      arn = "arn:aws:s3:::jwall-engineering-guitar-knowledge-base"
    }
  }

  assert {
    condition     = length(module.databricks_metastore) == 0 && length(module.databricks_audit_logs) == 0 && length(module.databricks_shared_host) == 0 && length(module.dataset_catalog_storage) == 0 && length(module.producer_catalog) == 0 && length(module.databricks_dataset) == 0
    error_message = "once Databricks is enabled in production, management plans none of it"
  }

  assert {
    condition     = !contains(keys(module.databricks_ci_plan), "braveheart-databricks")
    error_message = "a workspace project that has moved has no roles left in management"
  }
}
