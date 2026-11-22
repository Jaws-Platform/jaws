# Off-hours and the Watchdog Implementation Plan (07)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Let the node keep office hours, and report when it is down. Release it as 0.8.0 of `terraform-aws-jaws-monitoring`. It covers:
- **The optional schedule**, with Grafana muted for the first 15 minutes after each start, and snapshots taken while the node is off;
- **The watchdog:** EC2 status-check alarms that recover or reboot the node, and a small Lambda that posts to Slack when the node is down, on when it should be off, or not answering;
- **The root module**, which wires the normalizer into the node.

**Architecture:**
- **The schedule is two EventBridge Scheduler schedules** that call `ec2:StartInstances` and `ec2:StopInstances` on the one instance, in the schedule's time zone.
- **Snapshots move from Data Lifecycle Manager to AWS Backup.** DLM takes only UTC times, and Terraform has no time-zone database to convert one. An AWS Backup plan takes `schedule_expression_timezone`, so the snapshot lands in the off window all year round, daylight saving included.
- **The watchdog lives outside the node,** so it still works when the node is dead. It is on whenever Slack is.
  - Two CloudWatch alarms recover or reboot the instance, and notify an SNS topic.
  - A Python Lambda (stdlib plus boto3), triggered by that topic and every 5 minutes, judges the node against the schedule. It keeps its state in an SSM parameter and posts to the `host` channel's webhook.
- **The root module** follows `terraform-aws-jaws-lichess-bot`'s pattern. It only wires the two submodules together, and each keeps its own validation.

**Tech Stack:**
- Terraform (`terraform test` with mock providers);
- AWS EventBridge Scheduler, AWS Backup, CloudWatch, SNS and Lambda (`python3.13`);
- the Grafana 13.3.1 smoke test;
- Python unittest, run under the system Python and inside the pinned AWS Lambda Python base image.

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md):
- 6.9, the watchdog;
- 6.10, the off-hours schedule;
- 6.11, recovery;
- 7, the modules and the optional-feature rule.

Series: [00-roadmap](2026-11-21-monitoring-00-roadmap.md).

## Global Constraints

**Where things live**
- **Repo:** `$REPO` = `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-monitoring`, on branch `feat/off-hours-watchdog` from `origin/main` (0.7.0).
- **Modules:** `$MOD` = `$REPO/modules/monitoring-node`, and `$GRAF` = `$MOD/grafana`.

**Repo rules**
- PR titles carry a scope: `feat(monitoring-node): …`, or `feat(examples): …` for the root.
- PR bodies follow `.github/pull_request_template.md`.
- Commits are one line, at most 100 characters, followed by `Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>`.
- No cloud calls, and no `terraform apply`.

**The optional-feature rule** (7): every feature here is off until its input is given.
- **No `schedule`** means 24/7: no schedules and no mute timing.
- **No `slack`** means no watchdog: no alarms, topic, Lambda or schedules.

**`schedule`** (6.10): `optional object { timezone, days, on, off }`, default `null`.
- **Allowed shapes:**
  - whole hours (`HH:00`);
  - `on` before `off`;
  - `off` may be `24:00`, meaning midnight at the end of the day. Its stop fires at `00:00` on the next weekday, so the stop schedule's days shift by one;
  - at least 4 hours on;
  - one or more unique days from `mon` to `sun`;
  - a non-empty `timezone`;
  - no raw cron.
- **Jaws's schedule:** `America/Denver`, every day, `08:00` to `24:00`.

**The watchdog** (6.9):
- **Status-check alarms:** `StatusCheckFailed_System` triggers `arn:aws:automate:<region>:ec2:recover`, and `StatusCheckFailed_Instance` triggers `arn:aws:automate:<region>:ec2:reboot`. Both:
  - notify the topic, on alarm and on OK;
  - use `treat_missing_data = "notBreaching"`, so a scheduled stop is silent;
  - have a period of 60 seconds and 2 evaluation periods.
