# Monitoring node and cost monitoring: design

Date: 2026-11-21. Status: draft for the owner's review. Nothing described
here exists yet.

## 1. Intent

The owner wants one shared monitoring platform for everything Jaws runs. It
starts with cost: **how much is being spent across all cloud accounts and
providers**, shown in a form that is easy to take in, with Slack alerts when
spend does something unexpected.

Today the only cost view is `jaws cost report` ([costs.md](../../costs.md)).
It is an ad hoc Cost Explorer query that needs the owner's credentials, has
no history and no alerts, and doesn't cover Databricks at all.

The platform is a single always-on node in the production account running
Grafana and Prometheus. The owner maintains it by hand, so its own health
gets monitored as carefully as the costs. It is a fixed platform cost of
about $30 a month, shared by every project, and is meant to serve the
owner's monitoring needs from now on.

The cost model has to generalize. "How do we monitor cost across multiple
sources for heterogeneous cloud infrastructure?" is the real problem, so AWS
and Databricks are the first two providers of a design that can take a
third without being reshaped.

## 2. Goals, non-goals, anti-goals

**Goals**

1. A daily, organization-wide view of AWS spend across the management,
   production and development accounts. It can be broken down by account,
   service and the Jaws cost allocation tags (`Project`, `Component`,
   `Environment` and the rest).
2. Databricks spend, serverless included, in the same model, next to AWS
   spend.
3. Raw billing data kept forever, never deleted, laid out for bulk analysis
   later.
4. Thorough host monitoring of the node: CPU (including burst credits),
   memory, disk growth, services, TLS and patching. Every important metric
   gets warning and critical thresholds.
5. Slack alerts for host, pipeline and cost, routed to channels set in
   configuration.
6. A node that can die, be replaced, or be stopped on a schedule, and come
   back with its cost data and metrics history intact.
7. Generic, optional modules: every feature is off until its input is
   given. Jaws's `config.yaml` is the enforcement boundary that turns on
   what Jaws uses.
8. Backfilled history for both providers, where the providers allow it. A
   nice-to-have, not a requirement (12.9).
9. The cost of every task run, in a table with its project, task and launch
   metadata (6.12). The owner will run a lot of GPU training, and that is
   where most spend will be.

**Non-goals for v1**

- Metrics from projects (bots, tasks, sites) sent to the node. The node is
  designed so this can be added later; see section 13.
- Spend detection faster than about a day. Bills arrive a day late, and the
  owner has accepted next-morning alerts.
- Contract or discount pricing for Databricks. The owner pays by card,
  pay-as-you-go, so list price is the billed price.
- Formal FOCUS conformance. The schema is FOCUS-aligned, not certified.
- Log aggregation (no Loki), high availability, multiple regions, SSO for
  Grafana, and Kubernetes cost tools.

**Anti-goals.** Any of these would count as failure even if everything
technically works:

- Running costs creeping well past the agreed ~$30 a month.
- Alert noise, such as pages over cents or a burst of alerts after every
  scheduled start.
- Losing or silently rewriting raw billing data.
- Configuration done by hand in the Grafana UI or the console that the code
  can't reproduce. A snowflake node.
- A project being able to change platform settings (instance type,
  schedule, channels).

## 3. Constraints

- **Accounts.** Production (570327089884) holds everything that runs.
  - Organization-wide billing data can only come from the payer, which is
    the management account (650503560686). It was retired as a workload
    account on 2026-11-21.
  - The owner agreed to one exception: the billing export's configuration
    lives in the management account and is applied by the owner, like
    `owner-access/`. Nothing runs or is stored there.
- **Jaws rules ([AGENTS.md](../../../AGENTS.md)).**
  - Agents never run `terraform apply`. Applies happen only through the
    release apply job, or by the owner for owner roots.
  - Secrets and GitHub settings are handed off to the owner.
  - Commits are a single line.
- **Cost sensitivity.** No paid add-ons where a free one works: no Amazon
  Managed Grafana, no Grafana Enterprise plugins, no RDS, no NAT, no load
  balancer.
- **Tags.** The cost allocation tags have been active since 2026-10-30,
  with a backfill from 2025-11-01. The Databricks workspaces carry
  `Project`, `CostCenter` and `Workspace` tags
  ([databricks.md](../../databricks.md)).

## 4. Approaches

Every option shares the same sources (the export and the Databricks job),
the same bucket and the same node. They differ in **where raw bills become
FOCUS rows**.

1. **Everything on the node.** A loader on the node reads `raw/`, writes
   `normalized/` and fills Postgres.
   - It has the fewest pieces and no extra cost.
   - But `normalized/`, the layer meant for historical analysis, stops
     being written whenever the node is down or stopped, and the pipeline
     competes for the node's memory.
2. **A Lambda normalizes; the node only displays. (Chosen.)** A scheduled
   Lambda turns `raw/` into `normalized/`, with one mapper per provider,
   and records each run. The node copies `normalized/` into Postgres and
   alerts.
   - The bucket stays complete whatever state the node is in, and a new
     node rebuilds itself from it.
   - The provider mappers are the reusable core and are tested and
     released on their own.
   - It costs cents.
3. **No database: Grafana queries the bucket through Athena.** The node is
   smaller and nothing needs syncing. But every panel refresh is a billed
   query taking seconds, and the owner chose Postgres. Dropped.

The owner picked **2**.

## 5. Architecture

```text
 management account (payer)                     production account
 ┌────────────────────────────┐  cross-account  ┌──────────────────────────────────────────────┐
 │ Data Export: FOCUS 1.2,    │ ───────────────►│ s3://jaws-billing/raw/provider=aws/…         │
 │ DAILY, org-wide            │    delivery     │ s3://jaws-billing/raw/provider=databricks/…  │◄── jaws-shared workspace:
 │ (owner-applied root)       │                 │                │                             │    serverless job, daily
 └────────────────────────────┘                 │                ▼  hourly                     │
                                                │      billing-normalizer (Lambda)             │
                                                │                ▼                             │
                                                │ s3://jaws-billing/normalized/schema=focus-1.2/│
                                                │                ▼  every 30 min and at boot   │
                                                │ monitoring node (t9g.medium, AL2023 arm64)   │
                                                │   Caddy → Grafana ← Postgres (cost cache)    │
                                                │           Grafana ← Prometheus ← exporters   │──► Slack
                                                │ watchdog (Lambda) + status-check alarms      │──► Slack
                                                └──────────────────────────────────────────────┘
```

A third source, `jaws task run`, writes one record per task run under
`raw/provider=jaws/source=task-runs/`. That record is run metadata, not a
bill (6.12).

**The generalizing contract.** Every source re-delivers whole billing
periods, and the newest delivery of a period wins. AWS Data Exports already
work this way: each refresh carries the whole month to date, and corrections
arrive in later deliveries. The Databricks job is built to match.

