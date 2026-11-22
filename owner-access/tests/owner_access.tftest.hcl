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

# The state bucket's resources are adopted by `import` blocks (state.tf), and
# a mock provider cannot import, so each is overridden by address.
override_resource {
  target = aws_s3_bucket.state
  values = {
    id  = "jaws-owner-access-state-650503560686"
    arn = "arn:aws:s3:::jaws-owner-access-state-650503560686"
  }
}

override_resource {
  target = aws_s3_bucket_versioning.state
}

override_resource {
  target = aws_s3_bucket_server_side_encryption_configuration.state
}

override_resource {
  target = aws_s3_bucket_public_access_block.state
}

override_resource {
  target = aws_s3_bucket_ownership_controls.state
}

override_resource {
  target = aws_s3_bucket_policy.state
}

run "state_lives_in_its_own_management_account_bucket" {
  command = plan

  assert {
    condition     = aws_s3_bucket.state.bucket == "jaws-owner-access-state-650503560686"
    error_message = "the state bucket is jaws-owner-access-state-<management account ID>, matching backend/prod.hcl"
  }

  assert {
    condition     = aws_s3_bucket_versioning.state.versioning_configuration[0].status == "Enabled"
    error_message = "the state bucket must keep every prior state"
  }
}

# The state names every account the owner can reach, so its bucket denies
# everyone but the owner's admin role and root (issue #285).
run "state_bucket_denies_everyone_but_the_owner" {
  command = plan

  assert {
    condition     = [for st in jsondecode(aws_s3_bucket_policy.state.policy).Statement : st.Sid] == ["DenyInsecureTransport", "DenyAllButTheOwner"]
    error_message = "the state bucket policy is the TLS rule and the owner-only rule, in that order"
  }

  assert {
    condition     = alltrue([for st in jsondecode(aws_s3_bucket_policy.state.policy).Statement : st.Effect == "Deny" && st.Principal == "*"])
    error_message = "every statement is a deny for every principal: the policy bounds IAM and grants nothing"
  }

  assert {
    condition = jsondecode(aws_s3_bucket_policy.state.policy).Statement[1].Action == "s3:*" && jsondecode(aws_s3_bucket_policy.state.policy).Statement[1].Resource == [
      "arn:aws:s3:::jaws-owner-access-state-650503560686",
      "arn:aws:s3:::jaws-owner-access-state-650503560686/*",
    ]
    error_message = "the owner-only rule covers every action on the bucket and every object, its configuration and policy included"
  }

  assert {
    condition = jsondecode(aws_s3_bucket_policy.state.policy).Statement[1].Condition == {
      ArnNotLike = {
        "aws:PrincipalArn" = [
          "arn:aws:iam::650503560686:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_*",
          "arn:aws:iam::650503560686:root",
        ]
      }
    }
    error_message = "only the owner's AdministratorAccess role in this account (any generated suffix) and this account's root may reach the state; no CI role is listed"
  }
}

# The admin role is matched by name so a recreated permission set, whose role
# gets a new suffix, keeps access. The pattern must match the role Identity
# Center actually provisions, path included: the first ARN below is the
# management account's role as IAM lists it on 2026-11-21.
run "state_bucket_pattern_matches_the_provisioned_admin_role" {
  command = plan

  assert {
    condition = alltrue([
      for arn in [
        "arn:aws:iam::650503560686:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_22a17d3bc2bca2d3",
        "arn:aws:iam::650503560686:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_0123456789abcdef",
      ] : can(regex("^${replace(local.state_admin_principal_arns[0], "*", "[0-9a-f]+")}$", arn))
    ])
    error_message = "the admin pattern in the state bucket policy must match the role Identity Center provisions for the permission set, whatever its suffix"
  }

  assert {
    condition     = !can(regex("^${replace(local.state_admin_principal_arns[0], "*", "[0-9a-f]+")}$", "arn:aws:iam::650503560686:role/AWSReservedSSO_AdministratorAccess_0123456789abcdef"))
    error_message = "a role outside the path IAM reserves for Identity Center must not match the admin pattern"
  }

  assert {
    condition     = !can(regex("^${replace(local.state_admin_principal_arns[0], "*", "[0-9a-f]+")}$", "arn:aws:iam::570327089884:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_013589f39f92382a"))
    error_message = "the same permission set's role in another account must not match: the pattern is pinned to this account"
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

# Everything jaws builds is in the production account, so the owner needs the
# same admin access there. The development account is in config.yaml too:
# nothing is built there yet, but the owner can sign in to it (quota requests,
# the console).
run "the_owner_has_the_same_access_in_production_and_development" {
  command = plan

  assert {
    condition     = jsonencode(module.owner_admin.account_ids) == jsonencode(["650503560686", "570327089884", "859674017655"])
    error_message = "the owner must have AdministratorAccess in the management account, production (570327089884) and development (859674017655), and nowhere else"
  }

  assert {
    condition = alltrue([
      strcontains(output.aws_config, "[profile jwall-admin]"),
      strcontains(output.aws_config, "sso_account_id = 650503560686"),
      strcontains(output.aws_config, "[profile jaws-prod]"),
      strcontains(output.aws_config, "sso_account_id = 570327089884"),
      strcontains(output.aws_config, "[profile jaws-dev]"),
      strcontains(output.aws_config, "sso_account_id = 859674017655"),
    ])
    error_message = "aws_config must render the jwall-admin, jaws-prod and jaws-dev profiles"
  }

  assert {
    condition     = length(regexall("sso_session = jwall-engineering", output.aws_config)) == 3
    error_message = "all three profiles sign in through the one Identity Center session"
  }

  assert {
    condition     = length(regexall("(?m)^[ \\t]+\\S", output.aws_config)) == 0 && !strcontains(output.aws_config, "\n\n\n")
    error_message = "aws_config is pasted into ~/.aws/config, where an indented line continues the one before: no line may be indented, and blocks are one blank line apart"
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