- **The Lambda's problems:**

  | Key | Severity | When |
  |---|---|---|
  | `not-running` | critical | The node should run, isn't `pending` or `running`, outside the 15-minute grace after a scheduled start, on 2 checks in a row |
  | `running-off-hours` | warning | The node shouldn't run, is `running`, outside the 15-minute grace after a scheduled stop |
  | `health` | critical | With a domain, while the node should run and is running: `https://<domain>/api/health` failed on 2 checks in a row |
  | `status-system`, `status-instance` | critical | Its alarm is in `ALARM` |

- **Posting:** once when a problem fires, again every 4 hours while it lasts, and once when it resolves. The text is `🚨 [FIRING] <title> — severity: <severity>`, or `✅ [RESOLVED] <title>`, then the detail and the instance id.
- **State:** a String SSM parameter `/<name>/node/watchdog-state` holds the JSON `{"problems": {key: {severity, title, detail, since, posted}}, "counters": {"not_running": n, "health": n}}`. Unreadable state counts as empty. The state is saved only after every post succeeded.

**Snapshots** (6.10): `snapshots = { enabled, time_utc, keep }`, unchanged as an input.
- **The backup:** an AWS Backup plan runs daily, keeping each recovery point for `keep` days. Its selection is only the data volume.
- **Without a schedule:** at `time_utc`, in time zone `Etc/UTC`.
- **With a schedule:** in the schedule's time zone, at one hour after the stop (`off + 1`, modulo 24), moved to `03:00` when that falls between `01:00` and `02:59`, the hours daylight saving changes. For Jaws, `24:00 + 1` is `01:00`, which moves to `03:00`.
- **The vault** `<name>-snapshots` has `force_destroy = false`. Destroying the module, or turning snapshots off, needs its recovery points deleted first, so a stray destroy never deletes the backups.

**Patching** needs no change. `monitoring-release-check.timer` already runs at boot and every 6 hours, which is what 6.10 asks for under a schedule.

**Version:** `COST_SCHEMA_VERSION` is unchanged. Release 0.8.0.

## Review Focus

1. **Daylight saving.** The scheduler and the Backup plan take the zone, and the watchdog decides "should it run" in the zone's own local time. On a July day and a January day, the same local time is in or out of the window the same way. Test: Task 4 `test_the_window_follows_daylight_saving`.
2. **A brief not-running moment,** such as an apply that replaces the instance, or one check during a reboot, doesn't page. `not-running` needs 2 checks in a row. Test: Task 4 `test_one_not_running_check_is_not_critical`.
3. **Slack is down, or the webhook parameter is missing.** The watchdog logs it and keeps its state unchanged, so the next run posts again. Test: Task 4 `test_a_failed_post_leaves_the_state_unchanged`.
4. **Removing the schedule or Slack later.**
   - The schedules go.
   - The mute timing is deleted, or left unreferenced if Grafana can't delete it.
   - Grafana starts cleanly.

   Tests: Task 1 `without_a_schedule_the_node_runs_all_day`; the smoke test's phase 2 (no Slack, no schedule) after phase 1 (both).
5. **A scheduled stop stays silent.**
   - The alarms treat missing data as not breaching.
   - The watchdog doesn't flag a stopped node in its off window.

   Tests: Task 5 `with_slack_the_watchdog_watches` (`treat_missing_data`); Task 4 `test_a_stopped_node_in_its_off_window_is_fine`.

---

### Task 1: The schedule

**Files:**
- Create: `$MOD/schedule.tf`
- Modify: `$MOD/variables.tf` (`schedule`)
- Test: `$MOD/tests/monitoring_node.tftest.hcl`

**Interfaces:**
- Produces:
  - `var.schedule`;
  - `local.schedule_on_hour` and `local.schedule_off_hour` (numbers, with `off` 24 kept as 24);
  - `local.schedule_json`: `jsonencode(var.schedule)`, or `""`;
  - the resources `aws_scheduler_schedule.start` and `.stop`, and `aws_iam_role.schedule`, all with count `var.schedule == null ? 0 : 1`.

