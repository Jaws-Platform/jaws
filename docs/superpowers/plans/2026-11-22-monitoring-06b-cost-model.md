# Cost Model, Cost Alerts and the Overview Implementation Plan (06b)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the cost rows on the node into the numbers the owner watches, and release it as 0.6.0 of `terraform-aws-jaws-monitoring`:
- **the cost model in SQL:** daily spend, month to date, the forecast, budgets, anomalies and new untagged spend;
- **the cost alerts:** the budget forecast, month to date over budget, the daily anomaly, and new untagged spend;
- **the Cost · Overview dashboard.**

The Project, Databricks and Tasks dashboards are plan 06c.

**Architecture:**
- **The model is views** in the `cost` schema that `cost-sync` already creates. The data is small, and views are always current, so there are no materialized rollups to refresh.
- **Budgets** come from the bundle (`cost-sync/config.json`), and `cost-sync` rewrites `cost.budgets` every run.
- **Time:** every view reads `cost.now()`, which is `now()` unless the session sets `cost.now`, so tests can pin the clock.
- **The rules** are Grafana SQL rules on the Cost data source in table form: string columns become labels, and the one numeric column is the value. The smoke test checks them through Grafana's own `/api/v1/eval` against real rows, which settles spec 12.7.

**Tech Stack:**
- Postgres 17.12 SQL (views, `percentile_cont`, `generate_series`);
- the 06a `cost-sync` and its Postgres integration test;
- Terraform `terraform test`;
- the Grafana smoke test.

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md):
- 6.6, the forecast and complete days;
- 6.7, Cost · Overview and units;
- 6.8, the budget, anomaly and untagged rows;
- 7, the `cost` input;
- 8, the `budgets` example;
- 12.7, SQL alerting.

Series: [00-roadmap](2026-11-21-monitoring-00-roadmap.md).

## Global Constraints

**Where things live**
- **Repo:** `$REPO` = `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-monitoring`, on branch `feat/cost-model` from `origin/main` (0.5.0).
- **Modules:** `$MOD` = `$REPO/modules/monitoring-node`, and `$GRAF` = `$MOD/grafana`.

