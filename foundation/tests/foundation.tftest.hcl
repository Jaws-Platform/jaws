# The foundation of the account the platform configuration describes. The default runs plan the
# product's neutral platform configuration (../tests/fixtures/platform) as written; the others plan
# fixtures (tests/fixtures/*.yaml, kept equal to it plus a few values by
# tests/test_foundation_fixtures.py).
# Mock providers: nothing is called.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "222222222222"
    }
  }

  mock_data "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::222222222222:oidc-provider/token.actions.githubusercontent.com"
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

# Check blocks compare module outputs with ARNs and URLs the stack derives;
# mocked, those outputs are unknown at plan, so they are given the derived values.
override_module {
  target = module.sites_image
  outputs = {
    arn = "arn:aws:ecr:us-east-1:222222222222:repository/jaws-cli"
  }
}

override_module {
  target = module.databricks_shared_host
  outputs = {
    workspace_id  = 1111111111111111
    workspace_url = "https://dbc-00000000-0000.cloud.databricks.com"
  }
}

override_module {
  target = module.site_bucket["main-site"]
  outputs = {
    arn = "arn:aws:s3:::jaws-main-site"
  }
}

override_module {
  target = module.site_bucket["cs-survival-guide"]
  outputs = {
    arn = "arn:aws:s3:::jaws-cs-survival-guide"
  }
}

override_module {
  target = module.site_bucket["guitar-knowledge-base"]
  outputs = {
    arn = "arn:aws:s3:::jaws-guitar-knowledge-base"
  }
}

# The catalogs' storage builds IAM policies from data sources a mock provider
# fills with random strings; its own module test covers it.
override_module {
  target = module.dataset_catalog_storage
  outputs = {
    url                     = "s3://jaws-dataset-catalogs/managed"
    external_location_name  = "jaws-dataset-catalogs"
    storage_credential_name = "jaws-dataset-catalogs"
    bucket_name             = "jaws-dataset-catalogs"
    uc_role_arn             = "arn:aws:iam::222222222222:role/jaws-dataset-catalogs"
  }
}

# The fixtures are single files under tests/fixtures/, which has no datasets/:
# every run reads the repository's registry unless it says otherwise.
variables {
  config_path   = "../tests/fixtures/platform"
  datasets_path = "../datasets"
}

run "the_account_is_config_yamls" {
  command = plan

  assert {
    condition     = local.account_id == "222222222222" && local.state_bucket_name == "jaws-terraform-state-222222222222"
    error_message = "the account is 222222222222, with the state bucket jaws-terraform-state-222222222222"
  }

  assert {
    condition     = module.infra_ci_plan.role_name == "jaws-infra-ci-plan" && module.infra_ci_apply.role_name == "jaws-infra-ci-apply"
    error_message = "the foundation's own roles are jaws-infra-ci-plan and jaws-infra-ci-apply"
  }

  assert {
    condition     = local.sites_image_repository_arn == "arn:aws:ecr:us-east-1:222222222222:repository/jaws-cli"
    error_message = "the tool's image repository is jaws-cli"
  }

  assert {
    condition = jsonencode(module.context.tags) == jsonencode({
      Organization = "Example-Platform"
      Project      = "jaws"
      Environment  = "prod"
      Repository   = "Jaws-Platform/jaws"
      ManagedBy    = "JAWS"
      Owner        = "example-owner"
    })
    error_message = "the foundation's tags are Organization=Example-Platform (context.organization), Project=jaws, ManagedBy=JAWS"
  }

  assert {
    condition     = local.context.name_root == "jaws" && module.context.name_prefix == "jaws-jaws-prod"
    error_message = "names keep the name root (context.name_root), whatever the Organization tag says"
  }

  assert {
    condition = length(local.bucket_admin_principal_arns) == 3 && slice(local.bucket_admin_principal_arns, 0, 2) == [
      "arn:aws:iam::222222222222:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_0123456789abcdef",
      "arn:aws:iam::222222222222:root",
    ]
    error_message = "the break-glass principals are the owner's admin role and the account's root, then the apply role"
  }
}

