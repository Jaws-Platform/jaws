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
# their producer's catalog, and the dataset its schema and files volume.
run "the_positions_get_their_producer_catalog" {
  command = plan

  assert {
    condition     = jsonencode(keys(module.producer_catalog)) == jsonencode(["braveheart_selfplay"])
    error_message = "one producer catalog per producer with an onboarded dataset: braveheart_selfplay"
  }
}

# While the repository is renamed, the roles its own workflows assume trust both
# names (tests/test_repository_trust.py checks which modules get the alias).
run "the_repository_is_trusted_under_its_new_name_too" {
  command = plan

  assert {
    condition     = local.context.repository == "jwallace145/jwall-engineering-infra"
    error_message = "until the rename, the repository's own name is jwall-engineering-infra"
  }

  assert {
    condition     = jsonencode(local.context.repository_aliases) == jsonencode(["jwallace145/jaws"])
    error_message = "the roles must also trust jwallace145/jaws, the name the repository is about to take"
  }
}
