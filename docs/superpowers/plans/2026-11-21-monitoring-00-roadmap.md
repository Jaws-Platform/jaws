# Monitoring node and cost monitoring: plan series

**Spec:** [2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md)

The design spans four repositories. It is built as a series of plans, each
of which produces working, tested software on its own and ends in a
release. Later plans are written when their predecessors land, because the
build-start checks in section 12 of the spec change their details.

| # | Plan | Repository | Depends on | Spec sections | Status |
|---|---|---|---|---|---|
| 01 | [Billing storage](2026-11-21-monitoring-01-billing-storage.md): bootstrap the new repo, `billing-bucket`, `aws-billing-export` | `terraform-aws-jaws-monitoring` (new) | none | 6.1, 6.2, 7, 12.1–2 | written |
| 02 | Billing normalizer: the Lambda, with the AWS, Databricks and runs mappers and the run records | `terraform-aws-jaws-monitoring` | 01 | 6.4, 6.12 (schema), 12.6, 12.9 | to write |
| 03 | Databricks billing job: `databricks-billing-export` | `terraform-aws-jaws-databricks` | 01 (layout) | 6.3, 12.3–4 | to write |
| 04 | Monitoring node: the instance, disks, network, DNS, TLS, containers, config bundle and reconciler, host monitoring dashboards and alerts | `terraform-aws-jaws-monitoring` | 01 | 6.5, 6.7 (host), 6.8 (host), 6.11, 12.5, 12.7–8 | to write |
| 05 | Cost on the node: `cost-sync`, the cost, task and campaign dashboards, cost and pipeline alerts, Slack routing | `terraform-aws-jaws-monitoring` | 02, 04 | 6.6–6.8, 6.12 | to write |
| 06 | Off-hours and watchdog: the schedule, mute timings, status-check alarms, the watchdog Lambda, the root composition | `terraform-aws-jaws-monitoring` | 04 | 6.9, 6.10, 7 | to write |
| 07 | CI policy set for the monitoring stack | `terraform-aws-jaws-ci` | 04–06 (resource list) | 8 (foundation) | to write |
| 08 | Jaws integration: settings, foundation, `billing-export/`, the `monitoring/` stack, CLI (secrets, task records, `--campaign`, backfill), docs, rollout | `jaws` | 01–07 published | 8, 10, 11 | to write |

Each plan's release, the Terraform Registry publish, the repository's
creation, its settings and its secrets are owner steps, or done with the
owner's explicit permission at that point. Nothing in any plan runs
`terraform apply` or spends money. Spending starts only when the owner
merges the Jaws release in plan 08.