run "every_registered_project_is_served" {
  command = plan

  assert {
    condition     = toset(keys(module.site_bucket)) == toset(keys(local.projects)) && toset(keys(module.site_ci_apply)) == toset(keys(local.projects))
    error_message = "every registered site has its bucket and roles"
  }

  assert {
    condition     = toset(keys(module.bot_ci_plan)) == toset(keys(local.bots)) && toset(keys(module.bot_ci_apply)) == toset(keys(local.bots))
    error_message = "every registered bot and research project has its roles"
  }

  assert {
    condition     = toset(keys(module.databricks_ci_plan)) == toset(keys(local.databricks_projects))
    error_message = "every registered Databricks project has its roles"
  }

  assert {
    condition     = module.bot_ci_plan["braveheart-trainer"].role_name == "jaws-braveheart-trainer-ci-plan" && local.bot_datasets["braveheart-trainer"] == ["jaws-braveheart-trainer-nets"]
    error_message = "a project's roles carry the jaws prefix and manage its jaws- buckets"
  }

  assert {
    condition     = local.hosts_task_runners && length(module.spot_service_linked_role) == 1 && jsonencode(local.infra_ci.foundation.service_linked_role_services) == jsonencode(["spot.amazonaws.com"])
    error_message = "projects run tasks here, so the foundation owns the EC2 Spot service-linked role and the infra roles may manage it"
  }
}

# The state bucket's policy is hardened: it denies every state prefix it does
# not list, whatever a role's IAM allows (state.tf). So each CI role's state
# must be listed there with that role, or the role fails at `terraform init`.
run "the_reconcile_reaches_its_state" {
  command = plan

  override_module {
    target = module.data_access_ci_plan
    outputs = {
      role_arn = "arn:aws:iam::222222222222:role/jaws-data-access-ci-plan"
    }
  }

  override_module {
    target = module.data_access_ci_apply
    outputs = {
      role_arn = "arn:aws:iam::222222222222:role/jaws-data-access-ci-apply"
    }
  }

  assert {
    condition = jsonencode(try(local.state_prefix_access[local.data_access_ci.tfstate.key], null)) == jsonencode({
      read  = ["arn:aws:iam::222222222222:role/jaws-data-access-ci-plan"]
      write = ["arn:aws:iam::222222222222:role/jaws-data-access-ci-apply"]
    })
    error_message = "the state bucket policy must list data-access's key, readable by its plan role and writable by its apply role, or both roles are denied their own state"
  }
}

run "databricks_is_built_and_onboards_the_registry" {
  command = plan

  assert {
    condition     = length(module.databricks_metastore) == 1 && length(module.databricks_audit_logs) == 1 && length(module.databricks_shared_host) == 1
    error_message = "the metastore, the audit log delivery and the shared host are the foundation's"
  }

  assert {
    condition     = local.databricks.metastore_name == "jaws-us-east-1" && local.databricks.audit_bucket == "jaws-databricks-audit-logs" && local.databricks_host_name == "jaws-shared" && local.databricks_log_delivery_role_name == "jaws-databricks-log-delivery"
    error_message = "the metastore, audit bucket, shared host and log delivery role carry the jaws names"
  }

  assert {
    condition     = module.databricks_metastore[0].admin_group_name == "jaws-metastore-admins"
    error_message = "the metastore admin group is jaws-metastore-admins, the name the CLI gives the data-access stack (access.py metastore_admin_group)"
  }

  assert {
    condition     = local.databricks_secret_parameter_arn == "arn:aws:ssm:us-east-1:222222222222:parameter/jaws/databricks/client-secret" && local.databricks_events_arn_prefix == "arn:aws:s3:::jaws-databricks-audit-logs/events/"
    error_message = "the roles name the account's Databricks secret and audit bucket"
  }

  assert {
    condition     = contains(keys(local.onboarded_datasets), "braveheart-selfplay-positions") && contains(keys(module.producer_catalog), "braveheart_selfplay")
    error_message = "with the host recorded, the registry's datasets are onboarded under their producers' catalogs"
  }

  assert {
    condition     = local.onboarded_datasets["braveheart-selfplay-positions"].platform_name == "jaws-ds-braveheart-selfplay-positions" && local.onboarded_datasets["braveheart-selfplay-positions"].bucket == "jaws-braveheart-selfplay-positions"
    error_message = "a dataset's platform role and the bucket it reads carry the jaws names"
  }
}