So the normalizer never merges increments. It rebuilds one
`(provider, billing period)` at a time from that period's newest delivery.
Restatements, retractions and late corrections fall out for free. A new
provider needs two things: a source that delivers period snapshots under
`raw/provider=<p>/`, and a mapper from its columns to the schema in 6.4.

**Lifecycle split.** Durable data, meaning the bucket and the Databricks
job, belongs to the **foundation**. Replaceable compute, meaning the node
and the Lambdas, belongs to a new **`monitoring/` stack**. The monitoring
stack can be destroyed and recreated without touching any billing history.

## 6. Components

### 6.1 The billing bucket: `jaws-billing`

The `billing-bucket` submodule, applied by the foundation.

```text
s3://jaws-billing/
  raw/                                     # what each provider delivered; never deleted
    provider=aws/source=data-exports/      #   AWS writes its own layout below this prefix:
                                           #   <export-name>/data/BILLING_PERIOD=YYYY-MM/<execution>/…
                                           #   <export-name>/metadata/…
    provider=databricks/source=system-tables/
      table=usage/billing_period=YYYY-MM/run=<UTC timestamp>/part-0.parquet
      table=list_prices/run=<UTC timestamp>/part-0.parquet
      table=workspaces/run=<UTC timestamp>/part-0.parquet      # id → name, if available (§6.3)
    provider=jaws/source=task-runs/        #   one record per run event (6.12)
      project=<p>/date=YYYY-MM-DD/<run-id>.<task-id>.<started|finished|swept>.json
  normalized/                              # the normalizer's output; rebuildable from raw/
    schema=focus-1.2/provider=<p>/billing_period=YYYY-MM/data.parquet
    schema=runs-1/billing_period=YYYY-MM/data.parquet
    _runs/<UTC timestamp>.json             # one record per normalizer run
```

- **Raw data is never removed.**
  - Versioning is on.
  - The bucket policy denies `s3:DeleteObject` and `s3:DeleteObjectVersion`
    on `raw/*` to every principal.
  - There is no lifecycle rule on `raw/`.
  - Overwrites are allowed so that AWS delivery keeps working, but
    versioning keeps every older version anyway.
  - Undoing any of this takes a deliberate bucket-policy change by an
    admin. Object Lock is deliberately not used, because compliance mode
    can't be undone.
  - The deny statement (`protect_raw`, default true) is switched on only
    after the first AWS and Databricks deliveries have been checked to land
    under the right prefixes. Until then, a misplaced first object can
    still be cleaned up (section 10).
- **Name.** `jaws-billing`, from config `monitoring.cost.bucket`. No bucket
  by that name exists today (checked 2026-11-21). But
  `jaws-terraform-state` was refused at bootstrap even though it looked
  free. If creation fails, use `jaws-billing-570327089884`, the state
  bucket's pattern. Settle the name before the export is applied, because
  it's written into the export and the policies.
- **`normalized/` is overwritten in place.**
  - There is one object per `(provider, period)`, so no stale part files
    are left behind.
  - Noncurrent versions under `normalized/` expire after 30 days.
- **General settings:**
  - Block Public Access on.
  - ACLs disabled (BucketOwnerEnforced).
  - SSE-S3 encryption.
  - Non-TLS requests denied.
  - The bucket carries `Component=billing`.
- **Writers:**
  - `bcm-data-exports.amazonaws.com` may `PutObject` only under
    `raw/provider=aws/`. The condition is `aws:SourceAccount` = the
    management account and `aws:SourceArn` =
    `arn:aws:bcm-data-exports:us-east-1:<management>:export/*`.
  - The Databricks writer role may `PutObject` only under
    `raw/provider=databricks/` (6.3).
  - The normalizer may write only under `normalized/`.
- **Readers:**
  - The normalizer reads `raw/`.
  - The node reads `normalized/` and nothing else.
  - The owner can read everything.
- **Growth.** The export's "create new" mode re-delivers the month to date
  every day. For this organization that is roughly a gigabyte a year at
  most, about $0.02 a month of storage per year kept.

### 6.2 The AWS export (management account)

The `aws-billing-export` submodule, applied by the owner from a new root,
`billing-export/`, in the Jaws repo. That root uses the management
account's state bucket and `--profile jwall-admin`. CI never plans or
applies it, as with `owner-access/`.

- One **FOCUS 1.2** export at `TIME_GRANULARITY = DAILY`, in Parquet, with
  overwrite set to **create new** rather than overwrite.
- Delivered cross-account to `s3://jaws-billing/raw/provider=aws/source=data-exports/`.
- Created in the payer account, so it covers every member account.
- Tags appear in the FOCUS `Tags` map. The current ones are already
  activated in the management account. This root activates the new
  `Campaign` tag (`aws_ce_cost_allocation_tag`, 6.12). Adopting the
  existing activations here is optional later work.
- Order: the foundation creates the bucket and its policy first, then the
  owner applies this root. The first delivery arrives within about 24
  hours.

### 6.3 The Databricks billing job (`jaws-shared`)

The `databricks-billing-export` submodule, new in
`terraform-aws-jaws-databricks`. It is optional, and Jaws turns it on. The
foundation applies it with its existing `databricks.shared` provider, next
to `databricks_shared_host`, so the platform workspace is set up for cost
monitoring from the day it is created.

- **The job.** One `databricks_job` on **serverless jobs compute**, using
  standard performance mode for the lowest DBU rate.
  - A single Python task runs a file the module uploads as a workspace
    file. It is not a bundle (DAB): the shared host is already managed by
    Terraform, and one job doesn't justify a second deploy tool.
  - It runs daily at 06:00 UTC.
- **Each run writes:**
  - `system.billing.usage` for the **current and the previous billing
    period**, as full snapshots, one object per period. A `periods` job
    parameter overrides that; `all` is the one-time backfill. That re-delivery
    covers the roughly 12-hour latency and late `RETRACTION` and
    `RESTATEMENT` rows.
  - A full snapshot of `system.billing.list_prices`.
  - A workspace id-to-name table, if a system table offers one (for
    example `system.access.workspaces_latest`). Otherwise the normalizer
    falls back to ids.
- **How it writes.** It uses a Unity Catalog **service credential** backed
  by a new IAM role, `jaws-databricks-billing-writer`. The role is allowed
  only `s3:PutObject` on `jaws-billing/raw/provider=databricks/*`. The
  task collects each snapshot (small) and puts one Parquet object with
  boto3.
  - This avoids Spark's temporary and marker files, which would need
    deletes.
  - Verify at build start (section 12). The fallback is an external volume
    over a `staging/` prefix, which the normalizer copies from.
