# The sample Databricks project's account stack, planned against mock AWS and
# Databricks providers: the rendered inputs pass the stack's and the modules'
# validations, and the network is wired the way the workspace needs it.
mock_provider "aws" {
  mock_data "aws_ami" {
    defaults = {
      id           = "ami-0123456789abcdef0"
      architecture = "arm64"
    }
  }

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "650503560686"
      arn        = "arn:aws:iam::650503560686:root"
    }
  }

  mock_data "aws_region" {
    defaults = {
      region = "us-east-1"
      name   = "us-east-1"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{}"
    }
  }

  mock_data "aws_default_tags" {
    defaults = {
      tags = {}
    }
  }
}

mock_provider "databricks" {
  alias = "account"

  # The deployer's numeric ID feeds tonumber() in the module; known at plan, so
  # the runs below can assert on the stack's output.
  mock_resource "databricks_service_principal" {
    override_during = plan
    defaults = {
      id             = "8888"
      application_id = "99999999-8888-7777-6666-555555555555"
    }
  }

  mock_data "databricks_metastore" {
    defaults = {
      id           = "abcdef01-2345-6789-abcd-ef0123456789"
      metastore_id = "abcdef01-2345-6789-abcd-ef0123456789"
    }
  }
}

mock_provider "time" {}

# Realistic outputs of the provider's policy helpers, as the mock would return
# documents that are not JSON.
override_data {
  target = module.workspace.data.databricks_aws_assume_role_policy.this
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"sts:AssumeRole\",\"Principal\":{\"AWS\":\"arn:aws:iam::414351767826:root\"},\"Condition\":{\"StringEquals\":{\"sts:ExternalId\":\"00000000-0000-0000-0000-000000000000\"}}}]}"
  }
}

override_data {
  target = module.workspace.data.databricks_aws_crossaccount_policy.this
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"ec2:DescribeSubnets\",\"ec2:RunInstances\"],\"Resource\":\"*\"}]}"
  }
}

override_data {
  target = module.workspace.data.databricks_aws_bucket_policy.root
  values = {
    json = "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\"],\"Resource\":[\"arn:aws:s3:::jwall-engineering-databricks-poc-databricks-root/*\",\"arn:aws:s3:::jwall-engineering-databricks-poc-databricks-root\"],\"Principal\":{\"AWS\":\"arn:aws:iam::414351767826:root\"}}]}"
  }
}

run "plans_the_network_nat_and_workspace" {
  command = plan

  assert {
    condition     = local.private_subnet_cidrs == ["10.40.128.0/20", "10.40.144.0/20"]
    error_message = "the private subnets are the two /20s in the upper half of vpc_cidr"
  }

  assert {
    condition = (
      one([for f in data.aws_ami.nat.filter : one(f.values) if f.name == "name"]) == var.nat_ami_name &&
      one([for f in data.aws_ami.nat.filter : one(f.values) if f.name == "architecture"]) == "arm64" &&
      one(data.aws_ami.nat.owners) == "amazon"
    )
    error_message = "the NAT image is resolved by its pinned name, arm64 only"
  }

  assert {
    condition     = output.metastore_id == "abcdef01-2345-6789-abcd-ef0123456789"
    error_message = "the metastore comes from the lookup by name"
  }

  assert {
    condition     = contains([for s in jsondecode(module.workspace.s3_endpoint_policy).Statement : s.Sid], "UnityCatalogOnly")
    error_message = "the S3 endpoint carries the workspace module's policy"
  }
}


run "without_a_deployer_none_is_created" {
  command = plan

  assert {
    condition     = output.deployer_application_id == null
    error_message = "a project file that asks for no deployer gets none"
  }
}

run "a_deployer_reaches_the_workspace_module" {
  command = plan

  variables {
    deployer = {
      repository    = "jwallace145/databricks-poc"
      repository_id = "1458298100"
      owner_id      = "35950238"
    }
  }

  assert {
    condition     = output.deployer_application_id == "99999999-8888-7777-6666-555555555555"
    error_message = "the stack passes deployer to the workspace module and outputs its application ID"
  }
}