# The platform's repositories are Jaws-Platform/jaws alone, with no hub. Its own
# workflows' tokens name it, and only it. (Which roles trust them:
# tests/test_repository_trust.py.)
run "the_platform_repository_is_trusted_as_before" {
  command = plan

  assert {
    condition     = local.platform_trust.repository == "Jaws-Platform/jaws" && length(local.platform_trust.additional_repositories) == 0 && length(local.hub_trust) == 0
    error_message = "config/platform.yaml lists Jaws-Platform/jaws alone, and names no hub"
  }

  assert {
    condition     = module.context.tags["Repository"] == "Jaws-Platform/jaws"
    error_message = "the Repository tag is Jaws-Platform/jaws"
  }

  assert {
    condition = jsondecode(module.infra_ci_plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == [
      "repo:${local.platform_repository.repository}:pull_request",
      "repo:${split("/", local.platform_repository.repository)[0]}@${local.platform_repository.owner_id}/${split("/", local.platform_repository.repository)[1]}@${local.platform_repository.repository_id}:pull_request",
    ]
    error_message = "with one repository the plan role trusts its pull requests in both subject forms and nothing else: the trust policy jaws-ci 0.4.0 built"
  }

  assert {
    condition     = alltrue([for key, role in module.site_ci_plan : length(jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]) == 2])
    error_message = "without a hub a site's plan role trusts only its own repository"
  }
}

