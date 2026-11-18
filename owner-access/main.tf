# The owner's admin access: one IAM Identity Center user with the
# AdministratorAccess permission set in this account. Short-lived console and
# CLI credentials from one passkey sign-in, instead of an IAM user's access key.
#
# Applied only by the owner, from their own shell, never by CI: no CI role has
# Identity Center permissions or can reach this stack's state. Runbook,
# console prerequisites and the emergency path: docs/owner-access.md.

locals {
  owner = {
    user_name   = local.context.owner # jwallace145, the AWS CLI session name
    given_name  = "Jimmy"
    family_name = "Wallace"
    email       = "jimmy.wallace145@gmail.com"
  }

  # Credentials (and console sessions) last an hour; the CLI and SDKs renew
  # them until the 12-hour Identity Center sign-in expires (a console setting).
  session_duration = "PT1H"
}

# The organization instance, enabled once in the console (docs/owner-access.md).
data "aws_ssoadmin_instances" "this" {
  lifecycle {
    postcondition {
      condition     = length(self.arns) == 1
      error_message = "IAM Identity Center is not enabled in us-east-1. Enable the organization instance in the console first: docs/owner-access.md#one-time-console-setup. Never use `aws sso-admin create-instance`."
    }
  }
}

# The instance must be an organization instance owned by this account, which
# is therefore the organization's management account.
data "aws_organizations_organization" "this" {
  lifecycle {
    postcondition {
      condition     = self.master_account_id == local.account_id
      error_message = "This account is not the management account of its organization, so its Identity Center instance cannot grant account access. See docs/owner-access.md#one-time-console-setup."
    }
  }
}

module "owner_admin" {
  source  = "jwallace145/jwall-engineering/aws//modules/identity-center-access"
  version = "0.28.0"

  instance_arn      = one(data.aws_ssoadmin_instances.this.arns)
  identity_store_id = one(data.aws_ssoadmin_instances.this.identity_store_ids)
  account_id        = data.aws_organizations_organization.this.master_account_id

  # The same permission set in the organization's production and development accounts.
  additional_account_ids = compact([local.production_account_id, local.development_account_id])

  user = local.owner

  permission_set_name = "AdministratorAccess"
  session_duration    = local.session_duration
}
