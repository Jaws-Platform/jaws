# The private ECR repository that holds the jaws CLI image.
# Every site's CI roles pull it (ecr/pull); this repo's apply role pushes a
# tagged image on each release (ecr/push). Name and lifecycle come from
# config/tool.yaml, the tool's configuration, so the CLI and the repository that
# holds it agree.
#
# With a hub (platform.hub in config/platform.yaml) a second private repository,
# named platform.hub.image, holds the hub's own image. Every CI role pulls it
# (ecr/pull) and this repo's apply role, which acts as the hub's release role,
# pushes it. jaws-ci's ECR policies take several repositories: each further one
# adds an ecr/pull-<n> or ecr/push-<n> policy, so with a hub the infra apply role
# holds eight managed policies (five, plus ecr/pull, ecr/pull-2 and ecr/push-2),
# every other role one more than today (ecr/pull, or ecr/pull-2 on a site role), none above IAM's limit of ten.

locals {
  # Built from the configured name rather than module.sites_image.arn so the
  # roles' ECR policies do not depend on the repository. That lets the
  # repository depend on the apply role below, which orders its creation after
  # the foundation/manage update that grants ecr:CreateRepository on a fresh
  # account. A check below flags any drift from the module's own ARN.
  sites_image_repository_arn = "arn:aws:ecr:${local.region}:${data.aws_caller_identity.current.account_id}:repository/${local.account.ecr.repository}"

  # The hub image's repository, in the platform account, built from its name for
  # the same reason. Null without a hub.
  hub_image_repository_arn = local.hub == null ? null : "arn:aws:ecr:${local.region}:${data.aws_caller_identity.current.account_id}:repository/${local.hub.image}"

  # What each CI role adds to its policies and its ecr input for the hub image.
  hub_image_pull = local.hub == null ? [] : ["ecr/pull"]
  hub_image_ecr  = local.hub == null ? null : { repository_arns = [local.hub_image_repository_arn] }

  # The repositories the infra apply role pushes and the site roles pull.
  image_repository_arns = concat([local.sites_image_repository_arn], local.hub == null ? [] : [local.hub_image_repository_arn])
}

module "sites_image" {
  source  = "Jaws-Platform/jaws-lichess-bot/aws//modules/ecr-repository"
  version = "0.1.4"

  name                       = local.account.ecr.repository
  keep_release_images        = local.account.ecr.keep_release_images
  expire_untagged_after_days = local.account.ecr.expire_untagged_after_days

  depends_on = [module.infra_ci_apply]
}

check "sites_image_repository_arn_matches" {
  assert {
    condition     = module.sites_image.arn == local.sites_image_repository_arn
    error_message = "local.sites_image_repository_arn differs from module.sites_image's arn; the roles' ECR policies would point at the wrong repository."
  }
}

module "hub_image" {
  count   = local.hub == null ? 0 : 1
  source  = "Jaws-Platform/jaws-lichess-bot/aws//modules/ecr-repository"
  version = "0.1.4"

  name = local.hub.image

  depends_on = [module.infra_ci_apply]
}

check "hub_image_repository_arn_matches" {
  assert {
    condition     = alltrue([for m in module.hub_image : m.arn == local.hub_image_repository_arn])
    error_message = "local.hub_image_repository_arn differs from module.hub_image's arn; the roles' ECR policies would point at the wrong repository."
  }
}

# config/aws.yaml names the account the workflows build role ARNs for; a plan
# against any other account is a mistake worth flagging.
