# GitHub Actions OIDC identity provider.
#
# An account can hold only one IAM OIDC provider per URL. It is created outside
# this stack: by hand at bootstrap in a new account (README.md, "Bootstrap"); in
# this account by prog-strength-infra (see the TODO(owner) below). Every stack
# shares it and this one only reads it. Destroying the stack that owns it removes
# the provider every CI role trusts. Sharing is safe: the provider grants nothing
# by itself, and each role's trust policy restricts which repository/environment
# may assume it.
#
# TODO(owner): move ownership of the provider into this stack. Steps:
#   1. In prog-strength-infra, `terraform state rm` the provider and replace
#      it with a data source like the one below.
#   2. Here, replace the data source with
#        import { to = aws_iam_openid_connect_provider.github, id = <arn> }
#        resource "aws_iam_openid_connect_provider" "github" { url = ..., client_id_list = ["sts.amazonaws.com"] }
#      and give the apply role (foundation/manage in the library's ci-policies
#      catalog) permission to manage it.
#   3. Update README.md and docs/migration.md.

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  lifecycle {
    precondition {
      condition     = local.hub == null ? true : length(local.hub_trust) == 1
      error_message = "platform.hub.repository (config/platform.yaml) is not one of platform.repositories: the hub's pull requests are trusted under its entry's IDs, so list it there."
    }

    precondition {
      condition     = local.hub == null ? true : startswith(local.hub.image, "${local.context.name_root}-") && local.hub.image != local.account.ecr.repository && !contains([for k in keys(local.registry) : "${local.context.name_root}-${k}"], local.hub.image)
      error_message = "platform.hub.image (config/platform.yaml) must be named ${local.context.name_root}-*, the only repositories the foundation's apply role may create, and must be neither ecr.repository's (the CLI image keeps its own) nor a project's ${local.context.name_root}-<project> (its bot stack creates that, and its release role pushes to it)."
    }
  }
}
