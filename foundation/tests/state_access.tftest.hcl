# The state bucket's policy is hardened: it denies every state prefix it does
# not list, whatever a role's IAM allows (state.tf). So each CI role's state
# must be listed there with that role, or the role fails at `terraform init`.
# Mock providers: nothing is called. The shared host and the data-access roles
# are overridden with fixed outputs, so the roles' ARNs are known at plan.

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

# The management account's EC2 Spot service-linked role is imported
# (spot_service_linked_role.tf), and a mock provider cannot import: this stands
# in for the existing role wherever a run plans the import.
override_resource {
  target = module.spot_service_linked_role[0].aws_iam_service_linked_role.this
  values = {
    arn  = "arn:aws:iam::650503560686:role/aws-service-role/spot.amazonaws.com/AWSServiceRoleForEC2Spot"
    name = "AWSServiceRoleForEC2Spot"
  }
}

override_module {
  target = module.databricks_shared_host
  outputs = {
    workspace_id  = 7474644508802918
    workspace_url = "https://dbc-46322154-036c.cloud.databricks.com"
  }
}

override_module {
  target = module.data_access_ci_plan
  outputs = {
    role_arn = "arn:aws:iam::650503560686:role/jwall-engineering-data-access-ci-plan"
  }
}

override_module {
  target = module.data_access_ci_apply
  outputs = {
    role_arn = "arn:aws:iam::650503560686:role/jwall-engineering-data-access-ci-apply"
  }
}

# Two check blocks compare module outputs with ARNs this stack derives; mocked,
# those outputs are unknown at plan, so they are given the derived values.
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

# The catalogs' storage builds IAM policies from data sources a mock provider
# fills with random strings; its own module test covers it.
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

run "the_reconcile_reaches_its_state" {
  command = plan

  assert {
    condition = jsonencode(try(local.state_prefix_access[local.data_access_ci.tfstate.key], null)) == jsonencode({
      read  = ["arn:aws:iam::650503560686:role/jwall-engineering-data-access-ci-plan"]
      write = ["arn:aws:iam::650503560686:role/jwall-engineering-data-access-ci-apply"]
    })
    error_message = "the state bucket policy must list data-access's key, readable by its plan role and writable by its apply role, or both roles are denied their own state"
  }
}

# The onboarded positions (datasets/braveheart-selfplay/positions.yaml) get
# their producer's catalog where Databricks is: production, since 2026-11-19
# (accounts.tftest.hcl, databricks_in_production_onboards_once_the_host_is_recorded).
# The management account, as config.yaml is written, onboards nothing.
run "management_onboards_no_dataset" {
  command = plan

  assert {
    condition     = length(module.producer_catalog) == 0 && length(module.databricks_dataset) == 0
    error_message = "Databricks is enabled in production, so management has no producer catalog and no onboarded dataset"
  }
}

# The repository is Jaws-Platform/jaws. Its own workflows' tokens name it, and
# only it: the old names (jwallace145/jaws before the transfer of 2026-11-21,
# jwallace145/jwall-engineering-infra before the rename of 2026-11-17) are no
# longer trusted. (Which roles take aliases: tests/test_repository_trust.py.)
run "the_repository_is_trusted_under_its_name_only" {
  command = plan

  assert {
    condition     = local.context.repository == "Jaws-Platform/jaws"
    error_message = "the repository is Jaws-Platform/jaws"
  }

  assert {
    condition     = local.github.owner_id == 359185083
    error_message = "the owner ID in the immutable OIDC subject is the Jaws-Platform organization's"
  }

  assert {
    condition     = length(local.context.repository_aliases) == 0 && length(local.context.repository_alias_owner_ids) == 0
    error_message = "no other name of the repository is trusted: no token can name jwallace145/jaws since the transfer"
  }
}