- **Identity.** The job runs as a dedicated service principal,
  `jaws-billing-exporter`. It has `USE` and `SELECT` on `system.billing`
  (and the workspace table) and access to the service credential, nothing
  more. That's my call; the automation principal is a fallback.
- **Cost.** About $0.50 to $3 a month (estimated; measure it in the first
  week). The Databricks dashboard shows this job's own spend.

### 6.4 The normalizer (Lambda)

The `billing-normalizer` submodule, applied by the `monitoring/` stack.

- **Runtime.** Python 3.13 on arm64, run hourly by EventBridge Scheduler
  and invocable by hand. Hourly runs keep task-run records fresh (6.12).
  A run with no new deliveries does almost nothing.
  - Parquet support comes from the AWS SDK for pandas managed layer, which
    includes pyarrow, so the function's own code is plain Python with
    nothing to build.
  - Verify the layer ARN; the fallback is packaging pyarrow.
- **Each run:**
  1. For each enabled provider, find each billing period's newest
     delivery:
     - AWS: read the export's manifest or the newest execution folder.
     - Databricks: the newest `run=`.
  2. Rebuild every period whose newest delivery is newer than its current
     `normalized/` object, which records its source key and version in
     Parquet metadata.
  3. Write the `_runs/` record: start and end, status, and for each period
     the rows, total `BilledCost` and source keys, plus any error.
  4. Exit non-zero on any error, so the run record and the Lambda's
     `Errors` metric both show it.
- **Source precedence.** A provider can have more than one source for a
  period: for AWS, the export and a one-time Cost Explorer backfill (12.9).
  The export wins for every period it covers, so nothing is counted twice.
- **Normalized schema** (FOCUS 1.2 names; `x_` columns are Jaws
  extensions). One row per day × provider × account × service × SKU ×
  resource × tag set.

  | Column | AWS source | Databricks source |
  |---|---|---|
  | `ProviderName` | FOCUS `ProviderName` | `Databricks` |
  | `BillingAccountId` / `BillingAccountName` | FOCUS | account id / config name |
  | `SubAccountId` / `SubAccountName` | FOCUS (member account) | `workspace_id` / workspace name |
  | `BillingPeriodStart` | FOCUS | first of `usage_date`'s month |
  | `ChargePeriodStart` / `ChargePeriodEnd` | FOCUS (daily) | `usage_date`, `usage_date` + 1 day |
  | `ChargeCategory` / `ChargeClass` | FOCUS | `Usage`; `Correction` for retraction and restatement rows |
  | `ServiceName` / `ServiceCategory` | FOCUS | `Databricks <billing_origin_product>` / per-product mapping |
  | `SkuId` | FOCUS | `sku_name` |
  | `RegionId` | FOCUS | workspace region |
  | `ResourceId` | FOCUS (nullable) | job, warehouse, cluster or endpoint id from `usage_metadata` |
  | `ConsumedQuantity` / `ConsumedUnit` | FOCUS | `usage_quantity` / `usage_unit` |
  | `ListCost`, `BilledCost`, `EffectiveCost` | FOCUS | `usage_quantity` × the matching `list_prices.pricing.default` (all three equal) |
  | `BillingCurrency` | FOCUS | `currency_code` |
  | `Tags` (map) | FOCUS `Tags` | `custom_tags` |
  | `x_Project`, `x_Component`, `x_Environment` | promoted from `Tags` | promoted from `custom_tags` |
  | `x_Serverless` | null | `product_features.is_serverless` |
  | `x_Source` | source key and version | source key and version |

  - The promoted tag list is an input, defaulting to `Project`, `Component`
    and `Environment`.
  - When a Databricks row's `custom_tags` has no `Project`, the project is
    taken from the workspace instead, through a `workspace_projects` input.
    Jaws passes each `<project>-prod` workspace, and `jaws-shared` as
    `jaws`. Serverless usage without a usage policy gets its project this
    way.
  - Prices are matched on SKU, cloud and unit, with
    `price_start_time <= usage_start_time < coalesce(price_end_time, ∞)`.
  - Databricks' `databricks-solutions/cloud-infra-costs` FOCUS SQL is a
    useful reference for mapping choices. Write our own mapping, though:
    that repo is under the Databricks License.
  - **Double counting.** A Databricks subscription bought through AWS
    Marketplace would show up in the AWS rows too. It doesn't apply here
    (the owner pays by card). The module documents the caveat and offers
    an `exclude_marketplace_products` input, empty by default.

### 6.5 The monitoring node

The `monitoring-node` submodule, applied by the `monitoring/` stack. It
follows `container-instance` from `terraform-aws-jaws-lichess-bot`:

- Amazon Linux 2023 arm64, IMDSv2 only, encrypted gp3, Session Manager, and
  no SSH key.
- Resources carry `Name` and `Component=monitoring`; every other tag comes
  from the caller's `default_tags`.

**Instance and disks**

- **Instance.** `instance_type` is an input, `t9g.medium` in Jaws, placed
  in a subnet whose zone offers it. Changing `instance_type` is an in-place
  stop, modify and start.
- **AMI and patching.** The AMI is pinned by its Amazon image name
  (`ami_name`; in Jaws `monitoring.ami`, like `databricks.nat_ami`).
  - Patching is an AMI bump: a PR and a release, which replace the instance
    and reattach the data volume (6.11).
  - There are no in-place `dnf upgrade`s, because AL2023 locks packages to
    the AMI's release.
  - Container images are pinned in the module and bumped by module
    releases.
