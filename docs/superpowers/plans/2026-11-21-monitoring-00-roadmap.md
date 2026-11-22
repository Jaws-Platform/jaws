# Monitoring node and cost monitoring: plan series

**Spec:** [2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md)

The design spans four repositories. It is built as a series of plans, each
of which produces working, tested software on its own and ends in a
release. Later plans are written when their predecessors land, because the
build-start checks in section 12 of the spec change their details.

| # | Plan | Repository | Depends on | Spec sections | Status |
|---|---|---|---|---|---|
| 01 | [Billing storage](2026-11-21-monitoring-01-billing-storage.md): bootstrap the new repo, `billing-bucket`, `aws-billing-export` | `terraform-aws-jaws-monitoring` (new) | none | 6.1, 6.2, 7, 12.1–2 | released v0.1.0 (2026-11-21); registry publish is the owner's |
| 02 | [Billing normalizer](2026-11-21-monitoring-02-billing-normalizer.md): the Lambda, with the AWS, Databricks and runs mappers and the run records | `terraform-aws-jaws-monitoring` | 01 | 6.4, 6.12 (schema), 12.6, 12.9 | released v0.2.0 (2026-11-21) |
| 03 | [Databricks billing job](2026-11-21-monitoring-03-databricks-billing-job.md): `databricks-billing-export` | `terraform-aws-jaws-databricks` | 01 (layout) | 6.3, 12.3–4 | released `jaws-databricks` v0.2.0 (2026-11-22) |
| 04 | [Monitoring node](2026-11-22-monitoring-04-monitoring-node.md): the instance, data volume, network, DNS, bootstrap, reconciler and container stack (Caddy, Grafana on Postgres, Prometheus, exporters) | `terraform-aws-jaws-monitoring` | 01 | 6.5, 6.11 | released v0.3.0 (2026-11-22) |
| 05 | Host monitoring: the host dashboard, host alert rules, the Slack contact points and routing, message templates, the rules validator | `terraform-aws-jaws-monitoring` | 04 | 6.7 (host), 6.8 (host, Slack), 12.8 | released v0.4.0 (2026-11-22, [plan](2026-11-22-monitoring-05-host-monitoring.md)) |
| 06a | Cost sync: the normalizer's CSV twin, `cost-sync` and the `cost` database on the node, Grafana's read-only data source, the Pipeline row and the pipeline alerts | `terraform-aws-jaws-monitoring` | 02, 05 | 6.6, 6.8 (pipeline), 6.12 | written ([plan](2026-11-22-monitoring-06a-cost-sync.md)) |
| 06b | Cost views: the rollups, forecast and budgets, the cost, task and campaign dashboards, the cost alerts | `terraform-aws-jaws-monitoring` | 06a | 6.6–6.8, 6.12, 12.7 | to write |
| 07 | Off-hours and watchdog: the schedule, mute timings, status-check alarms, the watchdog Lambda, the root composition | `terraform-aws-jaws-monitoring` | 05 | 6.9, 6.10, 7 | to write |
| 08 | CI policy set for the monitoring stack | `terraform-aws-jaws-ci` | 04–07 (resource list) | 8 (foundation) | to write |
| 09 | Jaws integration: settings, foundation, `billing-export/`, the `monitoring/` stack, CLI (secrets, task records, `--campaign`, backfill), docs, rollout and first-run checks | `jaws` | 01–08 published | 8, 10, 11, 12.5 | to write |

Each plan's release, the Terraform Registry publish, the repository's
creation, its settings and its secrets are owner steps, or done with the
owner's explicit permission at that point. Nothing in any plan runs
`terraform apply` or spends money. Spending starts only when the owner
merges the Jaws release in plan 09.

On 2026-11-22 the original plan 04 was split in two (the node, then host monitoring), so the later plans moved up by one. The monitoring family's Slack routing moved to plan 05, because the host alerts need it.
