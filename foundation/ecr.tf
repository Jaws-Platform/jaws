# The private ECR repository that holds the jaws CLI image.
# Every site's CI roles pull it (ecr/pull); this repo's apply role pushes a
# tagged image on each release (ecr/push). Name and lifecycle come from
# config.yaml, the tool's configuration, so the CLI and the repository that
# holds it agree.

locals {
  # Built from the configured name rather than module.sites_image.arn so the
  # roles' ECR policies do not depend on the repository. That lets the
  # repository depend on the apply role below, which orders its creation after
  # the foundation/manage update that grants ecr:CreateRepository on a fresh
  # account. A check below flags any drift from the module's own ARN.
  sites_image_repository_arn = "arn:aws:ecr:${local.region}:${data.aws_caller_identity.current.account_id}:repository/${local.account.ecr.repository}"
}

module "sites_image" {
  source  = "Jaws-Platform/jaws-lichess-bot/aws//modules/ecr-repository"
  version = "0.1.2"

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

# config.yaml names the account the workflows build role ARNs for; a plan
# against any other account is a mistake worth flagging.