run "a_second_repository_is_trusted_alongside_the_first" {
  command = plan

  variables {
    config_path = "tests/fixtures/two-repositories.yaml"
  }

  assert {
    condition = jsondecode(module.infra_ci_plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == [
      "repo:${local.platform_repository.repository}:pull_request",
      "repo:Example-Hub/platform:pull_request",
      "repo:${split("/", local.platform_repository.repository)[0]}@${local.platform_repository.owner_id}/${split("/", local.platform_repository.repository)[1]}@${local.platform_repository.repository_id}:pull_request",
      "repo:Example-Hub@10000099/platform@20000099:pull_request",
    ]
    error_message = "the plan role trusts both repositories' pull requests, the classic subjects (first, second) before the immutable ones"
  }

  assert {
    condition = alltrue([
      for policy in concat(
        [module.data_access_ci_plan.assume_role_policy],
        [for role in module.monitoring_ci_plan : role.assume_role_policy],
        [for key, role in module.bot_ci_plan : role.assume_role_policy],
        [for key, role in module.databricks_ci_plan : role.assume_role_policy],
      ) : contains(jsondecode(policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"], "repo:Example-Hub@10000099/platform@20000099:pull_request")
    ])
    error_message = "every plan role of the platform's own trusts the second repository's pull requests"
  }

  assert {
    condition = alltrue([
      for policy in concat(
        [module.infra_ci_apply.assume_role_policy],
        [module.data_access_ci_apply.assume_role_policy],
        [for role in module.monitoring_ci_apply : role.assume_role_policy],
        [for key, role in module.bot_ci_apply : role.assume_role_policy],
        [for key, role in module.databricks_ci_apply : role.assume_role_policy],
      ) : contains(jsondecode(policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"], "repo:Example-Hub@10000099/platform@20000099:environment:prod")
    ])
    error_message = "every apply role of the platform's own trusts the second repository's prod environment"
  }

  assert {
    condition     = module.context.tags["Repository"] == local.platform_repository.repository && module.context.tags["Repository"] == "Jaws-Platform/jaws"
    error_message = "the Repository tag names the first repository"
  }

  assert {
    condition     = alltrue([for key, role in module.site_ci_plan : length(jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]) == 2])
    error_message = "without a hub a site's plan role still trusts only its own repository"
  }
}

run "the_hub_plans_every_site" {
  command = plan

  variables {
    config_path = "tests/fixtures/hub.yaml"
  }

  override_module {
    target = module.hub_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:222222222222:repository/jaws-platform"
    }
  }

  assert {
    condition = alltrue([
      for key, role in module.site_ci_plan :
      length(jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]) == 4 && contains(jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"], "repo:Example-Hub@10000099/platform@20000099:pull_request")
    ])
    error_message = "with a hub each site's plan role trusts the hub's pull requests too"
  }

  assert {
    condition     = alltrue([for key, role in module.site_ci_apply : length(jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]) == 2])
    error_message = "a site's apply role still trusts only its own repository"
  }
}

run "refuses_a_hub_it_does_not_trust" {
  command = plan

  variables {
    config_path = "tests/fixtures/hub-not-trusted.yaml"
  }

  override_module {
    target = module.hub_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:222222222222:repository/jaws-platform"
    }
  }

  expect_failures = [data.aws_iam_openid_connect_provider.github]
}

run "no_hub_image_without_a_hub" {
  command = plan

  assert {
    condition     = length(module.hub_image) == 0 && local.hub_image_repository_arn == null
    error_message = "without a hub nothing creates the hub image's repository"
  }

  assert {
    condition     = !contains(keys(module.infra_ci_plan.policy_arns), "ecr/pull")
    error_message = "without a hub the infra plan role pulls nothing"
  }

  assert {
    condition     = toset(keys(module.infra_ci_apply.policy_arns)) == toset(["tfstate/write", "foundation/read", "foundation/manage", "ecr/push", "databricks/read"])
    error_message = "without a hub the infra apply role's policies are today's five"
  }

  assert {
    condition     = alltrue([for key, role in module.site_ci_plan : toset(keys(role.policy_arns)) == toset(["tfstate/read", "static-site/read", "ecr/pull"])])
    error_message = "without a hub a site's plan role keeps today's three policies"
  }
}

run "a_hub_gets_its_image_repository" {
  command = plan

  variables {
    config_path = "tests/fixtures/hub.yaml"
  }

  override_module {
    target = module.hub_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:222222222222:repository/jaws-platform"
    }
  }

  assert {
    condition     = length(module.hub_image) == 1 && local.hub_image_repository_arn == "arn:aws:ecr:us-east-1:${local.account_id}:repository/jaws-platform"
    error_message = "the hub's image repository is created in the platform account, never the management account"
  }

  assert {
    condition = alltrue([
      for keys in concat(
        [keys(module.infra_ci_plan.policy_arns), keys(module.infra_ci_apply.policy_arns)],
        [keys(module.data_access_ci_plan.policy_arns), keys(module.data_access_ci_apply.policy_arns)],
        [for r in module.monitoring_ci_plan : keys(r.policy_arns)],
        [for r in module.monitoring_ci_apply : keys(r.policy_arns)],
        [for k, r in module.bot_ci_plan : keys(r.policy_arns)],
        [for k, r in module.bot_ci_apply : keys(r.policy_arns)],
        [for k, r in module.bot_ci_release : keys(r.policy_arns)],
        [for k, r in module.bot_ci_task : keys(r.policy_arns)],
        [for k, r in module.databricks_ci_plan : keys(r.policy_arns)],
        [for k, r in module.databricks_ci_apply : keys(r.policy_arns)],
        [for k, r in module.site_ci_plan : keys(r.policy_arns)],
        [for k, r in module.site_ci_preview : keys(r.policy_arns)],
        [for k, r in module.site_ci_apply : keys(r.policy_arns)],
      ) : contains(keys, "ecr/pull")
    ])
    error_message = "every CI role pulls the hub image"
  }

  assert {
    condition     = alltrue([for k, r in module.site_ci_plan : contains(keys(r.policy_arns), "ecr/pull-2")]) && alltrue([for k, r in module.site_ci_preview : contains(keys(r.policy_arns), "ecr/pull-2")]) && alltrue([for k, r in module.site_ci_apply : contains(keys(r.policy_arns), "ecr/pull-2")])
    error_message = "every site role pulls the hub image through its second ECR policy"
  }

  assert {
    condition     = contains(keys(module.infra_ci_apply.policy_arns), "ecr/push-2") && contains(keys(module.infra_ci_apply.policy_arns), "ecr/pull-2")
    error_message = "the infra apply role pushes and pulls the hub image"
  }
}

