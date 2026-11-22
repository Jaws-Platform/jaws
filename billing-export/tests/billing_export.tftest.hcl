# Plans the root against a mocked AWS provider: no credentials, no AWS calls.
# Run from billing-export/: terraform init -backend=false && terraform test.
# Never planned against real state by an agent or by CI (AGENTS.md).

mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "650503560686"
    }
  }

  mock_resource "aws_bcmdataexports_export" {
    defaults = {
      arn = "arn:aws:bcm-data-exports:us-east-1:650503560686:export/jaws-focus-daily-0123456789abcdef"
    }
  }
}

run "the_export_is_the_organizations_focus_daily" {
  command = plan

  assert {
    condition     = output.name == "jaws-focus-daily"
    error_message = "the export is <name_root>-focus-daily"
  }

  assert {
    condition     = output.delivery_prefix == "raw/provider=aws/source=data-exports/jaws-focus-daily"
    error_message = "AWS delivers under the billing bucket's aws_export_prefix, where the monitoring stack's normalizer reads (monitoring/main.tf local.aws_export)"
  }
}

run "it_delivers_across_accounts_into_the_billing_bucket" {
  command = plan

  assert {
    condition     = local.export.bucket_name == "jaws-billing-570327089884" && local.export.bucket_owner_account_id == "570327089884"
    error_message = "the export delivers into monitoring.cost.bucket, owned by the primary account (production), from the management account"
  }

  assert {
    condition     = local.account_id == "650503560686"
    error_message = "the root is applied in the organization's management account (config/aws.yaml, type management), the payer whose bill covers every account"
  }
}

run "is_tagged_as_part_of_the_monitoring_platform" {
  command = plan

  assert {
    condition = jsonencode(module.context.tags) == jsonencode({
      Organization = "Jaws-Platform"
      Project      = "monitoring"
      Environment  = "prod"
      Repository   = "Jaws-Platform/jaws"
      ManagedBy    = "JAWS"
      Owner        = "jwallace145"
    })
    error_message = "the export carries the platform's tags with Project = monitoring"
  }
}

run "refuses_any_account_but_the_management_account" {
  command = plan

  override_data {
    target = data.aws_caller_identity.current
    values = {
      account_id = "570327089884"
    }
  }

  expect_failures = [data.aws_caller_identity.current]
}
