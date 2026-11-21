# Terraform state bucket shared by every jaws stack.
#
# Key convention: project=<project>/env=<env>/<project>-<env>.tfstate
# Locking uses the S3 native lockfile (<key>.tflock); there is no DynamoDB.
# The module hard-codes prevent_destroy.
#
# The bucket policy is hardened: each state prefix is reachable only by the CI
# roles listed for it, read-only roles may write only .tflock objects, and
# only the break-glass admins may touch anything else or change the bucket's
# configuration. Every statement is a deny, so this bounds other principals in
# the account (including ones with s3:* on *) without granting anything.

locals {
  state_bucket_name = local.account.state.bucket

  # This stack's own state, used by the CI role policies. Must match
  # backend/<account>.hcl, which cannot reference variables.
  state_key = "project=infra/env=prod/infra-prod.tfstate"

  # Break-glass principals exempt from the hardened bucket policies on the
  # state bucket and every site bucket. Being exempt grants nothing by itself.
  #
  # - The owner's Identity Center admin role (owner-access/), for the console
  #   and the CLI. Its exact ARN, path included, from
  #   `terraform -chdir=owner-access output -raw admin_role_arn`: a literal,
  #   because the CI roles cannot list IAM roles and an empty lookup would
  #   silently drop the owner. AWS generates the suffix, so a recreated
  #   permission set needs a new ARN here (use root until that release lands).
  # - The root user, for emergencies (docs/owner-access.md).
  # - The apply role, which applies these policies.
  bucket_admin_principal_arns = [
    local.account.aws.admin_role_arn,
    "arn:aws:iam::${local.account_id}:root",
    module.infra_ci_apply.role_arn,
  ]

  # State prefix -> who may read and write it. The infra and data-access
  # entries are those stacks' exact keys (which also match their .tflock);
  # each project gets its prefix. A role whose state is not listed here is
  # denied it, whatever its IAM allows (foundation/tests/state_access.tftest.hcl).
  state_prefix_access = merge(
    {
      (local.state_key) = {
        read  = [module.infra_ci_plan.role_arn]
        write = [module.infra_ci_apply.role_arn]
      }
    },
    {
      # The reconcile (data-access/, ci-roles.tf).
      (local.data_access_ci.tfstate.key) = {
        read  = [module.data_access_ci_plan.role_arn]
        write = [module.data_access_ci_apply.role_arn]
      }
    },
    {
      for key, project in local.projects : "project=${key}/" => {
        read  = [module.site_ci_plan[key].role_arn]
        write = [module.site_ci_apply[key].role_arn]
      }
    },
    {
      for key, bot in local.bots : "project=${key}/" => {
        read  = [module.bot_ci_plan[key].role_arn]
        write = [module.bot_ci_apply[key].role_arn]
      }
    },
    {
      # Both stacks of a Databricks project: its account and workspace keys.
      for key, project in local.databricks_projects : "project=${key}/" => {
        read  = [module.databricks_ci_plan[key].role_arn]
        write = [module.databricks_ci_apply[key].role_arn]
      }
    },
  )
}

module "state_bucket" {
  source  = "Jaws-Platform/jaws-foundation/aws//modules/tfstate-bucket"
  version = "0.1.2"

  name = local.state_bucket_name

  admin_principal_arns = local.bucket_admin_principal_arns
  prefix_access        = local.state_prefix_access
}
