# Monitoring and costs

The monitoring and cost platform is one node, serving Grafana at
[grafana.jwall.engineering](https://grafana.jwall.engineering), that shows
every provider's spend next to its own health and posts to Slack; the billing
bucket every bill lands in; and the pipeline that fills it. It costs about
$24 to $27 a month on its schedule ([Cost](#cost)). The design is
[the spec](superpowers/specs/2026-11-21-monitoring-node-design.md); its
settings are [`config/monitoring.yaml`](../config/monitoring.yaml), which only
this repository can change (no project file can set any of it).

The modules are the [`jaws-monitoring`
family](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/tree/v0.8.1),
v0.8.1. Their READMEs hold the detail (every rule, panel, table and input), and
this page links to them rather than repeating it.

Contents: [what runs](#what-runs), [configuration](#configuration),
[how it is applied](#how-it-is-applied),
[first-time setup](#first-time-setup), [secrets](#secrets),
[reaching Grafana](#reaching-grafana), [the schedule](#the-schedule),
[dashboards and alerts](#dashboards-and-alerts),
[the watchdog](#the-watchdog), [recovery](#recovery),
[adding a cost provider](#adding-a-cost-provider),
[adding a Slack channel](#adding-a-slack-channel), [cost](#cost),
[known gaps](#known-gaps).

## What runs

```text
 management account                 production account
 jaws-focus-daily export ──daily──► s3://jaws-billing-570327089884/raw/provider=aws/…
                                    raw/provider=databricks/…   ◄── the Databricks billing job, daily
                                    raw/provider=jaws/…         ◄── task run, task sweep
                                          │
                                          ▼  jaws-monitoring-normalizer, hourly
                                    normalized/
                                          │
                                          ▼  cost-sync, at boot and every 30 minutes
                                    jaws-monitoring: Caddy, Grafana, Postgres, Prometheus ──► Slack
                                    jaws-monitoring-watchdog, every 5 minutes              ──► Slack
```

| Part | Name | Defined in | Applied by |
| --- | --- | --- | --- |
| The billing bucket | `jaws-billing-570327089884` | `foundation/monitoring.tf` | the release's foundation apply |
| The Databricks billing job | `jaws-databricks-billing-export`, on the shared workspace, daily at 06:00 UTC | `foundation/monitoring.tf` | the release's foundation apply |
| The stack's CI roles | `jaws-monitoring-ci-plan`, `jaws-monitoring-ci-apply` | `foundation/monitoring.tf` | the release's foundation apply |
| The node's VPC | `jaws-monitoring`: one public subnet in `us-east-1a`, no NAT | `monitoring/` | the release's apply, after the foundation |
| The normalizer | `jaws-monitoring-normalizer` (Lambda, hourly) | `monitoring/` | the same |
| The node | `jaws-monitoring`, its data volume `jaws-monitoring-data`, the snapshot vault `jaws-monitoring-snapshots`, the config bucket `jaws-monitoring-config-570327089884` | `monitoring/` | the same |
| The watchdog | `jaws-monitoring-watchdog` (Lambda) and two status-check alarms | `monitoring/` | the same |
| The organization's AWS bill | the `jaws-focus-daily` export, in the management account | `billing-export/` | the owner ([docs/billing-export.md](billing-export.md)) |

The durable half, the bucket and the job, is the foundation's; the
replaceable compute is the monitoring stack's, so the stack can be destroyed
and rebuilt without touching any billing history. Everything the stack creates
is named `jaws-monitoring…` and tagged `Project = monitoring`, which its CI
roles are scoped to.

- **The node** is a `t9g.medium` on a pinned Amazon Linux 2023 arm64 image,
  reached through Session Manager (no SSH key). Docker Compose runs Caddy
  (HTTPS from Let's Encrypt), Grafana on Postgres, Prometheus, node-exporter,
  cAdvisor, postgres-exporter and a probe of its own HTTPS address. Its state
  lives on the 30 GB data volume, which is kept when the instance is replaced:
  Prometheus's history, Postgres (Grafana's database and the `cost`
  database), Grafana's plugins and Caddy's certificates. The security group
  admits 443 and 80 only, and the node writes its own A record at every boot,
  because its public address changes on every start (there is no Elastic IP).
- **Its configuration** (compose file, Prometheus, every dashboard, rule,
  contact point and policy) is one content-addressed bundle in the config
  bucket. A reconciler on the node applies it at boot and every 5 minutes, so a
  dashboard, alert or channel change never replaces the instance
  ([how a change rolls out](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.1/modules/monitoring-node/README.md#how-a-change-rolls-out)).
- **The normalizer** rebuilds each billing period whose newest delivery
  changed, from `raw/` into FOCUS-aligned rows under `normalized/`, and the
  task-run records into an event table
  ([billing-normalizer](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.1/modules/billing-normalizer/README.md)).
  The bucket stays complete whether the node is up, stopped or gone, and
  `cost-sync` on the node loads whatever changed into Postgres.

## Configuration

`config/monitoring.yaml` holds the one `monitoring` section. Jaws's values:

| Key | Jaws | What it does |
| --- | --- | --- |
| `instance_type` | `t9g.medium` | The node's type, a Graviton (arm64) type. Changing it stops, modifies and starts the instance |
| `ami` | `al2023-ami-2023.12.20261026.1-kernel-6.18-arm64` | The pinned Amazon Linux 2023 arm64 image, by name. Bumping it replaces the instance, which is how the node is patched ([below](#replacing-the-instance-patching)) |
| `domain` | `grafana.jwall.engineering` | Grafana over HTTPS at this name, in the `dns` zone of `config/sites.yaml`. Left out, the node is private, reached through Session Manager |
| `snapshots` | `true` | Daily snapshots of the data volume (AWS Backup), kept 7 days |
| `schedule.timezone` | `America/Denver` | The schedule's IANA time zone |
| `schedule.days` | `[mon, tue, wed, thu, fri, sat, sun]` | The days it runs |
| `schedule.on` | `"08:00"` | When the node starts |
| `schedule.off` | `"24:00"` | When it stops: midnight, so it is off from 00:00 to 08:00 |
| `cost.bucket` | `jaws-billing-570327089884` | The billing bucket, which the foundation creates. Bucket names are global, so it carries the account ID |
| `cost.protect_raw` | `false` | Deny every delete under `raw/`. Becomes `true` once the first deliveries are checked ([first-time setup](#first-time-setup)) |
| `cost.aws` | `true` | The organization's AWS bill, which `billing-export/` delivers |
| `cost.databricks` | `true` | Databricks billing, from the foundation's job on the shared workspace (once Databricks is enabled and its shared host recorded) |
| `cost.budgets.total` | `100` | The monthly budget, in USD. `budgets.projects` and `budgets.accounts` (by account ID or name) take budgets too; Jaws sets none |
| `cost.anomaly_floor_usd` | `2` | A day must also be this many USD above its 14-day median to count as an anomaly |
| `slack.channels` | `platform: /jaws/monitoring/slack/platform`, `costs: /jaws/monitoring/slack/costs` | Each channel, and the SSM parameter holding its webhook URL ([secrets](#secrets)) |
| `slack.routes` | `{ host: platform, pipeline: platform, cost: costs }` | The channel each area's alerts go to. `host` is required, and takes every area without a route |
| `thresholds` | none: the module's defaults | Alert thresholds overridden by name ([below](#dashboards-and-alerts)) |

Every key but `ami` is optional, and a part left out is off: without
`schedule` the node runs all day, without `slack` alerts stay in Grafana, and
without `domain` the node is private. The stack refuses to plan without `cost`,
because the root module always runs the normalizer. Without the whole section
Jaws builds none of the platform: the foundation creates no bucket or roles,
and the CI plan and the release apply skip the stack.

The CLI validates the section (`MonitoringSection` in `src/jaws/settings.py`)
whenever it loads `config/`, so a bad value fails the pull request's checks
with the key named:

- **The schedule** takes whole hours, quoted (`"08:00"`: YAML reads a bare
  `08:00` as a number of minutes), with `on` before `off` on the same day, so
  there is no overnight window (`off` may be `24:00`, the midnight that ends
  the day). It runs at least 4 hours, lists no day twice, is never `00:00` to
  `24:00` (leave out `schedule` instead), and has an IANA time zone. Keep
  starts and stops out of 01:00 to 03:00, when daylight saving changes: one
  there can be skipped or doubled once a year.
- **Slack:** every route names a channel, `routes.host` is set, and every
  channel's parameter is under `/jaws/monitoring/`.
- **Cost:** budgets above 0, an anomaly floor of at least 0, at least one
  provider on, and a valid bucket name.
- **The node:** `ami` is an AL2023 arm64 image name (not an ID),
  `instance_type` a Graviton type, and `domain` a name in the `dns` zone.
- **Thresholds:** each is one of the module's, and a warning-and-critical pair
  states both.

## How it is applied

- **Merging a pull request changes nothing in AWS.** On every pull request,
  `ci.yml` runs **Monitoring stack validate, tflint, test** (against mock
  providers, with no credentials) and **Monitoring plan**, which plans with
  `jaws-monitoring-ci-plan` and posts the sticky `jaws/monitoring` plan
  comment. Until the release that creates that role, the plan is skipped with
  a notice.
- **Merging the release PR applies it.** The Release workflow's apply job, in
  the `prod` environment, applies `foundation/`; its monitoring-apply job, also
  in `prod` and needing it, then applies `monitoring/` with
  `jaws-monitoring-ci-apply`. A failed foundation apply skips the stack, so the
  first release creates the roles, the bucket and the Databricks job, then the
  stack; a failed monitoring apply does not hold back the CLI image.
- **Never from a shell, never by an agent.** Nobody runs `terraform apply` in
  `monitoring/` ([AGENTS.md](../AGENTS.md)). Locally, with no credentials:
  `cd monitoring && terraform init -backend=false && terraform validate && terraform test`.
- **State:** `project=monitoring/env=prod/monitoring-prod.tfstate` in the
  shared state bucket, reachable only by the stack's two roles and the
  break-glass admins.

What a change does once it is applied:

| Change | What the node does |
| --- | --- |
| Dashboards, rules, thresholds, budgets, channels or routes (a config change or a module release) | Converges to the new bundle within 5 minutes, recreating only the containers whose files changed |
| A rotated secret | Picks it up within 5 minutes |
| `instance_type` | Stops, changes type and starts, on the same disks |
| `ami`, or the module's bootstrap | Replaced by a new instance, which reattaches the data volume ([below](#replacing-the-instance-patching)) |
| `schedule` | New start and stop times, mute timing and snapshot time |

[monitoring/README.md](../monitoring/README.md) lists where each of the
stack's inputs comes from.

## First-time setup

The owner's steps, in order. Steps 1 to 3 come before the release; spending
starts at step 4.

1. **Create the Slack webhooks.** In Slack, create an incoming webhook (a
   Slack app with *Incoming Webhooks* on) for each channel in
   `monitoring.slack.channels`: one for the channel that takes host and
   pipeline alerts and the watchdog's posts (`platform`), and one for cost
   alerts (`costs`).
2. **Set the secrets** ([below](#secrets)): the Grafana admin's user name and
   password, and both webhooks. Then `jaws monitoring secrets check`. Until
   they exist, the node reports `failed:missing secret <parameter>` and starts
   nothing new.
3. **Activate the `Campaign` and `Workspace` cost allocation tags** in the
   management account ([docs/billing-export.md](billing-export.md#follow-ups)).
4. **Merge the release PR.** The foundation creates the billing bucket, the
   Databricks job and the stack's roles; then the stack comes up, and Grafana
   answers at its domain within minutes.
5. **Apply `billing-export/`** ([docs/billing-export.md](billing-export.md)).
   The first AWS delivery lands within about 24 hours. After it, the AWS
   Support backfill is optional.
6. **Backfill Databricks.** Run the `jaws-databricks-billing-export` job on
   the shared workspace once by hand with the job parameter `periods` set to
   `all` (the job's **Run now with different parameters**). Its daily runs
   export only the current and the previous month.
7. **Check it works:** the dashboards fill (cost data a day or so after the
   first deliveries), a test alert reaches each channel, a stop by hand during
   the day brings the watchdog's "Monitoring node not running" and a start
   resolves it, and a stop and start keeps the data.
8. **Set `cost.protect_raw: true`** in a pull request, then release, once the
   first AWS delivery and the first Databricks run have landed under their
   prefixes and nothing has landed elsewhere. From then on nothing under
   `raw/` can be deleted, a misplaced object included.

## Secrets

The stack reads four secrets from SSM Parameter Store, all SecureStrings
under `/jaws/monitoring/`: the Grafana admin's user name and password, and one
webhook per Slack channel. They belong to the owner: Terraform never creates,
reads into state or changes them, and the node and the watchdog report
`missing secret <name>` while one is absent.

| Name | Parameter | What it is |
| --- | --- | --- |
| `grafana-admin-user` | `/jaws/monitoring/grafana-admin-user` | Grafana's admin user name |
| `grafana-admin-password` | `/jaws/monitoring/grafana-admin-password` | Its password; a new value is applied at the node's next reconcile |
| `slack/<channel>` | the channel's value in `monitoring.slack.channels` | The channel's Slack incoming-webhook URL, one per channel in `config/monitoring.yaml` (`slack/platform`, `slack/costs`) |

Set them from your shell, with admin credentials in the primary account
(the command refuses another account's):

```sh
aws sso login --sso-session jwall-engineering
export AWS_PROFILE=jaws-prod                         # the primary account
jaws monitoring secrets set grafana-admin-user      # prompts, no echo
jaws monitoring secrets set grafana-admin-password
jaws monitoring secrets set slack/platform           # the webhook URL Slack gave the channel
jaws monitoring secrets set slack/costs
jaws monitoring secrets check                        # lists what is missing; exit 0 when nothing is
```

`set` overwrites, so it also rotates a secret. A name the configuration does
not imply is refused: a `slack/<channel>` needs the channel in
`monitoring.slack.channels` first. `check` never reads a value; it exits 3 and
names every missing secret while any is missing.

## Reaching Grafana

- **At <https://grafana.jwall.engineering>**, from 08:00 to midnight Mountain
  time. Sign in as the admin user (`grafana-admin-user`). Anonymous access
  and sign-up are off, and brute-force protection is on. Other users are added
  in Grafana's administration pages; they live in the data volume's Postgres,
  so a lost volume loses them.
- **Right after a start** the name takes up to a minute to follow the node's
  new address (a 60-second TTL). The certificate is kept on the data volume,
  so neither a start nor a replacement needs a new one from Let's Encrypt.
- **At night** the node is stopped. Start it by hand
  ([below](#stopping-starting-and-rebooting)) and stop it again when done.
- **On the node itself**, through Session Manager: `aws ssm start-session
  --target <instance-id>`. With a domain, Grafana listens only behind Caddy;
  a node without one is reached through a port forward instead
  ([reaching Grafana](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.1/modules/monitoring-node/README.md#reaching-grafana)).

## The schedule

The node runs from 08:00 to midnight every day, `America/Denver`, and is
stopped from 00:00 to 08:00. Two EventBridge Scheduler schedules start and stop
it; a stop is a normal shutdown, so every service stops cleanly.

- **Muted after the start.** Grafana mutes notifications for the first 15
  minutes after each scheduled start (the mute timing
  `after-scheduled-start`), while targets come up and `cost-sync` catches up
  on what arrived overnight. Rules still evaluate; only Slack is quiet. A
  start by hand is not muted.
- **Snapshots at 03:00** Mountain time, while the node is off, so they capture
  disks that were shut down cleanly. (An hour after the stop would be 01:00,
  inside the daylight-saving window, so the module moves it to 03:00.) The
  vault keeps 7.
- **While it is off**, the export, the Databricks job, the normalizer and the
  task records keep filling the bucket, and the node loads all of it at boot.
  Host metrics have a gap for the night.
- **The watchdog** reads the same schedule ([below](#the-watchdog)).
- **Changing it** is a pull request to `monitoring.schedule`, within the rules
  in [Configuration](#configuration), then a release. Leaving it out runs the
  node all day, for about $9.40 a month more.

The module's [off-hours
section](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.1/modules/monitoring-node/README.md#off-hours)
has the rest.

## Dashboards and alerts

Every dashboard and rule is provisioned, so they are read-only in Grafana; they
change with a module release or with `config/monitoring.yaml`.

| Dashboard | Folder | Shows |
| --- | --- | --- |
| **Monitoring node · Host health** | Monitoring | The last 6 hours: CPU and credits, memory, disks, services, patching, and the cost pipeline's freshness |
| **Cost · Overview** | Cost | The last 90 days, by provider, account, project and environment: month to date, the forecast against the $100 budget, the trend, where the money goes, the biggest movers, untagged spend |
| **Cost · Project** | Cost | One project: its spend by component, service and environment, against its budget |
| **Cost · Databricks** | Cost | Spend and DBUs by product, workspace and SKU, at list price, and the all-in cost with each workspace's AWS resources |
| **Cost · Tasks** | Cost | The last 30 days of task runs: campaigns, one row per run with its cost, spend by workflow, efficiency ([run records](remote-tasks.md#run-records)) |

Amounts are `BilledCost` in USD. Days are UTC calendar days, as AWS bills,
and a day is complete 48 hours after it ends, so yesterday is still partial.
Every panel and table is described in the module's [what the node
watches](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.1/modules/monitoring-node/README.md#what-the-node-watches)
and [cost
data](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.1/modules/monitoring-node/README.md#cost-data).

Alert rules come in warning and critical pairs, and each carries an `area`,
which `monitoring.slack.routes` sends to a channel:

| Area | Rules | Channel |
| --- | --- | --- |
| `host` | CPU, CPU credits, memory, swap, OOM kills, disk space and growth, inodes, Prometheus's size cap, scrape targets, container restarts, TLS expiry, Grafana's own rule failures, a newer AL2023 release | `platform` |
| `pipeline` | `cost-sync` or the normalizer late or failing, AWS charges or Databricks deliveries stale, a task run possibly leaked or over its ceiling | `platform` |
| `cost` | The month-end forecast or the month to date over a budget, a day's spend at 2× or 4× its 14-day median (and $2 above it), new untagged spend | `costs` |

Host and pipeline alerts repeat every 4 hours while they fire (the AMI
reminder once a day); cost alerts post once, then weekly. Resolved alerts post
too.

- **To change a threshold for good**, override it by name under
  `monitoring.thresholds`, in a pull request. The names and defaults are the
  module's ([thresholds](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.1/modules/monitoring-node/README.md#thresholds)):

  ```yaml
  thresholds:
    cpu_percent: { warning: 70, critical: 90 } # a pair states both
    untagged_daily_usd: { warning: 1 }         # a warning-only rule
  ```

- **Before a planned expensive run**, such as a long GPU training or a big
  data-generation campaign, add a silence in Grafana (Alerting → Silences)
  with an end time. Task spend counts in the anomaly rule on purpose, so every
  unplanned expensive run is heard about. A silence is the one thing set by
  hand in Grafana.

## The watchdog

A dead node can't report its own death, so it is also watched from outside.
Two CloudWatch alarms act on their own: a failed system status check makes EC2
recover the instance onto other hardware, and a failed instance status check
reboots it. A stopped instance sends no data, so the scheduled stop is silent.

`jaws-monitoring-watchdog` runs every 5 minutes, and at once when an alarm
changes. It posts to the `host` route's channel, `platform`:

| Post | Severity | When |
| --- | --- | --- |
| Monitoring node not running | critical | It should be running and isn't, on two checks in a row; never in the 15 minutes after the scheduled start |
| Monitoring node running off-hours | warning | It runs between midnight and 08:00: a stop that failed, or a start by hand, quietly costing money; never in the 15 minutes after the scheduled stop |
| Grafana not answering | critical | `https://grafana.jwall.engineering/api/health` failed twice in a row, 15 minutes or more after a start |
| EC2 system status check failed, EC2 instance status check failed | critical | While its alarm is in ALARM |

Each problem posts once, again every 4 hours while it lasts, and once when it
resolves. The watchdog keeps its state in `/jaws-monitoring/node/watchdog-state`
and saves it only after every post succeeded, so a post that failed (the
`slack/platform` webhook missing, say) is retried on the next run. The
module's [watchdog
section](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.1/modules/monitoring-node/README.md#the-watchdog)
has the rest.

## Recovery

| Event | What happens | What is lost |
| --- | --- | --- |
| The scheduled stop and start | The disks persist; the services start, `cost-sync` catches up and the DNS record follows the new address | Host metrics for the hours off |
| A reboot, or EC2's recovery after a failed status check | Same disks, same instance | Minutes of metrics |
| The instance replaced (an AMI bump, or a terminated instance) | The new instance reattaches the data volume and carries on | Minutes of metrics |
| The data volume lost | Dashboards and alerts are provisioned again and the cost database is rebuilt from `normalized/`; Grafana users other than the admin must be added again | Prometheus history since the last snapshot ([restore it](#restoring-the-data-volume-from-a-snapshot)) |
| The node down for days | The export, the Databricks job and the normalizer keep filling the bucket | Nothing in the bucket |

The commands below are the owner's, with the `jaws-prod` profile. The
instance's ID:

```sh
export AWS_PROFILE=jaws-prod
id=$(aws ec2 describe-instances \
  --filters Name=tag:Name,Values=jaws-monitoring \
  Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[].Instances[].InstanceId' --output text)
```

### Stopping, starting and rebooting

```sh
aws ec2 stop-instances --instance-ids "$id"
aws ec2 start-instances --instance-ids "$id"
aws ec2 reboot-instances --instance-ids "$id"
```

- **A stop by hand in the day** brings the watchdog's "not running" within
  about 10 minutes, and the next scheduled start (08:00) undoes it.
- **A start by hand at night** runs until you stop it or until the next
  scheduled stop, at midnight; the watchdog posts "running off-hours" as the
  reminder. Grafana's 15-minute mute covers only scheduled starts, so alerts
  can post while the services come up.

### When the node misbehaves

- **Its status:** the reconciler writes `/jaws-monitoring/node/status`, `ok`
  or `failed:<why>` (`missing secret <parameter>`, `bundle`, `pull`, `up`,
  `password-reset` or `internal`). Read it with
  `aws ssm get-parameter --name /jaws-monitoring/node/status --query Parameter.Value --output text`.
  A failed reconcile leaves the last good release running.
- **A shell on it:** `aws ssm start-session --target "$id"`. There,
  `sudo docker ps` lists the services, `journalctl -u monitoring-reconcile`
  and `journalctl -u monitoring-cost-sync` show the last runs, and
  `sudo systemctl start monitoring-reconcile.service` applies a new bundle now
  instead of within 5 minutes.
- **A pipeline alert:** `s3://jaws-billing-570327089884/normalized/_runs/latest.json`
  is the normalizer's last run, with its errors and warnings. After a fix, run
  it at once with
  `aws lambda invoke --function-name jaws-monitoring-normalizer --invocation-type Event out.json`
  (it rebuilds only what changed) and read `latest.json` again a few minutes
  later.

### Replacing the instance (patching)

The node is patched by replacing it with a newer image, never by upgrading
packages in place. The cue is the warning "Newer Amazon Linux 2023 release
available", which fires once a release has been out 7 days and is repeated
daily.

1. Find the newest image of the pinned kernel line:

   ```sh
   aws ec2 describe-images --owners amazon \
     --filters 'Name=name,Values=al2023-ami-2023.*-kernel-6.18-arm64' \
     --query 'sort_by(Images, &CreationDate)[-1].Name' --output text
   ```

2. Set it as `monitoring.ami` in a pull request. The monitoring plan comment
   shows the instance replaced and its volume attachment with it, and the data
   volume kept.
3. Merge it and release **between 08:00 and midnight**. The new instance
   reattaches the data volume, pulls the pinned images and reconciles in full;
   Grafana, the cost database, Prometheus's history and the certificate carry
   over. A new instance always starts running, so one created at night runs
   until the next scheduled stop (stop it by hand).

A terminated instance comes back the same way: the next release's apply
creates a new one, which reattaches the data volume.

### Restoring the data volume from a snapshot

If the data volume is lost, the next release's apply creates an empty one,
and a new instance with it (the instance boots knowing its volume's ID, so a
new volume means a new instance). The node then provisions every dashboard and
rule again and `cost-sync` rebuilds the cost database from `normalized/`, so
only Prometheus's history and the Grafana users other than the admin are
gone. To get the history back, restore a snapshot. The vault
`jaws-monitoring-snapshots` holds the last 7 nightly recovery points. This
path has not been rehearsed yet: read each plan before the release.

1. In AWS Backup → Backup vaults → `jaws-monitoring-snapshots`, pick the
   newest recovery point and **Restore** it as an encrypted gp3 volume in
   `us-east-1a`, the node's zone. Give it the lost volume's tags, at least
   `Name = jaws-monitoring-data` and `Project = monitoring`: the stack's apply
   role may change only volumes tagged with its project.
2. In `monitoring/`, with the owner's credentials, swap it into the state in
   place of the old volume. Never `terraform apply` from the shell:

   ```sh
   cd monitoring
   terraform init -backend-config=backend/prod.hcl
   terraform state rm 'module.monitoring[0].module.node.aws_ebs_volume.data'
   terraform import 'module.monitoring[0].module.node.aws_ebs_volume.data' vol-0123456789abcdef0
   terraform plan   # the instance and its volume attachment replaced; no volume created
   ```

3. Release between 08:00 and midnight. The apply replaces the instance, and
   the new one boots with the restored volume. Once it is attached, delete any
   empty volume an earlier apply created.

Turning `snapshots` off, or destroying the stack, needs the vault's recovery
points deleted by hand first: the vault refuses to be destroyed while it holds
any, so a stray destroy never deletes the backups.

## Adding a cost provider

A provider is a source that delivers whole billing periods into the bucket,
and a mapper in the normalizer from its columns to the normalized schema
([the bucket
layout](https://github.com/Jaws-Platform/terraform-aws-jaws-monitoring/blob/v0.8.1/README.md#the-bucket-layout)).
The module family holds the mapper; Jaws turns it on.

1. **The module**, in `Jaws-Platform/terraform-aws-jaws-monitoring` (never
   worked around here): the mapper in `billing-normalizer`, an input for the
   provider on the root module as `aws` and `databricks` have, and, if its
   freshness should be watched, a pipeline rule on the node. It ships as a new
   release of the family.
2. **The source:** something that writes period snapshots under
   `raw/provider=<p>/source=<s>/` in the billing bucket, the newest delivery of
   a period winning, with a writer that may put objects only under its own
   prefix (as the Databricks job's role may write only under
   `raw/provider=databricks/source=system-tables/`). If Jaws runs it, it is
   the foundation's, next to `databricks_billing_export` in
   `foundation/monitoring.tf`.
3. **One pull request here:** bump every `jaws-monitoring` pin together
   (`monitoring/`, `foundation/monitoring.tf`, `billing-export/` and
   `library.families` in `config/terraform.yaml`; `tests/test_versions.py`
   checks), add the provider's switch to `MonitoringCost` in
   `src/jaws/settings.py` with its tests and to `config/monitoring.yaml`, and
   pass it in `local.cost` in `monitoring/main.tf`, with a run in
   `monitoring/tests/`.
4. **Release**, then check that the first delivery lands under its prefix.
   With `protect_raw` on, a misplaced object can't be deleted, so check the
   writer's prefix in the plan before the release.

## Adding a Slack channel

1. **Create an incoming webhook** for the Slack channel.
2. **In a pull request,** add the channel under `monitoring.slack.channels`
   with its parameter, and route an area to it. A channel is named with a
   lowercase letter, then lowercase letters, digits or `-` (at most 30), and
   its parameter is under `/jaws/monitoring/`:

   ```yaml
   slack:
     channels:
       platform: /jaws/monitoring/slack/platform
       costs: /jaws/monitoring/slack/costs
       pipeline: /jaws/monitoring/slack/pipeline
     routes: { host: platform, pipeline: pipeline, cost: costs }
   ```

3. **Set its webhook** from a checkout of that branch, since the CLI accepts
   only the channels in the configuration it reads:
   `jaws monitoring secrets set slack/pipeline`, then
   `jaws monitoring secrets check`. Do it before the release: while a secret
   is missing, the node keeps running its last release and reports
   `failed:missing secret`.
4. **Release.** The new contact point and route arrive in the next bundle,
   within 5 minutes of the apply; the instance is not replaced.

To retire a channel, remove its routes and its entry in a pull request,
release, then delete its parameter (`aws ssm delete-parameter`). To rotate a
webhook, `jaws monitoring secrets set` it again.

## Cost

us-east-1, a month, from the spec's estimate. T9g's price is not verified yet,
so the node is priced like a `t4g.medium`.

| Item | Estimate |
| --- | --- |
| `t9g.medium` | about $24.50, running 24/7 |
| Public IPv4 address | $3.65, running 24/7 |
| Data volume, 30 GB gp3 | $2.40 |
| Root volume, 12 GB gp3 | $0.96 |
| Snapshots, 7 daily, incremental | under $1 |
| CloudWatch: 2 alarms, credit and status reads | under $0.50 |
| The Databricks billing job (serverless) | about $0.50 to $3, to be measured |
| Lambda, Scheduler, SNS, S3 | cents (free tiers; the bucket grows about 1 GB a year) |
| **Total, 24/7** | **about $33 to $36** |
| **Total on Jaws's schedule, 16 hours a day** | **about $24 to $27** |

The schedule saves a third of the instance and the IPv4 address, about $9.40;
the disks and the rest are billed either way. Ways to trim: turn snapshots off
(about $1), shrink the data volume to 20 GB ($0.80), run fewer hours (weekdays
08:00 to 20:00 would save about $18), or move to `t9g.small` if the host
dashboard shows memory to spare. The platform's own spend shows on
**Cost · Project**: project `monitoring` for the stack, and `jaws` for the
bucket and the Databricks job, whose DBUs are on **Cost · Databricks**.

## Known gaps

- **Unconfirmed until the first live run:** EC2's `recover` action on T9g, the
  watchdog's alarm reads scoped to the alarms' ARNs, pressure-stall metrics on
  the AL2023 kernel (without them their panel is hidden and there is no rule),
  that container restarts ignore the reconciler's recreations, T9g's price and
  whether it keeps CPU credits while stopped, and the Databricks job writing
  through its service credential from serverless compute.
- **Databricks workspace names are not exported** (the job's
  `include_workspaces` is off), so usage without a `Project` tag is not yet
  given its workspace's project, and **Cost · Databricks**'s all-in reads 0
  for AWS until the names are known and `Workspace` is an active cost
  allocation tag.
- **Task runs:** a run that finished and was swept later ends at the finish,
  and a run whose `finished` record never arrived stays "running" until it is
  swept.
- **Not built yet:** budget lines on the by-project bars, a forecast of future
  tax, and metrics sent from projects to the node.
