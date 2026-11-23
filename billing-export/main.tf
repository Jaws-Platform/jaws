# The organization's AWS bill, exported daily in FOCUS 1.2 (Parquet, every
# refresh to new files) into the billing bucket, across accounts: the
# aws-billing-export submodule of Jaws-Platform/jaws-monitoring/aws, in the
# management account. The monitoring stack's normalizer reads what it delivers
# (monitoring/main.tf local.aws_export).
#
# Applied only by the owner, from their own shell, after the release whose
# foundation apply created the bucket and its policy (which lets this account's
# exports deliver). Never by CI: no CI role, workflow or state prefix names this
# root (tests/test_billing_export.py). Runbook: README.md.

locals {
  # Present with monitoring.cost.aws (on by default with monitoring.cost).
  enabled = local.cost != null && try(local.cost.aws, true)

  export = !local.enabled ? null : {
    name                    = "${local.name_root}-focus-daily"
    bucket_name             = local.cost.bucket
    bucket_owner_account_id = local.primary_account_id
    # billing-bucket's aws_export_prefix.
    prefix = "raw/provider=aws/source=data-exports"
  }
}

module "export" {
  count   = local.enabled ? 1 : 0
  source  = "Jaws-Platform/jaws-monitoring/aws//modules/aws-billing-export"
  version = "0.8.2"

  name                    = local.export.name
  bucket_name             = local.export.bucket_name
  bucket_owner_account_id = local.export.bucket_owner_account_id
  prefix                  = local.export.prefix
}
