# The foundation of the account the tool configuration (config/) describes. The default runs plan
# the tool configuration (config/) as written; the others plan fixtures (tests/fixtures/*.yaml, kept
# equal to the tool configuration (config/) plus a few values by tests/test_foundation_fixtures.py).
# Mock providers: nothing is called.

mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "570327089884"
    }
  }

  mock_data "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::570327089884:oidc-provider/token.actions.githubusercontent.com"
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
    arn = "arn:aws:ecr:us-east-1:570327089884:repository/jaws-cli"
  }
}

override_module {
  target = module.databricks_shared_host
  outputs = {
    workspace_id  = 1111111111111111
    workspace_url = "https://dbc-287077d7-e617.cloud.databricks.com"
  }
}

override_module {
  target = module.data_access_ci_plan
  outputs = {
    role_arn = "arn:aws:iam::570327089884:role/jaws-data-access-ci-plan"
  }
}

override_module {
  target = module.data_access_ci_apply
  outputs = {
    role_arn = "arn:aws:iam::570327089884:role/jaws-data-access-ci-apply"
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
    uc_role_arn             = "arn:aws:iam::570327089884:role/jaws-dataset-catalogs"
  }
}

run "the_account_is_config_yamls" {
  command = plan

  assert {
    condition     = local.account_id == "570327089884" && local.state_bucket_name == "jaws-terraform-state-570327089884"
    error_message = "the account is 570327089884, with the state bucket jaws-terraform-state-570327089884"
  }

  assert {
    condition     = module.infra_ci_plan.role_name == "jaws-infra-ci-plan" && module.infra_ci_apply.role_name == "jaws-infra-ci-apply"
    error_message = "the foundation's own roles are jaws-infra-ci-plan and jaws-infra-ci-apply"
  }

  assert {
    condition     = local.sites_image_repository_arn == "arn:aws:ecr:us-east-1:570327089884:repository/jaws-cli"
    error_message = "the tool's image repository is jaws-cli"
  }

  assert {
    condition = jsonencode(module.context.tags) == jsonencode({
      Organization = "Jaws-Platform"
      Project      = "jaws"
      Environment  = "prod"
      Repository   = "Jaws-Platform/jaws"
      ManagedBy    = "JAWS"
      Owner        = "jwallace145"
    })
    error_message = "the foundation's tags are Organization=Jaws-Platform (this repository's GitHub owner), Project=jaws, ManagedBy=JAWS"
  }

  assert {
    condition     = local.context.name_root == "jaws" && module.context.name_prefix == "jaws-jaws-prod"
    error_message = "names keep the name root (context.name_root), whatever the Organization tag says"
  }

  assert {
    condition = length(local.bucket_admin_principal_arns) == 3 && slice(local.bucket_admin_principal_arns, 0, 2) == [
      "arn:aws:iam::570327089884:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_013589f39f92382a",
      "arn:aws:iam::570327089884:root",
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

  assert {
    condition = jsonencode(try(local.state_prefix_access[local.data_access_ci.tfstate.key], null)) == jsonencode({
      read  = ["arn:aws:iam::570327089884:role/jaws-data-access-ci-plan"]
      write = ["arn:aws:iam::570327089884:role/jaws-data-access-ci-apply"]
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
    condition     = local.databricks_secret_parameter_arn == "arn:aws:ssm:us-east-1:570327089884:parameter/jaws/databricks/client-secret" && local.databricks_events_arn_prefix == "arn:aws:s3:::jaws-databricks-audit-logs/events/"
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

# The repository is Jaws-Platform/jaws. Its own workflows' tokens name it, and
# only it. (Which roles take aliases: tests/test_repository_trust.py.)
run "the_repository_is_trusted_under_its_name_only" {
  command = plan

  assert {
    condition     = local.context.repository == "Jaws-Platform/jaws" && local.github.owner_id == 359185083
    error_message = "the repository is Jaws-Platform/jaws, owned by the Jaws-Platform organization (359185083)"
  }

  assert {
    condition     = length(local.context.repository_aliases) == 0 && length(local.context.repository_alias_owner_ids) == 0
    error_message = "no other name of the repository is trusted"
  }
}

run "takes_its_managed_by_from_the_configuration" {
  command = plan

  # context.managed_by is a value no code spells.
  variables {
    config_path = "tests/fixtures/relabelled.yaml"
  }

  assert {
    condition     = module.context.tags["ManagedBy"] == "jaws-relabelled" && module.context.tags["Organization"] == "Jaws-Platform"
    error_message = "the ManagedBy tag is config/tool.yaml's context.managed_by, as the CLI stamps it on every stack it renders"
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
      account_id = "650503560686"
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
    condition     = length(module.billing_bucket) == 1 && module.billing_bucket[0].arn == "arn:aws:s3:::jaws-billing-570327089884"
    error_message = "the billing bucket is monitoring.cost.bucket, jaws-billing-570327089884"
  }

  assert {
    condition     = jsonencode(local.billing_bucket.aws_export_source_account_ids) == jsonencode(["650503560686"])
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
    condition     = module.databricks_billing_export[0].role_arn == "arn:aws:iam::570327089884:role/jaws-databricks-billing-export" && module.databricks_billing_export[0].prefix == "raw/provider=databricks/source=system-tables"
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
      "compute/read", "compute/manage",
    ])
    error_message = "the apply role holds every monitoring/* leaf, and compute/* for the stack's own VPC (spec 6.5)"
  }

  # IAM's default quota: 10 managed policies attached to a role.
  assert {
    condition     = length(module.monitoring_ci_apply[0].policy_arns) <= 10 && length(module.monitoring_ci_plan[0].policy_arns) <= 10
    error_message = "a role may attach at most 10 managed policies (IAM's default quota)"
  }
}

run "the_monitoring_roles_may_change_only_the_grafana_record" {
  command = plan

  override_module {
    target = module.zone
    outputs = {
      zone_id = "Z0644006DW6W2HALU9BI"
      arn     = "arn:aws:route53:::hostedzone/Z0644006DW6W2HALU9BI"
    }
  }

  assert {
    condition     = local.monitoring_ci.monitoring == { zone_id = "Z0644006DW6W2HALU9BI", domain = "grafana.jwall.engineering" }
    error_message = "the roles' record is monitoring.domain in the foundation's zone, given together as the catalog requires"
  }
}

run "the_monitoring_stack_reaches_its_state" {
  command = plan

  override_module {
    target = module.monitoring_ci_plan
    outputs = {
      role_arn = "arn:aws:iam::570327089884:role/jaws-monitoring-ci-plan"
    }
  }

  override_module {
    target = module.monitoring_ci_apply
    outputs = {
      role_arn = "arn:aws:iam::570327089884:role/jaws-monitoring-ci-apply"
    }
  }

  assert {
    condition = jsonencode(try(local.state_prefix_access["project=monitoring/env=prod/monitoring-prod.tfstate"], null)) == jsonencode({
      read  = ["arn:aws:iam::570327089884:role/jaws-monitoring-ci-plan"]
      write = ["arn:aws:iam::570327089884:role/jaws-monitoring-ci-apply"]
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