run "a_hub_keeps_every_role_within_ten_policies" {
  command = plan

  variables {
    config_path = "tests/fixtures/hub.yaml"
  }

  override_module {
    target = module.hub_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:222222222222:repository/jaws-platform"
    }
  }

  # IAM's default quota: 10 managed policies attached to a role. The infra apply
  # role goes from five to eight with a hub; every other role gains exactly one (ecr/pull, or ecr/pull-2 on a site role).
  assert {
    condition = alltrue([
      for keys in concat(
        [keys(module.infra_ci_plan.policy_arns), keys(module.infra_ci_apply.policy_arns)],
        [keys(module.data_access_ci_plan.policy_arns), keys(module.data_access_ci_apply.policy_arns)],
        [for r in module.monitoring_ci_plan : keys(r.policy_arns)],
        [for r in module.monitoring_ci_apply : keys(r.policy_arns)],
        [for k, r in module.bot_ci_plan : keys(r.policy_arns)],
        [for k, r in module.bot_ci_apply : keys(r.policy_arns)],
        [for k, r in module.bot_ci_release : keys(r.policy_arns)],
        [for k, r in module.bot_ci_task : keys(r.policy_arns)],
        [for k, r in module.databricks_ci_plan : keys(r.policy_arns)],
        [for k, r in module.databricks_ci_apply : keys(r.policy_arns)],
        [for k, r in module.site_ci_plan : keys(r.policy_arns)],
        [for k, r in module.site_ci_preview : keys(r.policy_arns)],
        [for k, r in module.site_ci_apply : keys(r.policy_arns)],
      ) : length(keys) <= 10
    ])
    error_message = "a role may attach at most 10 managed policies (IAM's default quota)"
  }
}

run "refuses_a_hub_image_outside_the_name_root" {
  command = plan

  variables {
    config_path = "tests/fixtures/hub-image-outside-the-name-root.yaml"
  }

  override_module {
    target = module.hub_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:222222222222:repository/platform"
    }
  }

  expect_failures = [data.aws_iam_openid_connect_provider.github]
}

run "refuses_a_hub_image_named_like_the_cli_image" {
  command = plan

  variables {
    config_path = "tests/fixtures/hub-image-is-the-cli-image.yaml"
  }

  override_module {
    target = module.hub_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:222222222222:repository/jaws-cli"
    }
  }

  expect_failures = [data.aws_iam_openid_connect_provider.github]
}

run "refuses_a_hub_image_named_like_a_project_repository" {
  command = plan

  variables {
    config_path = "tests/fixtures/hub-image-is-a-project-repository.yaml"
  }

  override_module {
    target = module.hub_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:222222222222:repository/jaws-braveheart-bot"
    }
  }

  expect_failures = [data.aws_iam_openid_connect_provider.github]
}

run "takes_its_identity_from_the_configuration" {
  command = plan

  # context.managed_by is a value no code spells.
  variables {
    config_path = "tests/fixtures/relabelled.yaml"
  }

  assert {
    condition     = module.context.tags["ManagedBy"] == "jaws-relabelled" && module.context.tags["Organization"] == "Example-Platform"
    error_message = "the ManagedBy tag is config/tool.yaml's context.managed_by, as the CLI stamps it on every stack it renders"
  }

  assert {
    condition     = module.context.tags["Repository"] == "Example-Org/platform" && module.context.tags["Owner"] == "example-owner"
    error_message = "the Repository tag is the first of platform.repositories, and Owner is context.owner"
  }

  assert {
    condition     = local.zone_name == "example.com" && local.zone_comment == "jaws: zone owned by Example-Org/platform; records owned by project repos"
    error_message = "the zone is dns.zone, and its comment names the platform's own repository"
  }

  assert {
    condition     = jsonencode(local.txt_records) == jsonencode({ "_example-challenge" = ["example-token"] })
    error_message = "the zone's own TXT records are dns.txt_records"
  }
}

run "an_account_without_task_runners_has_no_spot_role" {
  command = plan

  variables {
    config_path = "tests/fixtures/no-task-runners.yaml"
  }

  assert {
    condition     = !local.hosts_task_runners && length(module.spot_service_linked_role) == 0 && length(local.infra_ci.foundation.service_linked_role_services) == 0
    error_message = "with no task runner the foundation neither owns nor grants anything on the EC2 Spot service-linked role"
  }
}

