# Costs

`cost report` prints monthly spend from AWS Cost Explorer, grouped by the
tags every resource this tool manages carries (see [Tags](../README.md#tags)).
Cost Explorer already aggregates the bill by tag, so there is no Cost and
Usage Report to parse and nothing to deploy: the command is read-only and
runs from the owner's shell.

It stays the ad hoc tool: a quick answer from a terminal, with nothing running.
For history, daily trends, budgets, Databricks and alerts, the monitoring
stack's dashboards in Grafana, at
[grafana.jwall.engineering](https://grafana.jwall.engineering), are the place
to look ([docs/monitoring.md](monitoring.md#dashboards-and-alerts)). They read
the organization's FOCUS export ([docs/billing-export.md](billing-export.md))
and Databricks' billing tables, not Cost Explorer:

| Dashboard | Shows |
|---|---|
| **Cost · Overview** | Every provider and account over 90 days: month to date, the forecast against the budget, the trend, where the money goes, movers, untagged spend |
| **Cost · Project** | One project by component, service and environment, against its budget |
| **Cost · Databricks** | Spend and DBUs by product, workspace and SKU, and each workspace's all-in cost |
| **Cost · Tasks** | Task runs and campaigns: one row per run with its cost, by workflow and profile |

The same data posts to Slack when spend does something unexpected: a budget
forecast or month to date over budget, a daily anomaly, new untagged spend.

```sh
jaws cost report --project braveheart   # one project, by component
jaws cost report --project braveheart --by profile  # task spend by profile, not workflow
jaws cost report                         # every project, then the untagged spend
jaws cost report --months 6              # 1-13 calendar months, this one included (default 3)
```

Cost Explorer groups by the `Project` tag as it was when the money was spent.
The chess engine's project was `rusty-chess` until 2026-11-15, so its spend
before then is under `--project rusty-chess` and its spend since is under
`--project braveheart`; neither report shows the other's months.

## What it shows

**One project** (`--project`): the project's spend by its `Component` tag.
Task instances are all `Component=task-runner`, so task spend is split by
the `Workflow` tag, the calling workflow's name: what the tasks were for,
not only where they ran. `--by profile` splits it by the `Profile` tag
instead (`cpu`, `gpu`, `train`, ...). `--by workflow` is the default, and
`--by` needs `--project`. A research project reports the same way.

```text
braveheart by component   2026-08  2026-09  2026-10*
task-runner: Datagen            —   $22.00    $41.30
task-runner: SPRT          $18.20   $25.10    $30.40
task-runner: Train              —    $1.80    $14.60
container-instance          $9.10    $9.40     $9.20
dataset                     $0.20    $0.90     $2.10
------------------------  -------  -------  --------
total                      $27.50   $59.20    $97.60
  * estimated: the month is not closed yet
```

(Illustrative numbers.) A component's spend with no `Workflow` tag, such as
the task-runner's log group, is the bare component; spend tagged with the
project but no component is `(no component)`.

**The account** (no `--project`): spend by `Project`, with everything that
has no `Project` tag in one `(untagged)` row, then that untagged spend by
service and usage type: the top 15 rows, the rest summed. Untagged spend is
anything this tool does not manage (another project's resources), and the
charges AWS never tags: public IPv4 addresses, tax, and some data transfer.
It is reported, never dropped, so the totals match the bill.

Rows under a cent in every month are left out of the table but counted in
the total. Amounts are `UnblendedCost`, what the bill says, in USD. The
current month is marked `*`: Cost Explorer's figures for it are estimates
and lag by about a day.

## Credentials

Cost Explorer is account-wide: its permissions can't be limited to one
project, so no CI role is granted `ce:GetCostAndUsage` and the command
checks no role. Run it with the owner's credentials (it logs who it runs
as). Without the permission it exits 3. Each Cost Explorer request costs
$0.01; a report makes one (`--project`) or two.

## Cost allocation tags

A tag only appears in Cost Explorer once it is activated as a cost
allocation tag (Billing → Cost allocation tags), and then only for spend
after activation, unless a backfill is requested (up to 12 months back,
one a day). For the organization, tags are activated in the management
account, the payer. The tags the reports and the dashboards use, active since
2026-10-30 with a backfill from 2025-11-01 unless marked:

| Tag | Used for |
|---|---|
| `Project` | the account report; the project filter |
| `Component` | the project report's rows |
| `Workflow` | task spend by workflow (`--by workflow`, the default) |
| `Profile` | task spend by profile (`--by profile`) |
| `Purpose`, `Lifecycle`, `RunId`, `TaskId` | active for Cost Explorer; `RunId` and `TaskId` join each task run to its cost on **Cost · Tasks** |
| `Campaign` | **not active yet: activate before use.** A task run's campaign (`task run --campaign`, [run records](remote-tasks.md#run-records)), which groups **Cost · Tasks** |
| `Workspace` | **not active yet: activate before use.** A Databricks workspace's AWS resources, which **Cost · Databricks** adds to its all-in cost |

A new tag a component adds must be activated by the owner before it shows.
