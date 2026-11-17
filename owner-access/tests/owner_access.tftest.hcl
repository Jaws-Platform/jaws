# Plans the stack against a mocked AWS provider: no credentials, no AWS calls.
# Run from owner-access/: terraform init -backend=false && terraform test

mock_provider "aws" {
  override_during = plan

  mock_data "aws_ssoadmin_instances" {
    defaults = {
      arns               = ["arn:aws:sso:::instance/ssoins-0123456789abcdef"]
      identity_store_ids = ["d-0123456789"]
    }
  }

  mock_data "aws_organizations_organization" {
    defaults = {
      master_account_id = "650503560686"
    }
  }

  mock_data "aws_iam_roles" {
    defaults = {
      arns = ["arn:aws:iam::650503560686:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_0123456789abcdef"]
    }
  }

  mock_resource "aws_identitystore_user" {
    defaults = {
      user_id = "90676d2e5d-11111111-2222-3333-4444-555555555555"
    }
  }

  mock_resource "aws_ssoadmin_permission_set" {
    defaults = {
      arn = "arn:aws:sso:::permissionSet/ssoins-0123456789abcdef/ps-0123456789abcdef"
    }
  }
}

run "owner_gets_administrator_access_for_one_hour" {
  command = plan

  assert {
    condition     = module.owner_admin.permission_set_name == "AdministratorAccess"
    error_message = "the owner's permission set must be AdministratorAccess"
  }

  assert {
    condition     = module.owner_admin.session_duration == "PT1H"
    error_message = "credentials must last one hour"
  }

  assert {
    condition     = module.owner_admin.user_name == "jwallace145"
    error_message = "the Identity Center user name must be context.owner from config.yaml"
  }
}

run "outputs_render_the_cli_profile" {
  command = plan

  assert {
    condition     = output.access_portal_url == "https://d-0123456789.awsapps.com/start"
    error_message = "the access portal URL is the identity store's default awsapps.com URL"
  }

  assert {
    condition = alltrue([
      strcontains(output.aws_config, "[sso-session jwall-engineering]"),
      strcontains(output.aws_config, "sso_start_url = https://d-0123456789.awsapps.com/start"),
      strcontains(output.aws_config, "[profile jwall-admin]"),
      strcontains(output.aws_config, "sso_account_id = 650503560686"),
      strcontains(output.aws_config, "sso_role_name = AdministratorAccess"),
    ])
    error_message = "aws_config must render the jwall-admin profile for this account and permission set"
  }
}

# Everything is moving to the production account, so the owner needs the same
# admin access there. Nothing is being built in the development account.
run "the_owner_has_the_same_access_in_production" {
  command = plan

  assert {
    condition     = jsonencode(module.owner_admin.account_ids) == jsonencode(["650503560686", "570327089884"])
    error_message = "the owner must have AdministratorAccess in the management account and in production (570327089884), and nowhere else"
  }

  assert {
    condition     = !contains(module.owner_admin.account_ids, "859674017655")
    error_message = "the development account gets no assignment: nothing is built there"
  }

  assert {
    condition = alltrue([
      strcontains(output.aws_config, "[profile jaws-prod]"),
      strcontains(output.aws_config, "sso_account_id = 570327089884"),
      strcontains(output.aws_config, "[profile jwall-admin]"),
      strcontains(output.aws_config, "sso_account_id = 650503560686"),
    ])
    error_message = "aws_config must render a jaws-prod profile for the production account beside the jwall-admin profile"
  }

  assert {
    condition     = length(regexall("sso_session = jwall-engineering", output.aws_config)) == 2
    error_message = "both profiles sign in through the one Identity Center session"
  }
}

run "refuses_without_an_identity_center_instance" {
  command = plan

  override_data {
    target = data.aws_ssoadmin_instances.this
    values = {
      arns               = []
      identity_store_ids = []
    }
  }

  expect_failures = [data.aws_ssoadmin_instances.this]
}

run "refuses_unless_this_is_the_management_account" {
  command = plan

  override_data {
    target = data.aws_organizations_organization.this
    values = {
      master_account_id = "111122223333"
    }
  }

  expect_failures = [data.aws_organizations_organization.this]
}