# The host is created by the first apply, and the tool configuration (config/) names its URL only
# afterwards: until then the check says so on every plan, and no dataset is
# onboarded, because their provider is configured from that URL.
run "databricks_starts_with_the_host" {
  command = plan

  variables {
    config_path = "tests/fixtures/awaiting-host.yaml"
  }

  expect_failures = [check.shared_host_url]

  assert {
    condition     = length(module.databricks_shared_host) == 1 && length(local.onboarded_datasets) == 0 && length(module.producer_catalog) == 0 && length(module.databricks_dataset) == 0
    error_message = "before the host's URL is recorded, the host exists and no dataset is onboarded"
  }
}

run "rejects_another_accounts_credentials" {
  command = plan

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111111111111"
    }
  }

  expect_failures = [data.aws_caller_identity.current]
}

run "rejects_an_admin_role_of_another_account" {
  command = plan

  variables {
    config_path = "tests/fixtures/foreign-admin.yaml"
  }

  expect_failures = [data.aws_caller_identity.current]
}

# --------------------------------------------------- the monitoring platform
# config/monitoring.yaml: the billing bucket, the Databricks billing job, and
# the monitoring stack's roles and state (monitoring.tf). The stack itself is
# monitoring/'s; the AWS export is the owner's billing-export/.

run "the_billing_bucket_takes_the_organizations_export" {
  command = plan

  assert {
    condition     = length(module.billing_bucket) == 1 && module.billing_bucket[0].arn == "arn:aws:s3:::jaws-billing-222222222222"
    error_message = "the billing bucket is monitoring.cost.bucket, jaws-billing-222222222222"
  }

  assert {
    condition     = jsonencode(local.billing_bucket.aws_export_source_account_ids) == jsonencode(["111111111111"])
    error_message = "only the management account's exports (config/aws.yaml, type management) may deliver: the payer's export covers every account"
  }

  assert {
    condition     = local.billing_bucket.protect_raw == false
    error_message = "protect_raw is monitoring.cost.protect_raw: off until the first deliveries are checked"
  }
}

run "databricks_billing_is_exported_from_the_shared_host" {
  command = plan

  assert {
    condition     = length(module.databricks_billing_export) == 1
    error_message = "with monitoring.cost.databricks and Databricks enabled and recorded, the foundation runs the billing job on the shared host"
  }

  assert {
    condition     = module.databricks_billing_export[0].role_arn == "arn:aws:iam::222222222222:role/jaws-databricks-billing-export" && module.databricks_billing_export[0].prefix == "raw/provider=databricks/source=system-tables"
    error_message = "the job writes as jaws-databricks-billing-export, under the Databricks source prefix the normalizer reads"
  }
}

run "the_monitoring_roles_get_the_monitoring_and_compute_leaves" {
  command = plan

  assert {
    condition     = module.monitoring_ci_plan[0].role_name == "jaws-monitoring-ci-plan" && module.monitoring_ci_apply[0].role_name == "jaws-monitoring-ci-apply"
    error_message = "the stack's roles are jaws-monitoring-ci-plan and jaws-monitoring-ci-apply, for the jaws-monitoring stack"
  }

  assert {
    condition     = toset(keys(module.monitoring_ci_plan[0].policy_arns)) == toset(["tfstate/read", "monitoring/read", "compute/read"])
    error_message = "the plan role reads its state, the stack (monitoring/read) and its VPC (compute/read), nothing more"
  }

  assert {
    condition = toset(keys(module.monitoring_ci_apply[0].policy_arns)) == toset([
      "tfstate/write", "monitoring/read", "monitoring/node", "monitoring/config", "monitoring/functions", "monitoring/backup",
      "monitoring/off-hours-page", "compute/read", "compute/manage",
    ])
    error_message = "the apply role holds every monitoring/* leaf, and compute/* for the stack's own VPC (spec 6.5)"
  }

  # IAM's default quota: 10 managed policies attached to a role.
  assert {
    condition     = length(module.monitoring_ci_apply[0].policy_arns) <= 10 && length(module.monitoring_ci_plan[0].policy_arns) <= 10
    error_message = "a role may attach at most 10 managed policies (IAM's default quota)"
  }
}

