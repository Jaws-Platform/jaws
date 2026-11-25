# Jaws's release infrastructure: the ECR Public repository the image is
# published to, and the one role the release workflow assumes to push to it.
# Everything is spelled here, since this root reads nothing outside its folder.

locals {
  # The production account (the primary account in config/).
  account_id = "570327089884"

  # The repository whose release runs publish (the platform's first
  # repository in config/), by name and by the IDs GitHub puts in its OIDC subject.
  repository = {
    name          = "Jaws-Platform/jaws"
    owner_id      = "359185083"
    repository_id = "1420037633"
  }

  # The GitHub environment the publishing role trusts.
  environment = "publish"

  push_policy = {
    Version = "2012-10-17"
    Statement = [
      {
        # Neither action takes a resource, and neither grants anything by itself.
        Sid      = "LogInToEcrPublic"
        Effect   = "Allow"
        Action   = ["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"]
        Resource = "*"
      },
      {
        Sid    = "PushTheJawsImage"
        Effect = "Allow"
        Action = [
          "ecr-public:BatchCheckLayerAvailability",
          "ecr-public:InitiateLayerUpload",
          "ecr-public:UploadLayerPart",
          "ecr-public:CompleteLayerUpload",
          "ecr-public:PutImage",
        ]
        Resource = aws_ecrpublic_repository.jaws.arn
      },
      {
        # What the release's prune step calls, on this one repository.
        Sid      = "PruneTheJawsImage"
        Effect   = "Allow"
        Action   = ["ecr-public:DescribeImages", "ecr-public:BatchDeleteImage"]
        Resource = aws_ecrpublic_repository.jaws.arn
      },
    ]
  }
}

module "context" {
  source  = "Jaws-Platform/jaws-foundation/aws//modules/context"
  version = "0.2.0"

  organization = "Jaws-Platform"
  project      = "jaws"
  environment  = "prod"
  repository   = "Jaws-Platform/jaws"
  owner        = "Jaws-Platform"
  name_root    = "jaws"
  managed_by   = "JAWS"
}

# The credentials must be the production account's: the repository is created
# there, and the role must be too.
# tflint-ignore: terraform_unused_declarations # read for its condition alone
data "aws_caller_identity" "current" {
  lifecycle {
    postcondition {
      condition     = self.account_id == local.account_id
      error_message = "These credentials belong to account ${self.account_id}, but Jaws's release infrastructure lives in the production account, ${local.account_id}: apply it with the owner's admin profile there (release-infra/README.md)."
    }
  }
}

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

# Every release customers pin lives here: never destroyed or renamed.
resource "aws_ecrpublic_repository" "jaws" {
  repository_name = "jaws"

  catalog_data {
    description       = "Jaws: the infrastructure CLI and every stack it applies, as one image with no configuration of its own."
    usage_text        = "Pin a release by tag and digest in your platform's Dockerfile (FROM public.ecr.aws/<alias>/jaws:vX.Y.Z@sha256:...), and add your configuration, config/, at /etc/jaws/config/ and your datasets, datasets/, at /etc/jaws/datasets/."
    architectures     = ["x86-64"]
    operating_systems = ["Linux"]
  }

  lifecycle {
    prevent_destroy = true
  }
}

# Outside the name root (jaws-*): the foundation's apply role manages every
# jaws-* role, and this one is the owner's alone.
module "publish_role" {
  source  = "Jaws-Platform/jaws-ci/aws//modules/github-oidc-role"
  version = "0.6.0"

  name              = "release-infra-publish"
  description       = "Pushes the Jaws image to the ECR Public repository jaws and prunes its old versions, for Jaws-Platform/jaws release runs (environment publish)"
  repository        = local.repository.name
  owner_id          = local.repository.owner_id
  repository_id     = local.repository.repository_id
  subjects          = ["environment:${local.environment}"]
  oidc_provider_arn = data.aws_iam_openid_connect_provider.github.arn
  component         = "publishing"
  inline_policies   = { push = local.push_policy }
}
