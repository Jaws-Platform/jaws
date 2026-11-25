# Plans the root against a mocked AWS provider: no credentials, no AWS calls.
# Run from release-infra/: terraform init -backend=false && terraform test.
# Never planned against real state by an agent or by CI (AGENTS.md). Every run
# is a plan: the repository's prevent_destroy forbids an apply here.

mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "570327089884"
    }
  }

  mock_data "aws_iam_openid_connect_provider" {
    defaults = {
      arn = "arn:aws:iam::570327089884:oidc-provider/token.actions.githubusercontent.com"
    }
  }

  mock_resource "aws_ecrpublic_repository" {
    defaults = {
      arn            = "arn:aws:ecr-public::570327089884:repository/jaws"
      repository_uri = "public.ecr.aws/example-alias/jaws"
    }
  }
}

run "the_role_may_push_and_prune_that_repository_and_nothing_else" {
  command = plan

  assert {
    condition = jsonencode(jsondecode(module.publish_role.inline_policies["push"].policy).Statement) == jsonencode([
      { Sid = "LogInToEcrPublic", Effect = "Allow", Action = ["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"], Resource = "*" },
      { Sid = "PushTheJawsImage", Effect = "Allow", Action = ["ecr-public:BatchCheckLayerAvailability", "ecr-public:InitiateLayerUpload", "ecr-public:UploadLayerPart", "ecr-public:CompleteLayerUpload", "ecr-public:PutImage"], Resource = aws_ecrpublic_repository.jaws.arn },
      { Sid = "PruneTheJawsImage", Effect = "Allow", Action = ["ecr-public:DescribeImages", "ecr-public:BatchDeleteImage"], Resource = aws_ecrpublic_repository.jaws.arn },
    ])
    error_message = "the role logs in to ECR Public, pushes to the repository jaws and prunes it, and may do nothing else"
  }

  assert {
    condition     = length(module.publish_role.inline_policies) == 1 && length(module.publish_role.managed_policy_arns) == 0 && length(module.publish_role.managed_policies) == 0
    error_message = "one inline policy, and no managed policy"
  }
}

run "trusts_only_this_repository_s_publish_environment" {
  command = plan

  assert {
    condition = jsondecode(module.publish_role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == [
      "repo:${local.repository.name}:environment:publish",
      "repo:${split("/", local.repository.name)[0]}@${local.repository.owner_id}/${split("/", local.repository.name)[1]}@${local.repository.repository_id}:environment:publish",
    ]
    error_message = "only Jaws-Platform/jaws's publish environment may assume the role, in both subject forms"
  }

  assert {
    condition     = !can(jsondecode(module.publish_role.assume_role_policy).Statement[0].Condition.StringLike) && module.publish_role.name == "release-infra-publish"
    error_message = "no wildcard subject, and the role keeps its name, outside jaws-*"
  }
}

run "publishes_one_repository_named_jaws" {
  command = plan

  assert {
    condition     = aws_ecrpublic_repository.jaws.repository_name == "jaws"
    error_message = "the repository is named jaws"
  }

  assert {
    condition     = toset(aws_ecrpublic_repository.jaws.catalog_data[0].architectures) == toset(["x86-64"]) && toset(aws_ecrpublic_repository.jaws.catalog_data[0].operating_systems) == toset(["Linux"])
    error_message = "the image is for x86-64 and Linux"
  }

  assert {
    condition     = output.repository_uri == "public.ecr.aws/example-alias/jaws"
    error_message = "repository_uri is the repository's public address"
  }
}

run "refuses_credentials_of_another_account" {
  command = plan

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "111122223333"
    }
  }

  expect_failures = [data.aws_caller_identity.current]
}

run "is_tagged_as_jaws_s_own" {
  command = plan

  assert {
    condition = jsonencode(module.context.tags) == jsonencode({
      Organization = "Jaws-Platform"
      Project      = "jaws"
      Environment  = "prod"
      Repository   = "Jaws-Platform/jaws"
      ManagedBy    = "JAWS"
      Owner        = "Jaws-Platform"
    })
    error_message = "the repository and the role carry Jaws's own tags"
  }
}
