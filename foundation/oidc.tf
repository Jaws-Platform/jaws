# GitHub Actions OIDC identity provider.
#
# An account can hold only one IAM OIDC provider per URL. It is created by hand
# at bootstrap (README.md, "Bootstrap"); every stack in this account shares it
# and this one only reads it. Sharing is safe: the provider grants nothing by
# itself, and each role's trust policy restricts which repository/environment
# may assume it. Who owns the provider is an open question: see the TODO(owner)
# below.
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
}