- [x] **Step 1: Write the failing tests.**
  - **`without_a_schedule_the_node_runs_all_day`:** no `aws_scheduler_schedule.start` or `.stop`.
  - **`a_schedule_starts_and_stops_the_node`** (Jaws's schedule):
    - start is `cron(0 8 ? * MON,TUE,WED,THU,FRI,SAT,SUN *)`;
    - stop is `cron(0 0 ? * TUE,WED,THU,FRI,SAT,SUN,MON *)`;
    - both have `schedule_expression_timezone = "America/Denver"` and flexible time window `OFF`;
    - the targets are `arn:aws:scheduler:::aws-sdk:ec2:startInstances` and `…:stopInstances`, with input `{"InstanceIds":[<instance id>]}`.
  - **`an_evening_stop_keeps_its_days`:** `mon`–`fri`, `08:00`–`20:00`, gives stop `cron(0 20 ? * MON,TUE,WED,THU,FRI *)`.
  - **`the_scheduler_may_start_and_stop_only_this_instance`:** the role's policy allows exactly `ec2:StartInstances` and `ec2:StopInstances`, on the instance's ARN.
  - **Rejects** (`expect_failures = [var.schedule]`):
    - `rejects_half_hours` (`08:30`);
    - `rejects_an_overnight_window` (`22:00`–`06:00`);
    - `rejects_fewer_than_4_hours_on` (`08:00`–`11:00`);
    - `rejects_an_unknown_day` (`funday`);
    - `rejects_a_repeated_day`;
    - `rejects_no_days`.
- [x] **Step 2: Run** `cd $MOD && terraform test -filter=tests/monitoring_node.tftest.hcl`. Expected: the new runs fail, with no `schedule` variable.
- [x] **Step 3: Implement** `var.schedule` with its validations, and `schedule.tf`. Day names become `MON`…`SUN`. With `off = "24:00"`, the stop's days are each day's successor.
- [x] **Step 4: Run** it again. Expected: all pass.
- [x] **Step 5: Commit** `feat(monitoring-node): start and stop the node on an optional schedule`.

### Task 2: Mute Grafana after each scheduled start

**Files:**
- Modify: `$GRAF/variables.tf` (`schedule`), `$GRAF/notifications.tf`, `$MOD/grafana.tf` (pass the schedule)
- Test: `$MOD/tests/grafana.tftest.hcl`, `$MOD/tests/test-grafana-provisioning.sh` (phase 1 renders with Jaws's schedule)

**Interfaces:**
- Consumes: `var.schedule` (Task 1).
- Produces: `grafana/provisioning/alerting/mute-timings.json` with the mute timing `after-scheduled-start`, and every child notification route with `mute_time_intervals = ["after-scheduled-start"]`. Both only with Slack and a schedule.

**The mute timing:** `time_intervals = [{ times = [{ start_time = on, end_time = on + 15 min }], weekdays = the days as full lowercase names, location = timezone }]`.
- **With a schedule,** a route exists for every area, `host`, `pipeline` and `cost` (the last with cost on). An area without its own channel uses `host`'s, so no alert falls through to the unmuted root.
- **Without a schedule,** the file is `{ deleteMuteTimes = [{ orgId = 1, name = "after-scheduled-start" }] }`. If Grafana 13.3 refuses that while the old policy still names it, render no file instead, and ledger a ruling: an unreferenced mute timing mutes nothing.

- [x] **Step 1: Write the failing tests.**
  - **`a_schedule_mutes_the_first_15_minutes`:** Jaws's schedule with Slack:
    - the mute timing has `08:00`–`08:15`, all seven weekdays and `America/Denver`;
    - every route has `mute_time_intervals = ["after-scheduled-start"]`;
    - the routes' area matchers cover `host`, `pipeline` and `cost`.
  - **`without_a_schedule_nothing_is_muted`:** no route has `mute_time_intervals`.
- [x] **Step 2: Run** `terraform test -filter=tests/grafana.tftest.hcl`. Expected: both fail.
- [x] **Step 3: Implement it,** and render phase 1 of the smoke test with Jaws's schedule.
- [x] **Step 4: Run** `terraform test`, then `bash tests/test-grafana-provisioning.sh`. Expected:
  - all pass;
  - phase 1 provisions the mute timing, and Grafana accepts the policy that names it;
  - phase 2 starts cleanly.
- [x] **Step 5: Commit** `feat(monitoring-node): mute alerts for the first 15 minutes after a scheduled start`.

### Task 3: Snapshots in the off window

**Files:**
- Modify: `$MOD/storage.tf` (DLM is replaced by AWS Backup)
- Test: `$MOD/tests/monitoring_node.tftest.hcl` (update the existing snapshot runs)

**Interfaces:**
- Consumes: `var.schedule`, `local.schedule_off_hour` (Task 1).
- Produces: `local.snapshot_hour` (0–23) and `local.snapshot_timezone`; the resources `aws_backup_vault.snapshots`, `aws_backup_plan.snapshots`, `aws_backup_selection.snapshots` and `aws_iam_role.snapshots` (principal `backup.amazonaws.com`, with `AWSBackupServiceRolePolicyForBackup`).

- [x] **Step 1: Write the failing tests.**
  - **`snapshots_without_a_schedule_run_at_time_utc`:** `time_utc = "03:00"` gives a rule with `cron(0 3 ? * * *)` and time zone `Etc/UTC`.
  - **`with_a_schedule_snapshots_run_after_the_stop`:** Jaws's schedule gives `cron(0 3 ? * * *)` in `America/Denver`. `mon`–`fri` `08:00`–`20:00` gives `cron(0 21 ? * * *)`.
  - **`snapshots_keep_the_last_n_days`:** `keep = 7` gives `lifecycle.delete_after = 7`.
  - **`snapshots_back_up_only_the_data_volume`:** the selection's resources are exactly the data volume's ARN.
  - **`the_snapshot_vault_keeps_its_recovery_points`:** `force_destroy == false`.
  - **`without_snapshots_there_is_no_backup_plan`.**
  - Remove the DLM assertions they replace.
- [x] **Step 2: Run** them. Expected: they fail, because there is no `aws_backup_plan`.
- [x] **Step 3: Implement it.** Use `start_window = 60` and `completion_window = 180`.
- [x] **Step 4: Run** `terraform test`. Expected: all pass.
- [x] **Step 5: Commit** `feat(monitoring-node): take snapshots with aws backup, in the off window when scheduled`.

### Task 4: The watchdog's code

**Files:**
- Create:
  - `$MOD/files/watchdog/watchdog.py`;
  - `$MOD/files/test_watchdog.py`;
  - `$MOD/tests/test-watchdog-runtime.sh`, which runs `test_watchdog.py` inside `public.ecr.aws/lambda/python:3.13`, pinned by digest at build;
  - `scripts/check-module.sh`, which runs it.

**Interfaces** (in `watchdog.py`, stdlib, with boto3 imported only inside `default_clients()`):
- `should_run(now: datetime, schedule: Optional[dict]) -> bool`: always `True` with no schedule. Otherwise the local day is in `days`, and `on <= local time < off`, where `off` 24 is the end of the day. Local time comes from `zoneinfo.ZoneInfo(schedule["timezone"])`.
- `in_grace(now: datetime, schedule: Optional[dict], minutes: int = 15) -> bool`: within `minutes` after a scheduled start or stop. Always `False` with no schedule.
- `assess(now, instance_state: str, schedule, alarms: Dict[str, str], health_ok: Optional[bool], counters: dict) -> Tuple[Dict[str, dict], dict]`: the current problems by key, and the new counters, per the table in Global Constraints.
- `notify(state: dict, problems: Dict[str, dict], now: datetime, repeat_hours: int = 4) -> Tuple[List[str], dict]`: the messages to post, and the new state.
- `handler(event, context, clients=None)`. It reads its environment:
  - `NAME`, `INSTANCE_ID`;
  - `SCHEDULE`: JSON, or `""`;
  - `DOMAIN`: or `""`;
  - `WEBHOOK_PARAMETER`, `STATE_PARAMETER`;
  - `ALARMS`: comma-separated names.

  It then describes the instance and the alarms, fetches the health URL, and calls `assess` and `notify`. It posts each message as `{"text": …}` with `urllib.request`, and saves the state only if every post succeeded. An SNS event and a scheduled event are handled the same way.

- [x] **Step 1: Write the failing tests** in `files/test_watchdog.py`, with fake clients and fixed `now`, and Jaws's schedule unless named.
  - `test_a_24_7_node_that_is_stopped_is_critical_on_the_second_check`
  - `test_one_not_running_check_is_not_critical`
  - `test_a_scheduled_node_is_not_flagged_in_its_first_15_minutes`: stopped at 08:10 local.
  - `test_a_scheduled_node_still_stopped_after_15_minutes_is_critical`: stopped at 08:20 and 08:25.
  - `test_a_stopped_node_in_its_off_window_is_fine`: 03:00 local.
  - `test_running_in_the_off_window_is_a_warning`: 00:20 local, running.
  - `test_midnight_off_means_the_end_of_the_day`: 23:59 is in the window, and 00:00 the next day is not.
  - `test_the_window_follows_daylight_saving`: `2026-07-15T14:30Z` and `2027-01-15T15:30Z` are both 08:30 local, so both are in the window.
  - `test_two_health_failures_in_a_row_are_critical`: one failure gives no problem, and a success in between resets the count.
  - `test_health_is_not_checked_while_the_node_should_be_off`
  - `test_a_failed_status_check_alarm_is_critical`
  - `test_a_problem_posts_once_repeats_after_4_hours_and_posts_when_resolved`
  - `test_a_failed_post_leaves_the_state_unchanged`
  - `test_unreadable_state_counts_as_empty`
  - `test_an_sns_event_is_judged_like_a_scheduled_one`
- [x] **Step 2: Run** `python3 -m unittest files/test_watchdog.py`. Expected: an import error, because there's no `watchdog.py` yet.
- [x] **Step 3: Implement `watchdog.py`.**
- [x] **Step 4: Run** the unit tests, then `bash tests/test-watchdog-runtime.sh`. Expected: both pass. The second proves `zoneinfo` has `America/Denver` and `boto3` imports, in the real runtime.
  - **If the Lambda runtime has no zone database: stop and ask the owner.** The way out, vendoring `tzdata`, breaks the spec's "standard library plus boto3".
- [x] **Step 5: Commit** `feat(monitoring-node): add the watchdog's code`.

### Task 5: The watchdog's infrastructure

**Files:**
- Create: `$MOD/watchdog.tf`
- Test: `$MOD/tests/monitoring_node.tftest.hcl`

**Interfaces:**
- Consumes: Task 4's `files/watchdog/` (zipped with `data.archive_file.watchdog`, handler `watchdog.handler`); `local.schedule_json` (Task 1); `local.parameter_prefix`; and `var.slack`.
- Produces, all with count `var.slack == null ? 0 : 1`:
  - `aws_sns_topic.watchdog`;
  - `aws_cloudwatch_metric_alarm.system_status` and `.instance_status`;
  - `aws_lambda_function.watchdog` (`python3.13`, 128 MB, 30 s);
  - `aws_cloudwatch_log_group.watchdog` (30 days);
  - `aws_iam_role.watchdog`;
  - `aws_scheduler_schedule.watchdog` (`rate(5 minutes)`), with its role;
  - `aws_sns_topic_subscription.watchdog` and `aws_lambda_permission.watchdog_sns`;
  - the output `watchdog_function_name` (null without Slack).

**The watchdog's permissions:**
- `ec2:DescribeInstances` on `*`;
- `cloudwatch:DescribeAlarms` on the two alarms;
- `ssm:GetParameter` on the `host` channel's webhook parameter and the state parameter;
- `ssm:PutParameter` on the state parameter;
- its own log group.

- [x] **Step 1: Write the failing tests.**
  - **`without_slack_there_is_no_watchdog`.**
  - **`with_slack_the_watchdog_watches`:**
    - the two alarms, with their `recover` and `reboot` actions plus the topic on alarm and OK, `notBreaching`, 60 s and 2 periods;
    - the Lambda's environment, with `WEBHOOK_PARAMETER` being the `host` channel's parameter, `STATE_PARAMETER = "/acme-monitoring/node/watchdog-state"`, and `ALARMS` naming both alarms;
    - the 5-minute schedule targets the Lambda.
  - **`the_watchdog_reads_the_schedule_and_the_domain`:** with Jaws's schedule and a domain, `SCHEDULE` decodes to the schedule and `DOMAIN` is the domain.
  - **`the_watchdog_may_read_only_its_webhook_and_state`:** the policy's `ssm` actions name exactly those two parameter ARNs, and `PutParameter` names only the state's.
- [x] **Step 2: Run** them. Expected: they fail.
- [x] **Step 3: Implement `watchdog.tf`.**
- [x] **Step 4: Run** `scripts/check-module.sh modules/monitoring-node`. Expected: it passes, with tflint clean.
- [x] **Step 5: Commit** `feat(monitoring-node): watch the node from outside with status alarms and a lambda`.

### Task 6: The root module

**Files:**
- Modify: `$REPO/main.tf`, `$REPO/variables.tf`, `$REPO/outputs.tf`, `$REPO/README.md`
- Modify: `$MOD/variables.tf` and `$REPO/modules/billing-normalizer/variables.tf`: `nullable = false` on every input that has a non-null default, so a null from the root means "the default"
- Create: `$REPO/tests/root.tftest.hcl`

**Interfaces:**
- **Inputs:** every input of both submodules, under the same name and defaulting to `null`, except:
  - `name` is shared: the normalizer is `<name>-normalizer`, and the node is `<name>`;
  - the normalizer's `schedule_expression`, `memory_size` and `log_retention_days` become `normalizer_schedule_expression`, `normalizer_memory_size` and `normalizer_log_retention_days`;
  - the node's `cost` becomes `budgets`, `anomaly_floor_usd` and `databricks_workspace_tag`, since the root wires the rest.

  Required inputs stay required: `name`, `bucket_name`, `vpc_id` and `subnet_id`.
- **Wiring:** `local.node_cost` =
  - `{ bucket = var.bucket_name, normalized_prefix = <the normalizer's normalized_prefix> }`;
  - `providers`: `aws` when `var.aws != null`, `databricks` when `var.databricks != null`;
  - `run_join_tags = var.runs == null ? ["RunId", "TaskId"] : var.runs.join_tags`;
  - the three cost settings above.
- **Outputs:** `normalizer` (all the normalizer's outputs) and `node` (all the node's).

- [x] **Step 1: Write the failing tests** in `tests/root.tftest.hcl` (mock `aws`):
  - **`the_root_plans_with_only_the_required_inputs`:** name, bucket, VPC and subnet, plus `aws = {}`. This fails today, because the root takes no inputs. It would also fail if a null reached a child input that needs its default.
  - **`the_root_wires_the_normalizer_into_the_node`:** with `aws = {}`, `databricks = {}` and `runs = { prefixes = ["raw/provider=jaws"], join_tags = ["RunId", "TaskId"] }`, `local.node_cost` has the bucket, `normalized`, `["aws", "databricks"]` and the join tags.
  - **`a_databricks_only_root_expects_only_databricks`.**
- [x] **Step 2: Run** `cd $REPO && terraform init -backend=false && terraform test`. Expected: it fails, because the root has no variables.
- [x] **Step 3: Implement it.** Update the root README.
- [x] **Step 4: Run** `terraform test` at the root and in both submodules. Expected: all pass, and the submodules' tests are unchanged.
- [x] **Step 5: Commit** once per scope, since a commit takes exactly one:
  - `feat(billing-normalizer): treat a null input as its default`;
  - `feat(monitoring-node): treat a null input as its default`;
  - `feat(examples): wire the normalizer and the monitoring node in the root module`.

### Task 7: Docs and release

- [x] **Step 1: README** (`$MOD/README.md`):
  - **Off-hours:** Jaws's example, the allowed shapes, the times to avoid (01:00–03:00), the mute timing, and that snapshots move into the off window.
  - **The watchdog:** what posts and when, and the alarms' actions.
  - **Snapshots on AWS Backup,** and the vault's delete rule.
  - Regenerate terraform-docs.
- [x] **Step 2: Run** `$REPO/scripts/check.sh`. Expected: `All checks passed.`
- [x] **Step 3: Final review** (opus, whole branch), then one fix pass for Critical and Important findings, each RED→GREEN.
- [x] **Step 4: Ask the owner** before push, PR, merge and the 0.8.0 release.
- [x] **Step 5: Record it.**
  - Tick this plan.
  - Mark 07 released in the roadmap.
  - Add an "As built in v0.8.0" note to spec 6.9 and 6.10, recording AWS Backup in place of DLM.
  - Note for plan 09: confirm T9g keeps CPU credits while stopped (6.10).
  - Delete the workspace, and update memory.