run "the_monitoring_roles_reach_the_grafana_record_and_the_pages_validation_record" {
  command = plan

  override_module {
    target = module.zone
    outputs = {
      zone_id = "Z0000000000EXAMPLE"
      arn     = "arn:aws:route53:::hostedzone/Z0000000000EXAMPLE"
    }
  }

  assert {
    condition     = local.monitoring_ci.monitoring == { zone_id = "Z0000000000EXAMPLE", domain = "grafana.example.com" }
    error_message = "the roles' record is monitoring.domain in the foundation's zone, given together as the catalog requires"
  }

  assert {
    condition     = contains(keys(module.monitoring_ci_apply[0].policy_arns), "monitoring/off-hours-page") && !contains(keys(module.monitoring_ci_plan[0].policy_arns), "monitoring/off-hours-page")
    error_message = "the Grafana A record is the plan role's reach; the apply role adds the page's certificate validation CNAME through monitoring/off-hours-page"
  }
}

run "a_private_node_has_no_off_hours_page_permissions" {
  command = plan

  variables {
    config_path = "tests/fixtures/private-node.yaml"
  }

  assert {
    condition     = local.monitoring_ci.monitoring == null
    error_message = "without monitoring.domain the roles are given no record"
  }

  assert {
    condition     = length(module.monitoring_ci_apply) == 1 && !contains(keys(module.monitoring_ci_apply[0].policy_arns), "monitoring/off-hours-page")
    error_message = "a private node's apply role has no off-hours page policy: the catalog refuses it without the zone and domain"
  }
}

# The node's Caddy gets its certificate for monitoring.domain from Let's
# Encrypt, which honours the zone's apex CAA record (RFC 8659 climbs to it).
run "lets_encrypt_may_issue_the_monitoring_nodes_certificate" {
  command = plan

  assert {
    condition     = jsonencode(local.caa_issuers) == jsonencode(["amazon.com", "amazontrust.com", "awstrust.com", "amazonaws.com", "letsencrypt.org"])
    error_message = "with monitoring.domain the zone's CAA allows ACM's four Amazon issuers and letsencrypt.org, nothing else"
  }
}

run "the_monitoring_stack_reaches_its_state" {
  command = plan

  override_module {
    target = module.monitoring_ci_plan
    outputs = {
      role_arn = "arn:aws:iam::222222222222:role/jaws-monitoring-ci-plan"
    }
  }

  override_module {
    target = module.monitoring_ci_apply
    outputs = {
      role_arn = "arn:aws:iam::222222222222:role/jaws-monitoring-ci-apply"
    }
  }

  assert {
    condition = jsonencode(try(local.state_prefix_access["project=monitoring/env=prod/monitoring-prod.tfstate"], null)) == jsonencode({
      read  = ["arn:aws:iam::222222222222:role/jaws-monitoring-ci-plan"]
      write = ["arn:aws:iam::222222222222:role/jaws-monitoring-ci-apply"]
    })
    error_message = "the state bucket policy lists monitoring/'s key (monitoring/backend/prod.hcl), readable by its plan role and writable by its apply role"
  }

  assert {
    condition     = !anytrue([for key in keys(local.state_prefix_access) : strcontains(key, "billing-export")])
    error_message = "no state prefix names billing-export/, the owner's root"
  }
}

run "nothing_of_the_platform_without_its_section" {
  command = plan

  variables {
    config_path = "tests/fixtures/no-monitoring.yaml"
  }

  assert {
    condition     = length(module.billing_bucket) == 0 && length(module.databricks_billing_export) == 0
    error_message = "without config/monitoring.yaml's monitoring section there is no billing bucket and no billing job"
  }

  assert {
    condition     = length(module.monitoring_ci_plan) == 0 && length(module.monitoring_ci_apply) == 0
    error_message = "without the section there are no monitoring roles"
  }

  assert {
    condition     = !anytrue([for key in keys(local.state_prefix_access) : startswith(key, "project=monitoring/")])
    error_message = "without the section no state prefix is the monitoring stack's"
  }

  assert {
    condition     = jsonencode(local.caa_issuers) == jsonencode(["amazon.com", "amazontrust.com", "awstrust.com", "amazonaws.com"])
    error_message = "without the section (no node, no monitoring.domain) the zone's CAA allows only ACM's four Amazon issuers"
  }
}

