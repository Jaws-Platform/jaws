# billing-export/

The organization's AWS bill, exported daily in FOCUS 1.2 into the billing
bucket: the
[`aws-billing-export`](https://registry.terraform.io/modules/Jaws-Platform/jaws-monitoring/aws/latest/submodules/aws-billing-export)
submodule of `Jaws-Platform/jaws-monitoring/aws`, as one export,
`jaws-focus-daily` (`<name_root>-focus-daily`), in the organization's
management account (`config/aws.yaml`, type `management`). Created in the payer,
it covers every account. AWS delivers across accounts into
`monitoring.cost.bucket` (`config/monitoring.yaml`), in the primary account,
under `raw/provider=aws/source=data-exports/jaws-focus-daily/`, where the
monitoring stack's normalizer reads it.

**The owner's root.** Like `owner-access/`, it is applied only by the owner,
with the owner's `jwall-admin` profile, and never by CI: no CI role, workflow or
state prefix names it (`tests/test_billing_export.py`). Its state sits beside
owner-access's, in the management account's owner-only bucket
(`jaws-owner-access-state-650503560686`, key
`project=billing-export/env=prod/billing-export-prod.tfstate`). Agents never
plan it against that state.

## Run it

Once, after the Jaws release whose foundation apply created the billing bucket:
the bucket's policy is what lets this account's exports deliver, and creating
the export fails without it.

```sh
aws sso login --profile jwall-admin
export AWS_PROFILE=jwall-admin
cd billing-export
terraform init -backend-config=backend/prod.hcl
terraform plan -out=tfplan     # one export to add: jaws-focus-daily
terraform apply tfplan
terraform output delivery_prefix
```

The plan stops unless the credentials are the management account's.

## Then

- **The first delivery** lands within about 24 hours, under
  `raw/provider=aws/source=data-exports/jaws-focus-daily/data/BILLING_PERIOD=YYYY-MM/`.
  Check it is there (and nothing landed elsewhere) before setting
  `monitoring.cost.protect_raw: true`.
- **History** (optional): after the first delivery, open a free AWS Support
  billing case naming the management account, the export and the months
  wanted. AWS backfills into the same folders.
- **Tags:** cost allocation tags appear in the export's `Tags` column once they
  are activated in this account (Billing console, Cost allocation tags):
  activate `Campaign` and `Workspace` here; the rest are already active.

## Changing it

The export's name and prefix are where the monitoring stack reads
(`monitoring/main.tf`, `local.aws_export`): change both together. Renaming the
export starts a new delivery folder. Turning `monitoring.cost.aws` off makes
this root destroy the export on its next apply.

Locally, with no credentials:

```sh
terraform init -backend=false && terraform validate && terraform test
```
