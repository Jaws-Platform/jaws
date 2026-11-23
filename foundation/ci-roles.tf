# This repository's own CI roles, assumed by GitHub Actions through OIDC.
#
#   jaws-infra-ci-plan   trusted for pull_request      tfstate/read, foundation/read, databricks/read
#   jaws-infra-ci-apply  trusted for environment:prod  tfstate/write, foundation/read, foundation/manage, ecr/push,
#                                                                   databricks/read
#
# databricks/read lets both roles read the Databricks client secret, which
# the foundation's Databricks resources (databricks.tf) authenticate with.
# It does not wait for databricks.enabled: the plan of the pull request that
# flips it to true must already be able to read the secret.
#
# Each role gets its permissions as managed policies from the library's
# ci-policies catalog, built for this stack. The plan role only accepts read
# policies. The apply role is the highest-privilege identity in the setup:
# foundation/manage restricts its IAM permissions to roles and policies named
# jaws-* and allow-lists the managed policies it may attach, so it
# cannot attach an AWS-managed policy such as AdministratorAccess. It can still
# edit jaws-* roles and policies, itself included, so the prod
# environment must stay protected. The full justification is in the
# ci-policies README; a summary is in README.md.

locals {
  infra_ci = {
    # Short role-name segment (jaws-infra-ci-plan/apply).
    # Deliberately not local.context.project, which is the Project tag value;
    # changing this renames and replaces the roles.
    project = "infra"

    tfstate = {
      bucket_arn = module.state_bucket.arn
      key        = local.state_key
    }

    # service_linked_role_services: the plan role may read, and the apply role
    # create and tag (never delete), the account's EC2 Spot service-linked role,
    # which the foundation owns in every account with a task runner. Granted one
    # release before the role is managed, so that release's plans can already
    # read it.
    foundation = {
      state_bucket_arn             = module.state_bucket.arn
      hosted_zone_arn              = module.zone.arn
      service_linked_role_services = local.hosts_task_runners ? ["spot.amazonaws.com"] : []
    }

    # The infra CLI image this repo publishes on release.
    ecr = {
      repository_arns = local.image_repository_arns
    }

    # databricks/read: the secret, and this stack's events under project=infra/
    # (the literal is local.infra_ci.project, which cannot be referenced here).
    databricks = {
      secret_parameter_arn = local.databricks_secret_parameter_arn
      events_object_arn    = "${local.databricks_events_arn_prefix}project=infra/*"
    }
  }
}

module "infra_ci_plan" {
  source  = "Jaws-Platform/jaws-ci/aws//modules/ci-plan-role"
  version = "0.6.0"

  project                 = local.infra_ci.project
  name_root               = local.context.name_root
  repository              = local.platform_trust.repository
  owner_id                = local.platform_trust.owner_id
  repository_id           = local.platform_trust.repository_id
  additional_repositories = local.platform_trust.additional_repositories
  oidc_provider_arn       = data.aws_iam_openid_connect_provider.github.arn

  policies = concat(["tfstate/read", "foundation/read", "databricks/read"], local.hub_image_pull)

  policy_inputs = {
    tfstate    = local.infra_ci.tfstate
    foundation = local.infra_ci.foundation
    databricks = local.infra_ci.databricks
    ecr        = local.hub_image_ecr
  }
}

module "infra_ci_apply" {
  source  = "Jaws-Platform/jaws-ci/aws//modules/ci-apply-role"
  version = "0.6.0"

  project                 = local.infra_ci.project
  name_root               = local.context.name_root
  repository              = local.platform_trust.repository
  owner_id                = local.platform_trust.owner_id
  repository_id           = local.platform_trust.repository_id
  additional_repositories = local.platform_trust.additional_repositories
  oidc_provider_arn       = data.aws_iam_openid_connect_provider.github.arn
  environment             = "prod"

  policies = concat(["tfstate/write", "foundation/read", "foundation/manage", "ecr/push", "databricks/read"], local.hub_image_pull)

  policy_inputs = {
    tfstate    = local.infra_ci.tfstate
    foundation = local.infra_ci.foundation
    ecr        = local.infra_ci.ecr
    databricks = local.infra_ci.databricks
  }
}

# The reconcile's roles (data-access/, .github/workflows/data-access.yml):
#
#   jaws-data-access-ci-plan   trusted for pull_request      tfstate/read, databricks/read
#   jaws-data-access-ci-apply  trusted for environment:prod  tfstate/write, databricks/read
#
# The stack only binds and grants in Databricks, through the service principal
# whose secret databricks/read reads; neither role has any other AWS
# permission, and only its own state key. The key follows config/terraform.yaml
# state.key_template, as every stack's does.
locals {
  data_access_ci = {
    project = "data-access"

    tfstate = {
      bucket_arn = module.state_bucket.arn
      key        = replace(replace(local.tool_config.state.key_template, "{project}", "data-access"), "{environment}", "prod")
    }

    # The literal is local.data_access_ci.project, which cannot be referenced here.
    databricks = {
      secret_parameter_arn = local.databricks_secret_parameter_arn
      events_object_arn    = "${local.databricks_events_arn_prefix}project=data-access/*"
    }
  }
}

module "data_access_ci_plan" {
  source  = "Jaws-Platform/jaws-ci/aws//modules/ci-plan-role"
  version = "0.6.0"

  project                 = local.data_access_ci.project
  name_root               = local.context.name_root
  repository              = local.platform_trust.repository
  owner_id                = local.platform_trust.owner_id
  repository_id           = local.platform_trust.repository_id
  additional_repositories = local.platform_trust.additional_repositories
  oidc_provider_arn       = data.aws_iam_openid_connect_provider.github.arn

  policies = concat(["tfstate/read", "databricks/read"], local.hub_image_pull)

  policy_inputs = {
    tfstate    = local.data_access_ci.tfstate
    databricks = local.data_access_ci.databricks
    ecr        = local.hub_image_ecr
  }
}

module "data_access_ci_apply" {
  source  = "Jaws-Platform/jaws-ci/aws//modules/ci-apply-role"
  version = "0.6.0"

  project                 = local.data_access_ci.project
  name_root               = local.context.name_root
  repository              = local.platform_trust.repository
  owner_id                = local.platform_trust.owner_id
  repository_id           = local.platform_trust.repository_id
  additional_repositories = local.platform_trust.additional_repositories
  oidc_provider_arn       = data.aws_iam_openid_connect_provider.github.arn
  environment             = "prod"

  policies = concat(["tfstate/write", "databricks/read"], local.hub_image_pull)

  policy_inputs = {
    tfstate    = local.data_access_ci.tfstate
    databricks = local.data_access_ci.databricks
    ecr        = local.hub_image_ecr
  }
}