run "databricks_billing_waits_for_the_host" {
  command = plan

  variables {
    config_path = "tests/fixtures/awaiting-host.yaml"
  }

  expect_failures = [check.shared_host_url]

  assert {
    condition     = length(module.databricks_billing_export) == 0 && length(module.billing_bucket) == 1
    error_message = "the billing job is created through the shared host, so it waits for its URL as the datasets do; the bucket does not"
  }
}

# `task run` and `task sweep` write each run's records to the billing bucket
# (jaws.run_records), with the project's task role: task/records lets it put
# objects under its own project's prefix and nothing else in the bucket.
run "each_task_role_writes_only_its_own_run_records" {
  command = plan

  assert {
    condition     = length(module.bot_ci_task) > 0 && alltrue([for key, role in module.bot_ci_task : toset(keys(role.policy_arns)) == toset(["task/launch", "task/records"])])
    error_message = "every task role launches its tasks and writes their records, nothing more"
  }

  assert {
    condition     = toset(keys(local.task_records)) == toset(keys(module.bot_ci_task))
    error_message = "every task role has its records prefix"
  }

  assert {
    condition = local.task_records["braveheart-trainer"] == {
      bucket = "jaws-billing-222222222222"
      prefix = "raw/provider=jaws/source=task-runs/project=braveheart-trainer"
    }
    error_message = "a project's task role writes only under raw/provider=jaws/source=task-runs/project=<project>/ in the billing bucket"
  }
}

run "no_task_records_without_the_billing_bucket" {
  command = plan

  variables {
    config_path = "tests/fixtures/no-monitoring.yaml"
  }

  assert {
    condition     = length(local.task_records) == 0 && alltrue([for key, role in module.bot_ci_task : toset(keys(role.policy_arns)) == toset(["task/launch"])])
    error_message = "without the billing bucket the task roles only launch"
  }
}

run "reads_its_configuration_and_datasets_from_the_repository_outside_the_image" {
  command = plan

  variables {
    config_path   = null
    datasets_path = null
  }

  # The one run that depends on the owner's configuration: the default path is the repository's
  # own config/, so the plan fails on the mocked neutral credentials and the owner's recorded
  # host (the asserts below are still evaluated). Plan 07 replaces it when config/ leaves the
  # repository.
  expect_failures = [data.aws_caller_identity.current, check.shared_host_url]

  # path.module is "." under terraform test, and dirname() cleans "./.." to "..".
  assert {
    condition     = !local.in_image && local.config_path == "./../config" && local.datasets_path == "../datasets"
    error_message = "without /etc/jaws/config the stack reads config/ and the datasets/ beside it, at the repository root, as the CLI reads ./config"
  }
}

run "the_datasets_are_beside_a_configuration_given_elsewhere" {
  command = plan

  variables {
    config_path   = "tests/fixtures/awaiting-host.yaml"
    datasets_path = null
  }

  # No dataset is onboarded before the host's URL is recorded, so the missing registry stops nothing.
  expect_failures = [check.shared_host_url]

  assert {
    condition     = local.datasets_path == "tests/fixtures/datasets"
    error_message = "config_path is where a caller's JAWS_CONFIG points, and the registry is the datasets/ beside it (jaws.access.infra_root)"
  }
}

run "a_configuration_directory_may_end_in_a_slash" {
  command = plan

  variables {
    config_path   = "../tests/fixtures/platform/"
    datasets_path = null
  }

  assert {
    condition     = local.datasets_path == "../tests/fixtures/datasets"
    error_message = "a trailing slash on config_path must not make the registry the config directory itself"
  }
}

run "stops_without_the_datasets_registry" {
  command = plan

  variables {
    datasets_path = "tests/fixtures/no-datasets"
  }

  expect_failures = [data.aws_caller_identity.current]
}
