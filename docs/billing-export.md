# The organization's AWS bill: `billing-export/`

The monitoring stack's AWS costs come from one AWS Data Export, created in the
organization's management account and delivered into the billing bucket in
production. This page is what it is and why it lives where it does; the
commands are in [billing-export/README.md](../billing-export/README.md), and
the platform it feeds is [docs/monitoring.md](monitoring.md).

## What it is

| | |
| --- | --- |
| Export | `jaws-focus-daily` (`<name_root>-focus-daily`) |
| Table | FOCUS 1.2 with AWS's columns (`FOCUS_1_2_AWS`), all 60 named explicitly |
| Granularity | daily line items, refreshed at least once a day |
| Format | Parquet; every refresh is written to new files, so nothing delivered is overwritten |
| Covers | every account in the organization: management, production and development, and any added later |
| Lives in | the management account (650503560686), the payer |
| Delivers to | `s3://jaws-billing-570327089884/raw/provider=aws/source=data-exports/jaws-focus-daily/`, in production (570327089884) |
| Module | [`aws-billing-export`](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.0/modules/aws-billing-export/README.md) of `Jaws-Platform/jaws-monitoring/aws`, v0.8.0 |
| Turned on by | `monitoring.cost.aws` in `config/monitoring.yaml` |

It is the whole bill, as AWS itself reports it: tax, credits and the charges
AWS never tags (public IPv4, some data transfer) included, with the cost
allocation tags in its `Tags` column. Exports cost nothing beyond the storage,
which grows about 1 GB a year.

## Why it is an owner root in the management account

- **Only the payer sees the whole organization.** An export created in a
  member account covers that account alone, and only since it joined. The
  management account is the payer, so the export has to live there.
- **It is the one exception to "everything in production".** The management
  account was retired as a workload account on 2026-11-21, and Jaws builds only
  in the primary account (`config/aws.yaml`). The owner agreed to this one
  exception: the export's configuration lives in the management account, and
  nothing runs or is stored there.
- **So no CI role can reach it.** CI roles exist only in production. Like
  [`owner-access/`](owner-access.md), the root is applied only by the owner,
  from their own shell with the `jwall-admin` profile. No CI role, workflow or
  state prefix names it (`tests/test_billing_export.py` checks), and agents
  never plan it against its state.
- **Its state** sits beside owner-access's, in the management account's
  owner-only bucket: `jaws-owner-access-state-650503560686`, key
  `project=billing-export/env=prod/billing-export-prod.tfstate`.

## Running it

Once, after the Jaws release whose foundation apply created the billing
bucket: the bucket's policy is what lets the management account's exports
deliver, and creating the export fails without it. The owner signs in with
`jwall-admin`, then runs `terraform init`, `plan` and `apply` in
`billing-export/`, which adds the one export; the plan stops unless the
credentials are the management account's. The exact commands are in
[billing-export/README.md](../billing-export/README.md#run-it).

It is a one-time step. The root changes again only if the export does: its
name and prefix are where the monitoring stack reads (`local.aws_export` in
`monitoring/main.tf`), so they change together, and renaming the export starts
a new delivery folder. Turning `monitoring.cost.aws` off makes this root
destroy the export on its next apply.

## The delivery path

```text
management account                            production account
Data Export jaws-focus-daily ── daily, ──►    s3://jaws-billing-570327089884/raw/provider=aws/source=data-exports/
                                across        jaws-focus-daily/
                                accounts        data/BILLING_PERIOD=YYYY-MM/<timestamp>-<execution-id>/jaws-focus-daily-00001.snappy.parquet
                                                metadata/BILLING_PERIOD=YYYY-MM/Manifest.json
                                                      │
                                                      ▼  jaws-monitoring-normalizer, hourly
                                              normalized/schema=focus-1.2/provider=aws/billing_period=YYYY-MM/data.parquet
```

1. **AWS writes the files.** The bucket's policy (the foundation's
   `billing-bucket`) lets `bcm-data-exports.amazonaws.com` put objects only
   for the management account's exports (`aws:SourceAccount` and
   `aws:SourceArn`), and the export names production as the bucket's owner.
   Each refresh writes a new execution folder for the billing period, then
   rewrites that period's `Manifest.json` to point at it.
2. **The normalizer reads the newest delivery.** Every hour it reads each
   period's manifest, and rebuilds the period's normalized rows when the
   manifest names a newer execution. AWS refreshes the current month at
   least daily and may restate the previous month for up to two weeks, so the
   newest delivery of a period always wins and corrections replace the
   period whole.
3. **The node loads it.** `cost-sync` loads each rebuilt period into the
   node's cost database within 30 minutes, and the cost dashboards and alerts
   read it from there ([docs/monitoring.md](monitoring.md#dashboards-and-alerts)).

Everything AWS delivers stays under `raw/` for good: the bucket is versioned,
no lifecycle rule touches `raw/`, and with `protect_raw` on no delete call can
remove anything there. Bills arrive about a day late, so the dashboards show
yesterday as partial and a day is complete 48 hours after it ends.

## Follow-ups

The owner's, after the export exists:

1. **Activate the `Campaign` and `Workspace` cost allocation tags** in the
   management account (Billing and Cost Management → Cost allocation tags).
   A tag appears in the export's `Tags` column only once it is active there,
   and only for spend after that unless a backfill is asked for (up to 12
   months back, one a day). `Campaign` is on task instances and their volumes
   ([run records](remote-tasks.md#run-records)) and groups the
   **Cost · Tasks** dashboard's campaigns, even for a run whose record failed
   to write; `Workspace` is on each Databricks workspace's AWS resources and
   gives **Cost · Databricks** its all-in cost. The other tags the
   dashboards use have been active since 2026-10-30 ([docs/costs.md](costs.md#cost-allocation-tags)).
2. **Check the first delivery, then set `protect_raw: true`.** The first
   delivery lands within about 24 hours, under
   `raw/provider=aws/source=data-exports/jaws-focus-daily/data/BILLING_PERIOD=YYYY-MM/`.
   Check it is there and that nothing landed elsewhere, and check the first
   Databricks run the same way, under `raw/provider=databricks/source=system-tables/`:

   ```sh
   aws s3 ls --recursive s3://jaws-billing-570327089884/raw/ --profile jaws-prod
   ```

   Then set `monitoring.cost.protect_raw: true` in `config/monitoring.yaml`,
   in a pull request, and release: the foundation's apply adds the deny to the
   bucket policy. From then on nothing under `raw/` can be deleted, a
   misplaced object included, which is why it waits for the check.
3. **Ask for the history (optional).** After the first delivery, open a free
   AWS Support billing case from the management account, naming the export
   (`jaws-focus-daily`) and the months wanted. Most sources say up to 36
   months back, one AWS guide says 14. It takes up to 24 hours, lands in the
   same folders as any delivery, and the normalizer's next run picks it up. A
   backfill cannot reach past a change in the organization's structure, and
   the production and development accounts joined in 2026, so their history
   may start then.