- **Root volume.** 12 GB: the OS, Docker images and a 2 GB swap file.
- **Data volume.** 30 GB gp3, a separate `aws_ebs_volume` in the subnet's
  availability zone. It is attached and mounted at boot, and kept when the
  instance is replaced. It holds the Prometheus TSDB, the Postgres data
  directory (Grafana's and the cost database), Grafana's plugin and state
  directory, and Caddy's certificate storage. Keeping the certificates
  there avoids Let's Encrypt reissue limits on replacement.
- **Snapshots** (optional, on in Jaws). Nightly Data Lifecycle Manager
  snapshots of the data volume, keeping 7. With a schedule they are taken
  inside the off window (6.10).

**Network and access**

- **Network.** Its own VPC from `jaws-network//modules/vpc`, with one
  public subnet and no NAT, like the bot stacks.
- **Security group.** Ingress only on 443 and 80, the latter for ACME and
  the redirect. Nothing else is exposed: Prometheus and Postgres listen
  only on the Docker network.
- **DNS** (optional: `domain`; Jaws uses `grafana.jwall.engineering` in the
  `jwall.engineering` zone).
  - Terraform creates the A record with `ignore_changes` on its value.
  - At every boot the node upserts its current public IPv4 address with a
    60-second TTL.
  - IAM allows only `route53:ChangeResourceRecordSets`, limited by
    `route53:ChangeResourceRecordSetsNormalizedRecordNames` to that one
    name and by `…RecordTypes` to `A`.
  - There is no Elastic IP: one would bill $3.65 a month even while
    stopped.
- **Without a domain** the node is private and reached through a Session
  Manager port forward.
- **Grafana sign-in.**
  - Anonymous access and sign-up are off, and the admin user name is not
    the default.
  - The user name and password come from SSM SecureString parameters that
    the owner sets (section 8).
  - Grafana's brute-force protection stays on.
  - Changing the password parameter is applied on the next reconcile,
    because Grafana reads the variable only on first boot.

**Containers** (Docker Compose under systemd, with pinned image versions and
a memory limit each; exact values are the builder's)

| Service | Purpose |
|---|---|
| `caddy` | HTTPS (Let's Encrypt), security headers, reverse proxy to Grafana |
| `grafana` | Dashboards and all alerting (no Alertmanager), database in Postgres |
| `prometheus` | Host and service metrics. Retention is 365 days **and** a size cap (default 12 GB), so growth drops the oldest blocks instead of filling the disk |
| `node-exporter` | Host metrics, including vmstat (OOM kills), pressure (if the kernel exposes it), filesystem and inodes, plus a textfile directory |
| `cadvisor` | Per-container CPU, memory and restarts (trimmed to the metrics the dashboards use) |
| `postgres` | Databases `grafana` and `cost`. Grafana reads `cost` as a read-only user |
| `postgres-exporter` | Postgres up, connections and database sizes |
| `blackbox-exporter` | Probes the public HTTPS address: reachable, TLS expiry |
| `cost-sync` | Not long-running: started by a systemd timer every 30 minutes and at boot (section 6.6) |

- **Memory.** Every container has a limit, so no single service can take
  the node down. The swap file absorbs start-up spikes, mainly Prometheus
  replaying its write-ahead log. Everything should fit comfortably in 4 GiB
  (an estimate; the dashboard will show it).
- **Grafana data sources**, all provisioned:
  - Prometheus;
  - Postgres (`cost`);
  - CloudWatch, through the instance role, for the CPU credit balance and
    status checks.
- **Host textfile metrics.** Scripts that run at boot and every 6 hours
  write the running AL2023 release, whether a newer release exists
  (`dnf check-release-update`), and since when.

**Configuration delivery.** Dashboards and alert changes must not replace
the instance.

- The module renders a **config bundle**: the compose file, Prometheus
  configuration, Grafana provisioning (data sources, dashboards, alert
  rules, templates, contact points, policies and mute timings), budgets and
  the schedule.
- It uploads the bundle to a small, versioned module bucket,
  `<name>-monitoring-config`, keyed by content hash, and writes that hash
  to an SSM parameter.
- A reconciler on the node converges to the named bundle at boot, on a
  5-minute timer, and when Terraform changes it (SSM State Manager
  association, or the builder's equivalent). It validates the bundle, swaps
  it in, runs `compose up` and reloads, then writes `status` and
  `running-config` parameters, as `container-instance` does.
- User data only bootstraps: Docker, the data volume mount, swap and the
  reconciler.

### 6.6 Cost data on the node

`cost-sync` lists `normalized/`. For every `(provider, period)` whose object
version differs from the one loaded, it replaces that period's rows in
`cost.cost_lines` in one transaction. Then it:

- refreshes the daily rollups the dashboards read;
- loads the budgets from the bundle;
- reads the newest `_runs/` record;
- writes textfile metrics: last sync success, last normalizer run time and
  status, newest `ChargePeriodStart` for each provider, newest Databricks
  delivery.

At boot it runs before anything else reads the cost database, so data that
arrived while the node was off shows immediately.

The rollup schema and its views are the builder's: daily cost, month to
date, forecast, budget status and anomalies.

- **Forecast** = month to date plus the average daily spend of the last 7
  complete days, multiplied by the days left in the month.
- **"Complete day"** means at least 48 hours old. Newer days are labelled
  partial.

### 6.7 Dashboards

All dashboards are provisioned and read-only in the UI. They follow the
owner's prog-strength conventions
([reference](https://github.com/Prog-Strength/prog-strength-infra/tree/main/monitoring)):

- stat tiles that turn green, yellow or red;
- time series with dashed warning and critical lines (the same numbers the
  alert rules use);
- rows that each open with a short text panel;
- a description on every panel that states its thresholds;
- a 30-second refresh.

**Monitoring node · Host health** (last 6 hours)

```text
┌ CPU ─┬ Memory ┬ Root disk ┬ Data disk ┬ CPU credits ┬ Targets up ┬ Uptime ┐
▸ CPU       usage % (60/85) · CPU credit balance · load 1/5/15
▸ Memory    used % (70/90) · swap · OOM kills · memory pressure · memory by container (stacked)
▸ Disk      used % per volume (70/90) · days until full · inodes · Prometheus size vs its cap · Postgres size · I/O
▸ Services  targets up · container restarts · CPU by container · TLS days left · Grafana alert-evaluation errors
▸ Patching  newer AL2023 release available (days) · running release · last boot
▸ Pipeline  last sync · last normalizer run · newest AWS charge date · newest Databricks delivery · errors
```

**Cost · Overview** (last 90 days; variables: provider, account, project, environment)

```text
┌ Month to date ┬ Forecast vs budget ┬ Budget used ┬ Yesterday (partial) ┬ vs last month, same day ┬ Untagged ┐
▸ Trend          daily spend stacked by provider · monthly totals, last 12 months
▸ Where it goes  by project (bars, budget lines) · by service (top 10) · by account · by provider
▸ Budgets        one row per budget: budget · month to date · forecast · % used
▸ Movers         projects and services furthest above their 14-day norm
▸ Untagged       untagged spend by service and account; charges AWS never tags (public IPv4, tax) labelled as such
```

The "data as of" date (newest complete day) sits in the header.

**Cost · Project.** One project's spend by component, service and
environment, daily and month to date, against its budget.

**Cost · Databricks.**

- Spend and DBUs by product (jobs, SQL, serverless vs classic), by
  workspace and by SKU, labelled "list price".
- An **all-in** panel that adds the AWS cost of classic clusters' EC2 and
  storage. Those are AWS rows that carry the workspace's tags.

**Cost · Tasks.** One row per task run; see 6.12.

**Units.** Amounts are `BilledCost` in USD. Tax and credits stay as their
own `ChargeCategory` rows and are excluded from "untagged".

### 6.8 Alerts and Slack

All rules are Grafana-managed and provisioned in YAML, using the
prog-strength conventions:

- warning and critical pairs, each mirroring a panel through
  `__dashboardUid__` and `__panelId__`;
- one Slack message template, posting resolved messages too;
- a root policy grouped by folder and `alertname`, repeating every 4 hours;
- the rules validator, ported from `validate_rules.py`.

Every rule carries `area` (`host`, `pipeline` or `cost`) and `severity`.

**Routing.** A notification policy per `area` sends it to the configured
channel. Each channel is a contact point whose Slack incoming-webhook URL is
read from SSM. Adding a channel means one webhook and one line of
configuration.

**Default thresholds** (inputs; Jaws may override any of them):

| Rule | Warning | Critical |
|---|---|---|
| CPU used, 10 min average | 60 % | 85 % |
| CPU credit balance, share of the type's maximum | < 25 % | < 5 % |
| Memory used, 5 min | 70 % | 90 % |
| Swap used, 15 min | 25 % | 75 % |
| OOM kill | — | any |
| Disk used, each volume | 70 % | 90 % |
| Disk full forecast (last 24 h growth) | < 7 days | < 2 days |
| Inodes used | 70 % | 90 % |
| Prometheus size vs its cap | 85 % | — |
| Scrape target down, 2 min | — | any |
| Container restarts in 15 min | 1 | 3 |
| TLS certificate expiry | < 14 days | < 3 days |
| Grafana rule-evaluation failures, 10 min | any | — |
| Newer AL2023 release available (time for an AMI bump) | > 7 days | — |
| Last successful normalizer run | > 3 h | > 12 h, or the last run failed |
| Task run with no `finished` or `swept` record an hour past its max hours (a possibly leaked instance) | — | any |
| Task run's billed cost over its ceiling | — | any |
| Newest AWS charge date | > 3 days old | > 5 days old |
| Newest Databricks delivery | > 36 h old | > 60 h old |
| Last successful `cost-sync` | > 2 h | > 6 h |
| Budget: month-end forecast (total, account or project) | over budget | — |
| Budget: month to date | — | over budget |
| Day's spend vs the median of the 14 complete days before it, for the total and each project. The amount above the median must also exceed `anomaly_floor_usd` (default $2). The newest day is evaluated as soon as it has data, because partial data only undercounts | 2× | 4× |
| New untagged spend: rows with no `x_Project` (tax and credits excluded) from an account and service pair that had none in the previous 14 days, over $0.50 a day. Steady charges AWS never tags, such as public IPv4, don't re-alert | any | — |

**Task spend stays in the anomaly rule** (the owner's choice): the owner
wants to hear about every expensive run. Before a planned big or overnight
run, they add a temporary **silence** in Grafana's UI. Silences are
operational state and allowed even though the rules are provisioned. To
change a rule for good, they edit its threshold in `config.yaml`.

Rules that depend on data from AWS (credits, status) use
`execErrState: Alerting`. Pressure-stall metrics are used only if the
AL2023 kernel exposes them. Otherwise the panel is hidden and there is no
rule.

### 6.9 The watchdog (outside the node)

Without this, a dead node would never report its own death. It is on
whenever Slack is configured.

- **CloudWatch alarms.**
  - `StatusCheckFailed_System` triggers the EC2 `recover` action.
  - `StatusCheckFailed_Instance` triggers `reboot`.
  - Both also notify an SNS topic, and both treat missing data as not
    breaching, so a scheduled stop is silent.
- **The watchdog Lambda** (Python, standard library plus boto3) is
  triggered by that topic and by EventBridge Scheduler every 5 minutes.
  - Not running when it should be: critical, after a 15-minute grace
    period following a scheduled start.
  - Running inside its off window: warning. It catches a stop that failed
    and is quietly costing money.
  - With a domain, it fetches `https://<domain>/api/health`. Two
    consecutive failures are critical.
  - It keeps its state in an SSM parameter: it posts once, repeats every 4
    hours, and posts when the problem resolves.
  - It posts to the `host` channel's webhook.

### 6.10 Off-hours schedule (optional; 24/7 by default)

`schedule` defaults to none, which means always on. Any caller can add one.
Jaws sets 08:00 to midnight every day in `America/Denver`, which keeps the
node off from 00:00 to 08:00 while the owner is asleep:

```hcl
schedule = {
  timezone = "America/Denver"
  days     = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
  on       = "08:00"
  off      = "24:00"
}
```

- **Allowed shapes only:**
  - whole hours;
  - `on` before `off` on the same day, so no overnight windows. `off` may
    also be `24:00`, meaning midnight at the end of that day. Its stop
    then fires at 00:00 on the following weekday, and the module shifts
    the stop schedule's days by one to match;
  - at least 4 hours on;
  - one or more unique weekdays.
  - Raw cron is deliberately not accepted.
- **Mechanism.** Two EventBridge Scheduler schedules call
  `ec2:StartInstances` and `ec2:StopInstances` on this one instance. Stop
  is a normal shutdown, so compose services stop cleanly under systemd.
- **Side effects:**
  - Grafana gets a mute timing for the first 15 minutes after each
    scheduled start.
  - The watchdog reads the same schedule.
- **Savings.** Jaws's 08:00 to midnight every day saves a third of the
  instance and IPv4 costs, about $9.40 a month. Weekdays 08:00 to 20:00
  would save about 64%, around $18. Disks are still billed.
- **Nightly work moves inside the window.** With a schedule, the
  data-volume snapshot is taken during the off window, so it captures disks
  that were shut down cleanly. The module converts the time to UTC for Data
  Lifecycle Manager. The patching scripts run at boot and every 6 hours
  instead of nightly.
- **Times to avoid.** Daylight-saving changes happen between 01:00 and 03:00
  in most zones, so a start or stop in that window can be skipped or run
  twice once a year. Jaws's times stay clear of it.
- **CPU credits.** T4g keeps earned credits for 7 days while stopped. Verify
  that T9g does the same; the T9g announcement says it uses the same credit
  system.

### 6.11 Recovery

| Event | What happens | What's lost |
|---|---|---|
| Scheduled stop and start | Disks persist. Services start, `cost-sync` catches up and DNS is upserted | Host metrics for the off hours (a gap) |
| Reboot or EC2 recovery | Same disks, same instance | Minutes of metrics |
| Instance replaced (AMI, or a terminated instance) | The new instance reattaches the data volume and continues | Minutes of metrics |
| Data volume lost | Postgres rebuilds from `normalized/`; dashboards and alerts are reprovisioned; Grafana users other than the admin must be re-added | Prometheus history since the last snapshot (none if snapshots are off) |
| Node down for days | Exports, the Databricks job and the normalizer keep filling the bucket | Nothing in the bucket |

### 6.12 Task runs: cost per run

The owner runs a lot of GPU training through `jaws task run` and wants one
row per run, with its cost and its metadata.

**Run records (a Jaws source).** `jaws task run` writes a JSON record when
the instance launches and another when the task ends. `task sweep` writes
one when it terminates a leaked instance. They go to
`raw/provider=jaws/source=task-runs/project=<p>/date=YYYY-MM-DD/<run-id>.<task-id>.<event>.json`.
Each record is write-once, like every raw delivery. Each project's
`ci-task` role may `PutObject` only under its own `project=` prefix.

- **`started`:**
  - who launched it: repository, workflow, run id and attempt, task id,
    pull request, commit;
  - what it runs on: profile, instance type, GPU count, market, zone,
    instance id;
  - its prices and limits: the hourly price paid at launch (spot or on
    demand), the on-demand price, worst-case cost, ceiling, max hours;
  - its campaign, if any (below);
  - when it launched.
- **`finished`:** ended at, outcome (`passed`, `failed`, `interrupted`, …),
  exit code, interrupted at, and the GPU, driver and CUDA versions from the
  environment block.
- **`swept`:** terminated at and the reason.

**The module stays generic.** The normalizer has a `runs` source type with
a documented schema, `runs-1`. Jaws is simply its first writer.

- A run key made of the tag values that billing rows are joined on. The
  `run_join_tags` input is `RunId` and `TaskId` in Jaws.
- Standard fields: project, campaign, kind (the workflow), started, ended,
  outcome, instance type, accelerator count, market, hourly price,
  on-demand price, ceiling, links.
- Free-form `attributes` for anything else.

The output is `normalized/schema=runs-1/billing_period=YYYY-MM/data.parquet`.

**Cost per run.**

- In Postgres, a run's billed cost is the sum of the cost rows whose `Tags`
  carry its `RunId` and `TaskId`: the instance and its volume.
- The run's public IPv4 address is untagged (AWS never tags it) and is left
  out. It is a cent an hour at most.
- Until the bill arrives (one to two days), the table shows an estimate
  instead, marked `~`: duration × the hourly price at launch.
- Runs from before the records existed still appear. They are built from
  their tags alone (project, workflow, profile, lifecycle, run, task),
  without the launch metadata.

**Campaigns.** A campaign is a set of runs toward one goal, such as a
data-generation push made of many small spot runs, some of them
interrupted and retried.

- **Naming one.** The caller names it at launch with
  `task run --campaign <slug>`, or with the reusable workflow's `campaign`
  input. It's optional. A slug is lowercase letters, digits and hyphens, up
  to 63 characters.
- **Where it's recorded.** It goes in the `started` record. It also goes on
  the instance and its volume as a `Campaign` tag, which the
  `billing-export/` root activates as a cost allocation tag.
  - So billing rows carry it too: cost still groups by campaign when a
    run's record failed to write.
  - `jaws cost report` can group by it.
- **No registry in v1.** The name is the campaign. Declared campaigns, with
  a description, a budget and a budget alert, can come later without
  changing the records.

**Cost · Tasks** dashboard (last 30 days; variables: project, campaign,
workflow, profile, outcome, market)

```text
┌ Task spend (month) ┬ GPU spend (month) ┬ Runs ┬ GPU-hours ┬ Interrupted runs' cost ┬ Avg cost per run ┐
▸ Campaigns   one row per campaign (below); a click filters the runs table to it
▸ Runs        one row per run, newest first (below)
▸ By workflow daily task spend stacked by workflow · totals by project, workflow and task
▸ Efficiency  spot vs on-demand share · cost per GPU-hour by instance type · % of ceiling used
```

Campaigns:

| Campaign | Project | First run | Last run | Runs | Passed / failed / interrupted | Instance-hours | GPU-hours | Cost | Saved vs on demand | Cost per passed run |
|---|---|---|---|---|---|---|---|---|---|---|
| datagen-2026-12 | braveheart-selfplay | Dec 1 | Dec 6 | 48 | 39 / 2 / 7 | 192 | — | $214.30 | $301.10 (58 %) | $5.49 |

Runs:

| Started (MT) | Project | Campaign | Workflow | Task | Run | PR | Commit | Profile | Instance | GPUs | Market | Zone | Duration | Outcome | Cost | Ceiling | % of ceiling | $/GPU-hour |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Nov 24 21:10 | braveheart-trainer | net-v12 | train | net-v12 | 123456·1 ↗ | #88 | `a1b2c3d` | gpu | g6e.xlarge | 1 | spot | use1-az4 | 5 h 42 m | passed | ~$6.10 | $50 | 12 % | ~$1.07 |

(The values are made up.) "Saved vs on demand" compares each run's
duration × its on-demand price with what was billed.

- **Links:** Run opens the GitHub Actions run, PR the pull request, and
  Commit the commit.
- **Colors:** Outcome is colored. % of ceiling turns yellow at 75% and red
  at 100%.
- **Alerts:** two rules in 6.8 watch task runs: a possibly leaked instance,
  and billed cost over the ceiling. Records are written the moment a run
  starts, and the normalizer runs hourly, so the leak rule fires within
  about 90 minutes of the run's max hours plus one hour.

## 7. Modules

There is a new family, **`terraform-aws-jaws-monitoring`**, in
`Jaws-Platform` (registry `Jaws-Platform/jaws-monitoring/aws`). It has the
same layout and tooling as `terraform-aws-jaws-lichess-bot`: submodules,
examples, mock-provider tests, Release Please and the release bot. The
owner publishes it in HCP Terraform.

| Submodule | Applied by | Purpose |
|---|---|---|
| `billing-bucket` | Jaws foundation | 6.1 |
| `aws-billing-export` | owner root `billing-export/` | 6.2 |
| `billing-normalizer` | `monitoring/` stack | 6.4 |
| `monitoring-node` | `monitoring/` stack | 6.5–6.11 |

`terraform-aws-jaws-databricks` gains **`databricks-billing-export`**
(6.3), which includes the writer role, the service credential, the
principal and its grants.

**The optional-feature rule.** A feature is off until its input is given.
Host monitoring is always on.

| Feature | Input | Off when |
|---|---|---|
| Public HTTPS | `domain`, `zone_id` | null: private, reached through Session Manager |
| Cost (sync, cost dashboards, cost rules) | `cost = { bucket, normalized_prefix, budgets, anomaly_floor_usd }` | null: a host-only node |
| Slack notifications and the watchdog | `slack = { channels = { name = ssm_parameter }, routes = { area = channel } }` | null: dashboards only |
| Off-hours | `schedule` | null: 24/7 |
| Snapshots | `snapshots` | false |
| Extra dashboards and rules | `extra_dashboards`, `extra_alert_rules` | empty |
| Normalizer providers | `providers` | each provider is listed or not |

The modules name nothing in Jaws. Names come from `name` or `bucket_name`
inputs, and tags from `default_tags`. Defaults are generic (for example
`instance_type = "t9g.medium"`, `data_volume_gb = 30`), and
`thresholds` defaults to the table in 6.8.

## 8. Jaws integration

**`config.yaml`** (platform-owned; projects can't set any of this)

```yaml
monitoring:
  instance_type: t9g.medium
  ami: al2023-ami-<release>-arm64   # pinned image name; patching is a PR that bumps it
  domain: grafana.jwall.engineering
  snapshots: true
  schedule:                  # off while the owner sleeps; omit for 24/7
    timezone: America/Denver
    days: [mon, tue, wed, thu, fri, sat, sun]
    on: "08:00"
    off: "24:00"             # midnight; off 00:00–08:00 MT
  cost:
    bucket: jaws-billing     # jaws-billing-570327089884 if the plain name is refused
    protect_raw: false       # true once the first deliveries are checked (section 10)
    aws: true
    databricks: true
    budgets:                 # optional, USD per month
      total: 100
      projects: {}
      accounts: {}
    anomaly_floor_usd: 2
  slack:
    channels:
      platform: /jaws/monitoring/slack/platform
      costs: /jaws/monitoring/slack/costs
    routes: { host: platform, pipeline: platform, cost: costs }
  # thresholds: optional overrides of the module defaults (6.8)
```

- **`settings.py`.**
  - Adds a `MonitoringSection` (Pydantic) that validates the schedule rules
    from 6.10, including timezones with `zoneinfo`, the channel and route
    references, and positive budgets.
  - Project files get no monitoring keys (a test checks).
  - `tests/fixtures/config.yaml` stays identical to `config.yaml`.
- **Foundation.**
  - `billing_bucket`, present when `monitoring.cost` is set; its policy
    names `management.account_id`.
  - `databricks_billing_export`, present when `cost.databricks` is set and
    Databricks is enabled.
  - The plan and apply roles for the monitoring stack (like
    `data_access_ci_*`), and the stack's entry in `state_prefix_access`.
  - A new policy set in `terraform-aws-jaws-ci`'s catalog for what the
    monitoring stack manages: EC2, EBS, DLM, VPC, IAM roles under its
    prefix, Lambda, Scheduler, CloudWatch, SNS, S3 on its config bucket,
    SSM under `/jaws/monitoring/`, and the one Route 53 record.
  - New `foundation.tftest.hcl` runs.
- **`monitoring/`** is a new top-level stack, like `data-access/`. It reads
  `config.yaml` and applies `monitoring-node` and `billing-normalizer`. Its
  workflow plans on PRs and applies in the release apply job (`prod`
  environment), following `data-access.yml`.
- **`billing-export/`** is a new owner root in the management account.
  `tests/` checks that no CI role or state prefix references it, as with
  `owner-access/`.
- **CLI.** `jaws monitoring secrets set <name>` and `secrets check`,
  mirroring `bot secrets` (no-echo prompt, SecureString):
  - `grafana-admin-user`
  - `grafana-admin-password`
  - `slack/<channel>`

  All live under `/jaws/monitoring/`. The parameters belong to the owner
  and are not managed by Terraform. The node and the watchdog report
  `missing secret <name>` in their status if one is absent.
- **Tasks.** `task run` writes the `started` and `finished` records, and
  `task sweep` writes `swept` (6.12).
  - `task run --campaign <slug>` and the reusable workflow's `campaign`
    input put the `Campaign` tag on the instance and its volume, and the
    slug in the record. The `ci-task` role's tag conditions must allow the
    `Campaign` key.
  - The foundation grants each project's `ci-task` role `s3:PutObject` on
    its own `raw/provider=jaws/source=task-runs/project=<project>/` prefix,
    and nothing else in the bucket.
  - The GPU count comes from the instance type. Add
    `ec2:DescribeInstanceTypes` if the role lacks it.
  - A failed record write is logged as a warning and never fails or delays
    the task.
  - `docs/remote-tasks.md` documents the records.
- **Docs.** A new `docs/monitoring.md` (operations, recovery, adding a
  provider, adding a channel), plus `docs/billing-export.md`. Update
  [costs.md](../../costs.md): `cost report` stays as the ad hoc tool and
  points to the dashboards. Update the README's stack list.

## 9. Cost (monthly, us-east-1, running 24/7)

| Item | Estimate |
|---|---|
| `t9g.medium` | ~$24.50 if priced like `t4g.medium` (T9g's price is unverified) |
| Public IPv4 address | $3.65 |
| Data volume, 30 GB gp3 | $2.40 |
| Root volume, 12 GB gp3 | $0.96 |
| Snapshots (7 daily, incremental) | < $1 |
| CloudWatch: 2 alarms, credit and status reads | < $0.50 |
| Databricks serverless job | ~$0.50–3 (measure) |
| Lambda, Scheduler, SNS, S3 | cents (free tiers; the bucket grows about 1 GB a year) |
| **Total, 24/7** | **about $33–36** |
| **Total with Jaws's schedule (on 16 hours a day)** | **about $24–27** |

Ways to trim: turn snapshots off (about $1), shrink the data volume to
20 GB ($0.80), add a schedule (up to about $18), or drop to `t9g.small` if
the dashboards show memory to spare.

## 10. Rollout

Each step that spends money is a release the owner merges.

1. Build the `terraform-aws-jaws-monitoring` modules and
   `databricks-billing-export`, then release them.
   - **Owner:** publish the new family in HCP Terraform.
2. **Owner:** create the Slack incoming webhooks, then run
   `jaws monitoring secrets set` for those and the Grafana credentials.
3. Jaws PR: settings, foundation (bucket, Databricks job, roles), the
   `billing-export/` root, the `monitoring/` stack, CLI and docs.
   - **Owner:** merge, then release. The foundation applies the bucket and
     the job.
4. **Owner:** apply `billing-export/` in the management account. The first
   delivery arrives within about 24 hours. Then:
   - request the AWS backfill (12.9);
   - run the Databricks job once with `periods = all`.
5. The monitoring stack applies, the node comes up, and Grafana is served
   at the domain. Spending starts here.
6. Check: the dashboards fill, a test alert reaches each channel, the
   watchdog fires on a manual stop, and a stop and start keeps the data.
7. Once the first AWS delivery and Databricks run have landed under the
   right prefixes, set `protect_raw: true` (a config PR and a release).
   From then on nothing under `raw/` can be deleted.

## 11. Decisions

**The owner's:**

- Approach 2: the normalizer runs in a Lambda, and the node only displays.
- Everything runs in production, except the org-wide FOCUS export, which
  the owner applies in the management account.
- Databricks billing comes from a daily serverless job in `jaws-shared`,
  optional and on.
- The bucket keeps raw data forever and is write-only, with a prefix per
  provider and source.
- Postgres on the node is a rebuildable cache.
- Grafana is served over public HTTPS with sign-in credentials kept as
  secrets.
- `t9g.medium`, set by Jaws configuration only. Projects can never control
  it.
- Host monitoring must be thorough, especially disk growth and memory at
  start-up, in the prog-strength style.
- Cost alerts are the budget forecast, the daily anomaly and untagged
  spend, with next-morning latency accepted.
- Task spend stays in the anomaly alert. The owner wants to hear about
  every expensive run, and silences it in Grafana before a planned one.
- A task-run table: cost per run, with its project, task and launch
  metadata, for the GPU training ahead.
- A campaign layer above runs, for pushes made of many small, often
  interrupted, spot runs.
- Backfill where the providers allow it (a nice-to-have).
- One org-wide export from the payer, kept rather than per-account exports
  run by Jaws: it covers every account, including ones added later, and
  the history that sits in the management account.
- 24/7 by default in the module, with an optional, limited off-hours
  schedule. Jaws runs the node on a daily schedule that skips the owner's
  sleep hours: on 08:00 to midnight, `America/Denver`, so off from 00:00
  to 08:00 MT.
- Features are optional in the modules, and Jaws's inputs are the
  enforcement boundary.
- v1 covers cost and the node's own health only; project metrics come
  later.
- A running cost of about $30 a month.

**My calls** (please check these):

- The bucket is named `jaws-billing`, with the layout in 6.1.
- Databricks deliveries are billing-period snapshots under
  `billing_period=…/run=…`, so both sources follow the same contract.
- The Databricks job is defined in Terraform rather than as a bundle, runs
  as a dedicated service principal, and writes through a service
  credential.
- The bucket and the job belong to the foundation; the node and the
  Lambdas belong to a new `monitoring/` stack.
- The normalizer runs hourly and `cost-sync` every 30 minutes.
- Task-run records are a Jaws source (`provider=jaws`), written by
  `task run` and `task sweep`, with the generic `runs-1` schema so that the
  module stays free of Jaws. Cost per run shows an estimate until the bill
  arrives.
- Two new task-run rules: a possibly leaked instance, and billed cost over
  the ceiling.
- A campaign is an optional slug given at launch, recorded in the record
  and as a `Campaign` cost allocation tag, with no registry in v1.
  Campaign budgets can come later.
- Grafana keeps its own database in Postgres rather than SQLite.
- All alerting runs in Grafana, with no Alertmanager.
- The separate 30 GB data volume and the size-capped, 365-day Prometheus
  retention.
- The node updates its own DNS record instead of using an Elastic IP.
- Config bundles go to S3 and a reconciler applies them, so dashboard
  changes never replace the instance.
- The default threshold values in 6.8, and the forecast formula.
- `extra_dashboards` and `extra_alert_rules` as extension hooks.
- The cost estimate: about $33–36 at 24/7, a little above the earlier
  "about $31" once the root volume and the Databricks job are counted. That
  becomes about $24–27 on Jaws's schedule.
- The bucket name `jaws-billing`, with the account-suffixed fallback.
  Deletes under `raw/` are blocked only after the first deliveries have
  been checked.
- Patching by AMI bump (PR, release, replacement), following Jaws's
  existing AMI pins, instead of in-place upgrades. The patch alert is
  "newer AL2023 release available".
- "Untagged" means *new* untagged spend, as agreed, so steady charges AWS
  can't tag don't alert every day. Databricks rows without a `Project` tag
  take it from their workspace.
- The anomaly rule applies to the total and to each project. Its floor
  applies to the amount above the median, and it evaluates partial days as
  soon as they arrive.
- `t4g.medium` as the fallback if T9g fails verification.

## 12. Verify at build start

Check each of these before relying on it; each has a fallback.

1. **Cross-account destination.** Does the Terraform AWS provider's
   `aws_bcmdataexports_export` support a cross-account destination (GA
   2026-04-14)? Fallback: the `awscc` provider, or the owner creating the
   export once by CLI and the root importing it.
2. **FOCUS 1.2 details.** The FOCUS 1.2 table name and its
   `TIME_GRANULARITY` option. The "create new" folder layout and manifest
   the normalizer reads.
3. **Writing from serverless jobs.** Can serverless jobs compute use a
   Unity Catalog service credential to `PutObject` with boto3? Fallback:
   an external volume over `staging/`.
4. **Workspace names.** A Databricks system table with workspace names.
   Fallback: a `workspace_names` input.
5. **T9g.** Price in us-east-1, which availability zones offer it, AL2023
   support, maximum credits per size, and credit retention while stopped.
   Fallback: `t4g.medium`, if T9g isn't offered in a usable zone or its
   price would push the scheduled total above $30.
6. **The pandas layer.** The ARN of the AWS SDK for pandas layer for
   Python 3.13 on arm64. Fallback: package pyarrow.
7. **SQL alerting.** Grafana alerting on Postgres queries in table form.
   Fallback: queries in time-series form.
8. **Pressure metrics.** Whether pressure-stall (PSI) metrics are on in
   the AL2023 kernel.
9. **History (backfill; a nice-to-have, wanted by the owner).**
   - **AWS.** After the first delivery, the owner opens a free AWS Support
     billing case naming the management account, the export and the months
     wanted. Most sources say up to 36 months; one AWS guide says 14. It
     takes up to 24 hours and lands under the export's prefix like any
     other delivery.
   - **Known limit:** a backfill can't include data from before an
     organization structure change, and the production and development
     accounts joined this year.
   - **AWS fallback:** a one-time `jaws cost backfill`, run by the owner
     with management credentials. It pulls about 13 months of daily Cost
     Explorer data (account, service, `Project`) into
     `raw/provider=aws/source=cost-explorer/` for a few cents. The
     normalizer uses it only for periods the export doesn't cover.
   - **Databricks.** `system.billing.usage` keeps history indefinitely, so
     a one-time run of the job with `periods = all` exports every past
     period.

## 13. Left to the builder

- Image versions, memory limits, and retention numbers within the stated
  caps.
- The Postgres schema, views and indexes, and the exact panel queries.
- The Databricks product-to-`ServiceCategory` mapping.
- The reconciler's mechanics, within the contract in 6.5.
- Test layout: mock-provider tests for every submodule, normalizer unit
  tests against fixture deliveries (AWS FOCUS samples, Databricks usage
  with retractions), schedule validation tests in both Terraform and
  Python, and the rules validator run in CI.
- **Later (not v1).** A way for projects to send metrics (remote write or
  scrape over the same HTTPS address, authenticated). Keep the Caddy and
  Prometheus configuration free of assumptions that would block it.