**Conventions:** as in Plans 04–06a (house style, the validator, the deleteRules catalogue, `for` at least 2m, one-line commits with the trailer, no cloud calls). The host scripts stay on Python 3.9 stdlib (the owner's decision).

**Days and money**
- **Days are UTC calendar days of `charge_period_start`** (AWS bills in UTC). Grafana shows them in the browser's zone.
- **Amounts are `billed_cost` in USD.** `charge_category` `Tax` and `Credit` rows count in spend, but never as untagged.
- **A day is complete** when its end is at least 48 hours before `cost.now()` (6.6). Newer days are partial.
- **The forecast** is (this month's complete days' spend) + (the average of the last 7 complete days) × (days left in the month that aren't complete yet). That is 6.6's formula, with the partial days replaced by the average instead of counted short.

**The model** (in `cost-sync`'s schema SQL; `COST_SCHEMA_VERSION` stays `"1"`, since everything is `IF NOT EXISTS` or `CREATE OR REPLACE`)

| Object | Columns |
|---|---|
| function `cost.now()` | `coalesce(nullif(current_setting('cost.now', true), '')::timestamptz, now())` |
| table `cost.budgets` | `scope` (`total`, `project` or `account`), `name` (`total`, a project, or an account id or name), `monthly_usd`; primary key `(scope, name)` |
| view `cost.daily` | `day` (date), `complete` (bool), `provider`, `account_id`, `account_name`, `project` (`(untagged)` when null), `environment`, `service`, `charge_category`, `billed_cost` (sum) |
| view `cost.as_of` | `day`: the newest complete day with data |
| view `cost.month_to_date` | one row per scope: `total`, each `project`, each `account` (by id), with `scope`, `name`, `mtd`, `complete_mtd`, `avg7`, `days_left`, `forecast`, `budget` (null if none), `used_percent`, `forecast_percent`. The `account` scope matches a budget by account id or name |
| view `cost.anomalies` | For the newest day with data: one row per `total`, each `project` and each `service`, with `kind`, `name`, `day`, `spend`, `median14` (the median of the 14 complete days before it; a complete day with no rows counts 0), `ratio` (spend ÷ median, null when the median is 0), `excess` (spend − median) |
| view `cost.untagged` | Untagged rows (`project` is `(untagged)`, not Tax or Credit), per `day`, `account_id`, `account_name`, `service`, `billed_cost` |
| view `cost.untagged_new` | For the newest day with data: each `(account_id, service)` with untagged spend that day, with `account_name`, `spend`, `prior_spend` (its untagged spend in the 14 days before) |

**Inputs**
- **`cost` gains:**
  - `budgets = optional(object({ total = optional(number), projects = optional(map(number), {}), accounts = optional(map(number), {}) }), {})`;
  - `anomaly_floor_usd = optional(number, 2)`.
  
  Every budget is above 0, and the floor is at least 0. `config.json` gains `budgets`.
- **`thresholds` gains:** `anomaly_ratio = {warning 2, critical 4}` (higher is worse, warning above 1) and `untagged_daily_usd = {warning 0.5}`.

**Cost rules** (group `cost`, folder `Cost`, interval `5m`, `labels.area = cost`, uid `cost-<key>-<severity>`, file `rules-cost.json` with its catalogue and `deleteRules`, link `cost-overview`). Each runs one SQL query on `datasourceUid: cost` (`format: table`, `editorMode: code`) with a threshold step C on it.

| Key | Title | SQL (string columns are labels) | Op | Warning | Critical | For | Panel |
|---|---|---|---|---|---|---|---|
| `budget-forecast` | Budget: month-end forecast | `SELECT scope, name, forecast_percent FROM cost.month_to_date WHERE budget IS NOT NULL` | gt | 100 | — | 2m | 32 |
| `budget-spent` | Budget: month to date | `SELECT scope, name, used_percent FROM cost.month_to_date WHERE budget IS NOT NULL` | gt | — | 100 | 2m | 32 |
| `anomaly` | Daily spend anomaly | `SELECT kind, name, ratio FROM cost.anomalies WHERE kind IN ('total', 'project') AND excess > <anomaly_floor_usd> AND ratio IS NOT NULL` | gt | ratio.w | ratio.c | 2m | 42 |
| `untagged-new` | New untagged spend | `SELECT account_name, service, spend FROM cost.untagged_new WHERE prior_spend = 0` | gt | untagged.w | — | 2m | 53 |

- `noDataState: OK` (no rows means nothing is over), and `execErrState: Alerting`.
- **The catalogue:** 4 keys and 5 uids. All are rendered with `cost`, and all are deleted without it.

**Cost · Overview** (`grafana/dashboards/Cost/overview.json`, uid `cost-overview`, folder `Cost`, the last 90 days, 30s refresh, read-only, only with `cost`)
- **Variables:** `provider`, `account`, `project` and `environment`: multi-value, with All, each from `SELECT DISTINCT … FROM cost.daily`. Every panel query filters on them.
- **Panels** (ids fixed; SQL is the builder's, on `cost.*`):

| Id | Panel | Shows |
|---|---|---|
| 1 | Month to date (stat) | `mtd` of `total` |
| 2 | Forecast (stat) | `forecast` of `total`, coloured at 80 % and 100 % of its budget |
| 3 | Budget used (gauge) | `used_percent` of `total`, at 80 and 100 |
| 4 | Yesterday, partial (stat) | yesterday's spend |
| 5 | vs last month, same day (stat) | this month to date against last month to the same day, in % |
| 6 | Untagged this month (stat) | the month's untagged spend |
| 7 | Data as of (stat) | `cost.as_of.day` |
| 10, 11 | Trend (row, text) | |
| 12 | Daily spend by provider (time series, stacked bars) | |
| 13 | Monthly totals (bars, its own time range of 12 months) | |
| 20, 21 | Where it goes (row, text) | |
| 22, 23, 24, 25 | Month to date by project, by service (top 10), by account, by provider (bar gauges) | |
| 30, 31 | Budgets (row, text) | |
| 32 | Budgets (table) | `scope`, `name`, `budget`, `mtd`, `forecast`, `used_percent`, `forecast_percent`; the percentages coloured at 80 and 100 |
| 40, 41 | Movers (row, text) | |
| 42 | Furthest above their 14-day norm (table) | `cost.anomalies`, by `ratio`, top 10, with the anomaly thresholds as colours |
| 50, 51 | Untagged (row, text) | |
| 52 | Untagged this month by service and account (table) | |
| 53 | New untagged spend (table) | `cost.untagged_new`, coloured at the threshold |

- **Every rule's panel** exists, and its description states the rule's numbers.

## Review Focus

1. **The first days of a month,** with no complete day yet. The forecast must not divide by zero or show nothing: it falls back to the last 7 complete days, whichever month they were in (Task 1, `the_forecast_carries_across_a_month_boundary`).
2. **A project that spent nothing on most of the last 14 days.** Its median is 0, so its ratio is null and the anomaly rule stays quiet unless the floor is passed; the total still alerts (Task 1, `a_new_project_is_not_an_anomaly_of_infinity`; Task 3's rule filter `ratio IS NOT NULL`).
3. **Budgets keyed by account name or account id.** Both must match, and a budget for a project or account with no spend shows 0 used, not missing (Task 1, `budgets_match_by_id_or_name_and_show_with_no_spend`).
4. **A steady untagged charge (public IPv4).** It alerts once, on its first day, and never again (Task 1, `steady_untagged_spend_is_new_only_once`).
5. **Grafana evaluating the SQL rules on real rows.** Table results become one alert instance per row, labelled by its string columns (Task 3, the smoke test's `/api/v1/eval` checks).

---

### Task 1: The cost model in SQL

**Files:**
- Modify: `$MOD/files/monitoring-cost-sync.py` (the schema SQL: `cost.now()`, the table and the views; and rewriting `cost.budgets` from `config["budgets"]` every run, in one transaction)
- Modify: `$MOD/tests/test-cost-sync-postgres.sh` (new cases); create `$MOD/tests/cost_model_rows.sql` (the rows the cases load)

**Interfaces:** the model in Global Constraints.
- `config.json` gains `"budgets": {"total": n|null, "projects": {…}, "accounts": {…}}`.
- An absent `budgets` key means no budgets, so a 0.5.0 bundle still works.

- [ ] **Step 1: Write the failing cases**

`cost_model_rows.sql` inserts straight into `cost.lines` (key `test/model`, provider `aws`, account `570327089884` named `production`), at fixed dates in UTC:
- **Project `alpha`:** $10 on each of 2026-10-01 … 2026-11-18, then $50 on 2026-11-21.
- **Project `beta`:** $5 on 2026-11-21 only.
- **Untagged:**
  - service `Amazon Virtual Private Cloud`: $0.60 on each of 2026-11-05 … 2026-11-21;
  - service `Amazon S3`: $3 on 2026-11-21 only;
  - a `Tax` row of $4 on 2026-11-21.
- **Budgets** (through `config.json`):
  - `total = 400`;
  - `projects = {alpha = 300, gamma = 50}`;
  - `accounts = {"production" = 1000}` (by name; `sub_account_name` is `production`).

The cases run their checks in a `psql` session that first does `SET cost.now = '2026-11-21T12:00:00Z'`.
- **`complete_days_are_48_hours_old`:** in `cost.daily`, 2026-11-18 is complete, 2026-11-19 isn't, and `cost.as_of.day` is 2026-11-18.
- **`the_forecast_uses_the_last_7_complete_days`:** `alpha` has `complete_mtd = 180` (Nov 1–18), `avg7 = 10`, `days_left = 12`, and `forecast = 300`, so `forecast_percent = 100`.
- **`the_forecast_carries_across_a_month_boundary`:** with `cost.now = '2026-11-02T06:00:00Z'`, `alpha` has `complete_mtd = 0`, `avg7 = 10` (from Oct 24–30, since Oct 31 isn't 48 hours old yet), and `forecast = 300`.
- **`budgets_match_by_id_or_name_and_show_with_no_spend`:**
  - the `account` row for `570327089884` has `budget = 1000`;
  - `gamma` has `mtd = 0` and `used_percent = 0`;
  - `total`'s `budget = 400`.
- **`a_new_project_is_not_an_anomaly_of_infinity`:**
  - on 2026-11-21, `alpha` has `median14 = 10` (over Nov 5–18, the 14 complete days before it), `ratio = 5` and `excess = 40`;
  - `beta` has `median14 = 0` and a null `ratio`;
  - `total` has `spend = 62.6` against `median14 = 10.6`, a `ratio` above 4.
- **`steady_untagged_spend_is_new_only_once`:** `cost.untagged_new` for 2026-11-21 lists S3 with `prior_spend = 0`, and VPC with `prior_spend > 0`. Tax isn't untagged.
- **`budgets_are_rewritten_every_run`:** remove `gamma` from `config.json` and run `cost-sync` again. `cost.budgets` no longer has it.

- [ ] **Step 2: Run them to see them fail**

Run: `cd $MOD && bash tests/test-cost-sync-postgres.sh`
Expected: FAIL in `complete_days_are_48_hours_old` (`relation "cost.daily" does not exist`).

- [ ] **Step 3: Implement the function, the table, the views and the budget rewrite**

The 14 days before a day, and a month's days, come from `generate_series`, so a day with no rows counts as 0. `percentile_cont(0.5)` gives the median.

- [ ] **Step 4: Run them**

Run: `cd $MOD && bash tests/test-cost-sync-postgres.sh && python3 -m unittest discover -s files -p 'test_*.py'`
Expected: `cost sync (postgres): OK`; unit tests OK (also under Python 3.9.6).

- [ ] **Step 5: Commit** `feat(monitoring-node): model spend, the forecast, budgets, anomalies and untagged spend in the cost database`

---

### Task 2: The inputs

**Files:** `$MOD/variables.tf` (`cost.budgets`, `cost.anomaly_floor_usd`, the two `thresholds`), `$MOD/grafana.tf` (`config.json`, and passing `anomaly_floor_usd` to `$GRAF`), `$GRAF/variables.tf`; tests in `$MOD/tests/monitoring_node.tftest.hcl` and the `thresholds` copy in `tests/grafana.tftest.hcl` and the smoke test.

- [ ] **Step 1: Write the failing tests**
  - **`with_budgets_cost_sync_gets_them`:** with `budgets = {total = 100, projects = {alpha = 50}}`, `jsondecode(config.json).budgets == {total = 100, projects = {alpha = 50}, accounts = {}}`.
  - **`the_default_thresholds_are_the_specs`:** gains `anomaly_ratio {2, 4}` and `untagged_daily_usd {0.5}`.
  - **`rejects_a_zero_budget`, `rejects_a_negative_anomaly_floor`, `rejects_an_anomaly_ratio_of_one`:** each with its `expect_failures`.
- [ ] **Step 2: Run them to see them fail** (`terraform test`). Expected: FAIL; the attributes don't exist.
- [ ] **Step 3: Implement, then run** `cd $MOD && terraform test`. Expected: PASS.
- [ ] **Step 4: Commit** `feat(monitoring-node): take budgets, the anomaly floor and the cost thresholds as inputs`

---

### Task 3: The cost alerts

**Files:**
- Create: `$GRAF/rules-cost.tf` (the specs; `rules-common.tf` gains `cost` as an area, plus a third `source`, `postgres`, built by its own for-expression)
- Modify: `$GRAF/main.tf` (`rules-cost.json`), `$GRAF/validate.tf` (nothing new is reserved beyond the catalogue), `$MOD/tests/grafana_smoke.py` and `tests/test-grafana-provisioning.sh` (rule evaluation)
- Test: `$MOD/tests/grafana.tftest.hcl`

**Interfaces:** the cost rule table. Folder `Cost` is also the Overview's folder, so the smoke test's one-folder-per-title check covers it.

- [ ] **Step 1: Write the failing tests**

`grafana.tftest.hcl`:
- **`cost_rules_run_sql_on_the_cost_database`:** with `cost`, every `cost-*` rule's A step has `datasourceUid == "cost"`, `model.format == "table"` and a `rawSql`. The anomaly SQL contains `excess > 2` at the default floor, and `excess > 5` with `anomaly_floor_usd = 5`.
- **`cost_rules_link_the_overview`:** each links `cost-overview` and a panel that exists.
- **`the_cost_rules_need_cost`:** without `cost`, all 5 uids are in `deleteRules`, and none is rendered.
- **`cost_thresholds_reach_the_rules`:** with `anomaly_ratio = {3, 6}`, the anomaly rule is `gt 3` and `gt 6`.

Smoke phase 1, after Grafana is healthy:
- **The rows:** load rows relative to the real `now()`. Project `alpha` spends $1 a day for the 20 days before today, then $10 today; there is untagged S3 today only; and a `total` budget of $1 (with `budgets.total = 1` in phase 1's `cost-sync` config).
- **Evaluate:** `POST /api/v1/eval` with each cost rule's `data` from the rendered `rules-cost.json`.
- **Expect** firing instances, labelled by their string columns:
  - `budget-spent` and `budget-forecast` for `total`;
  - `anomaly` for `alpha`, at both severities;
  - `untagged-new` for the S3 row.

- [ ] **Step 2: Run them to see them fail**

Run: `cd $MOD && terraform test && bash tests/test-grafana-provisioning.sh`
Expected: FAIL, with `Invalid index` on `rules-cost.json`.

- [ ] **Step 3: Implement**

The Postgres data step is:

```
{ refId = "A", datasourceUid = "cost", relativeTimeRange = { from = 600, to = 0 },
  model = { refId = "A", datasource = { type = "grafana-postgresql-datasource", uid = "cost" },
            rawSql = <sql>, format = "table", editorMode = "code" } }
```

The threshold step C reads A.

**Fallback (12.7):** if `/api/v1/eval` shows Grafana refusing table results, switch the rules to time-series form. That means a `time` column of `cost.now()` and `metric` built from the labels. Record a ruling.

- [ ] **Step 4: Run them, and the suite**

Run: `cd $REPO && scripts/check-module.sh modules/monitoring-node`
Expected: PASS; `grafana smoke: OK`, with the eval checks named.

- [ ] **Step 5: Commit** `feat(monitoring-node): alert on budgets, daily anomalies and new untagged spend`

---

### Task 4: Cost · Overview

**Files:**
- Create: `$GRAF/dashboard-cost-overview.tf`
- Modify: `$GRAF/main.tf` (`module_dashboards` gains `Cost/overview.json` with `cost`)
- Test: `$MOD/tests/grafana.tftest.hcl`

**Interfaces:** the Overview table.
- SQL panels use the Cost data source, with `format: table` or `time_series`, and Grafana's `$__timeFilter(…)` and variable syntax. The dashboard JSON isn't environment-expanded, and the validator's `$` rule applies only to alerting files.
- The house-style builders from `dashboard-host.tf` are reused where the panel types match. Otherwise, write the panel objects directly.

- [ ] **Step 1: Write the failing tests**
  - **`the_overview_follows_the_house_style`:**
    - uid `cost-overview`, folder `Cost` (path `Cost/overview.json`);
    - the last 90 days, 30s refresh, `editable` false;
    - four variables on the Cost data source;
    - unique ids;
    - every row followed by a text panel, and every other panel with a description.
  - **`every_cost_panel_reads_the_cost_database`:** every target's datasource uid is `cost`, and every `rawSql` names a `cost.` object.
  - **`the_overview_needs_cost`:** without `cost`, there is no `Cost/overview.json`.
  - **`the_budget_and_anomaly_panels_state_their_numbers`:** panel 32's description contains `100`, and panel 42's contains `2` and `4`.
- [ ] **Step 2: Run them to see them fail.** Expected: `Invalid index` on `Cost/overview.json`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `cd $REPO && scripts/check-module.sh modules/monitoring-node`. Expected: PASS; the smoke test lists `cost-overview` in folder `Cost`, and no second `Cost` folder.
- [ ] **Step 5: Commit** `feat(monitoring-node): add the cost overview dashboard`

---

### Task 5: Docs and the 0.6.0 release

- [ ] **Step 1: Write the docs.** The README covers:
  - the budgets and the anomaly floor;
  - the cost rules table;
  - the model's views, for ad hoc SQL;
  - the forecast and complete-day definitions;
  - what the Overview shows.
  
  The example adds a `budgets` block.
- [ ] **Step 2: Run** `cd $REPO && scripts/check.sh`. Expected: `All checks passed.`
- [ ] **Step 3: Commit** `docs(monitoring-node): document the cost model, the cost alerts and the overview`
- [ ] **Step 4:** The final whole-branch review and fix pass.
- [ ] **Step 5:** Ask the owner, then publish:
  1. push;
  2. open the PR, `feat: model the cost data, alert on it and add the cost overview`;
  3. squash-merge once CI is green;
  4. merge the 0.6.0 release PR;
  5. check the registry.
- [ ] **Step 6: Record it:**
  - tick the plan;
  - mark 06b released, and add 06c to the roadmap;
  - add an "As built in v0.6.0" note to spec 6.6–6.8;
  - delete the workspace;
  - update the memory note.
