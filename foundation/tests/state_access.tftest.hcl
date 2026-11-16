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
