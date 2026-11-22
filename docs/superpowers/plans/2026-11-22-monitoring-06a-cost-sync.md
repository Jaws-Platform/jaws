# Cost Sync Implementation Plan (06a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Get the cost data onto the node and watch the pipeline that delivers it, and release it as 0.5.0 of `terraform-aws-jaws-monitoring`. The pieces:
- **the normalizer writes a CSV twin** of every output;
- **`cost-sync` on the node** loads the twins into a `cost` database in Postgres every 30 minutes and writes pipeline metrics;
- **Grafana reads the database** as a read-only user;
- **the host dashboard gains its Pipeline row and the pipeline alerts.**

The cost dashboards and the cost alerts (budgets, anomaly, untagged) are plan 06b, with the daily rollups, the forecast and the budgets that 6.6 has `cost-sync` maintain, because only those dashboards and rules read them.

**Architecture:**
- **The normalizer** (Lambda, which has pyarrow) writes `data.csv.gz` beside each `data.parquet`, in a CSV dialect Postgres's `COPY` reads exactly.
- **`monitoring-cost-sync`** is a Python 3.9 stdlib script on the host, like the reconciler, run by a systemd timer. It lists the twins with `aws`, loads each changed one in its own transaction through `psql` in the Postgres container, and writes node-exporter textfile metrics. The node gets no new image and downloads nothing at boot.
- **The Grafana module** renders the pipeline rules and the Pipeline row from those metrics, which keeps all of 06a in Prometheus. SQL alerting (spec 12.7) is 06b's concern.

**Tech Stack:**
- Python 3.13 with pyarrow (the normalizer's tests, through uv);
- Python 3.9 stdlib on the host (`cost-sync`), tested with `unittest`, fake `aws` and fake `psql`;
- Postgres 17.12 (the pinned image) for an integration test in Docker;
- Terraform `>= 1.11` and `terraform test`;
- the Plan 05 Grafana smoke test.

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md):
- 6.1, the bucket layout;
- 6.4, the normalized schema;
- 6.5, the containers;
- 6.6, cost data on the node;
- 6.8, the pipeline rows;
- 6.12, task runs;
- 7, the `cost` input.

Series: [00-roadmap](2026-11-21-monitoring-00-roadmap.md).

## Global Constraints

**Where things live**
- **Repo:** `$REPO` = `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-monitoring`, on branch `feat/cost-sync` cut from `origin/main` (0.4.0).
- **Modules:** `$NORM` = `$REPO/modules/billing-normalizer`, `$MOD` = `$REPO/modules/monitoring-node`, and `$GRAF` = `$MOD/grafana`.

**Conventions**
- The Plan 04 and 05 conventions hold: no provider configuration or organisation names, terraform-docs READMEs, one-line commits with the `Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>` trailer, no cloud calls, and the house style for dashboards and rules (Plan 05 Global Constraints).

**The CSV twin** (`csv-twin-1`, written by `$NORM`)
- **Where:** `…/data.csv.gz` next to each `…/data.parquet`: the same rows and columns in the same order, gzip, UTF-8, with the same S3 metadata (`source-signature`, `warnings`).
- **Format:**
  - a header row of column names;
  - `csv.QUOTE_NOTNULL`, so a NULL is an unquoted empty field and every value, an empty string included, is quoted;
  - timestamps in ISO 8601 with their offset (`2026-11-01T00:00:00+00:00`);
  - booleans `true` or `false`;
  - maps as JSON objects with sorted keys;
  - floats as Python's `repr`.
- **Rebuilds:** `MAPPER_VERSION` becomes `"2"`, so every existing output is rebuilt with its twin.

**The node reads** (only with `cost` set)
- `<bucket>/<normalized_prefix>/schema=focus-1.2/provider=<p>/billing_period=<YYYY-MM>/data.csv.gz`
- `<bucket>/<normalized_prefix>/schema=runs-1/event_month=<YYYY-MM>/data.csv.gz`
- `<bucket>/<normalized_prefix>/_runs/latest.json`
- The role gets `s3:GetObject` on `arn:aws:s3:::<bucket>/<normalized_prefix>/*`, and `s3:ListBucket` on the bucket with `s3:prefix` `StringLike` `<normalized_prefix>/*`. Nothing else in the bucket.

**The `cost` database** (database `cost`, schema `cost`)

| Object | What it holds |
|---|---|
| `cost.lines` | One row per normalized cost row: `key` (the S3 key), `provider`, `period`, then each FOCUS column in snake_case (`ProviderName` → `provider_name` … `BillingCurrency` → `billing_currency`), `tags jsonb`, `project`, `component`, `environment` (from `x_Project`, `x_Component`, `x_Environment`), `serverless boolean`, `source`. Indexes on `(provider, charge_period_start)` and a GIN index on `tags`. |
| `cost.run_events` | One row per runs-1 event: `key`, then every runs-1 column in snake_case (`tags`, `links` and `attributes` as `jsonb`). |
| `cost.loads` | `key` (primary key), `kind` (`focus` or `runs`), `provider`, `period`, `etag`, `last_modified`, `rows`, `billed_cost`, `loaded_at`. |
| `cost.normalizer_runs` | `started_at` (primary key), `ended_at`, `status`, `errors`, `warnings`, `record jsonb`. |
| `cost.meta` | `name` (primary key) and `value`: `schema_version`. |
| view `cost.task_runs` | One row per `run_key`: the `started` event's fields; `ended_at` from `finished` or `swept`; `outcome` from `finished`, `swept` when swept, or null while running; `exit_code`, `interrupted_at`, `swept_reason`; `join_tags` (the jsonb of the `run_join_tags`). |
| view `cost.task_run_costs` | `run_key` and `billed_cost`: the sum of `cost.lines.billed_cost` whose `tags @> join_tags`. |

- **Loading:**
  - a CSV column maps to its snake_case name, `x_<Tag>` columns to the tag's lowercase name, and `x_Serverless` and `x_Source` to `serverless` and `source`;
  - unknown columns are ignored, and missing ones are NULL;
  - a header name that isn't `^[A-Za-z_][A-Za-z0-9_]*$` fails that output.
- **`COST_SCHEMA_VERSION = "1"`.** When `cost.meta` holds a different version, `cost-sync` drops schema `cost` and rebuilds it. The database is a rebuildable cache, so every output is then reloaded.
- **The reader:** role `cost_reader` (LOGIN, password from the generated secret `COST_READER_PASSWORD`), with CONNECT on `cost`, USAGE on `cost`, and SELECT on every table and view (default privileges too). `cost-sync` sets the password every run, sent over stdin, never argv.

**`cost-sync`'s metrics** (`<textfile dir>/cost_sync.prom`, written atomically)

| Metric | Value |
|---|---|
| `monitoring_cost_sync_success` | 1 if the last run loaded everything, else 0 |
| `monitoring_cost_sync_last_success_seconds` | Unix time of the last successful run; the first run's time until one succeeds, from `/data/cost-sync/state.json` |
| `monitoring_cost_sync_outputs` | outputs loaded |
| `monitoring_normalizer_last_success_seconds` | `ended_at` of the newest `ok` run seen, or `cost-sync`'s first run if none yet |
| `monitoring_normalizer_last_run_failed` | 1 if `latest.json` says `error`, else 0 |
| `monitoring_normalizer_errors`, `monitoring_normalizer_warnings` | counts in `latest.json` |
| `monitoring_cost_newest_charge_seconds{provider}` | newest `charge_period_start` per expected provider, or the first run if none |
| `monitoring_cost_newest_output_seconds{provider}` | newest S3 `LastModified` of the provider's twins, or the first run if none |
| `monitoring_task_run_overdue_hours{project,run_key,instance_id}` | hours past `max_hours + 1` for each run with a `started` event, no `finished` or `swept`, and a `max_hours`; only while overdue |
| `monitoring_task_run_over_ceiling_usd{project,run_key}` | `billed_cost − ceiling_usd` for each run whose billed cost exceeds a set ceiling; only while over |

- **Clocks:** the "first run" fallback starts each staleness clock when the node starts watching. A brand-new node isn't critical in its first hours, but alerts if data never comes.
- **Failure:** if S3 or Postgres can't be reached, the file holds only `success 0` and `last_success`, so the `cost-sync` rule fires and nothing else reads stale numbers as current.

**Pipeline rules** (group `pipeline`, folder `Monitoring`, `labels.area = pipeline`, uid `pipeline-<key>-<severity>`, file `rules-pipeline.json` with its own catalogue and `deleteRules`, and the Plan 05 conventions)

| Key | Title | Query | Op | Warning | Critical | For | Panel | Needs |
|---|---|---|---|---|---|---|---|---|
| `normalizer-late` | Normalizer late | `(time() - monitoring_normalizer_last_success_seconds) / 3600` | gt | normalizer_hours.w | normalizer_hours.c | 2m | 63 | cost |
| `normalizer-failed` | Normalizer run failed | `monitoring_normalizer_last_run_failed` | gt | — | 0.5 (count) | 2m | 68 | cost |
| `aws-charges-stale` | AWS charges stale | `(time() - monitoring_cost_newest_charge_seconds{provider="aws"}) / 86400` | gt | aws_charge_days.w | aws_charge_days.c | 2m | 64 | provider aws |
| `databricks-stale` | Databricks delivery stale | `(time() - monitoring_cost_newest_output_seconds{provider="databricks"}) / 3600` | gt | databricks_delivery_hours.w | .c | 2m | 65 | provider databricks |
| `cost-sync-late` | Cost sync late | `(time() - monitoring_cost_sync_last_success_seconds) / 3600` | gt | cost_sync_hours.w | .c | 2m | 62 | cost |
| `task-run-overdue` | Task run possibly leaked | `monitoring_task_run_overdue_hours` | gt | — | 0 | 2m | 66 | cost |
| `task-run-over-ceiling` | Task run over its ceiling | `monitoring_task_run_over_ceiling_usd` | gt | — | 0 | 2m | 67 | cost |

- **New `thresholds` attributes** (optional, higher is worse):
  - `normalizer_hours {3, 12}`;
  - `aws_charge_days {3, 5}`;
  - `databricks_delivery_hours {36, 60}`;
  - `cost_sync_hours {2, 6}`.
- **The Pipeline row** (only with `cost`):
  - 60 row, 61 text;
  - 62 Last cost-sync (hours);
  - 63 Last successful normalizer run (hours);
  - 64 Newest AWS charge (days; provider aws);
  - 65 Newest Databricks delivery (hours; provider databricks);
  - 66 Overdue task runs (hours, legend `{{project}} {{run_key}}`);
  - 67 Task runs over their ceiling (USD);
  - 68 Normalizer: last run failed, errors and warnings.
  
  Each panel draws its rule's lines, at y 91–118. Rules 66 and 67 draw a critical line at 0.

**Grafana's Postgres data source** (only with `cost`): uid `cost`, type `grafana-postgresql-datasource`, url `postgres:5432`, database `cost`, user `cost_reader`, `secureJsonData.password = $COST_READER_PASSWORD`, `jsonData = {sslmode = "disable", postgresVersion = 1700}`.

**The node, with `cost`**
- **Input:**
  ```hcl
  cost = object({
    bucket            = string
    normalized_prefix = optional(string, "normalized")
    providers         = optional(set(string), ["aws", "databricks"])
    run_join_tags     = optional(list(string), ["RunId", "TaskId"])
  })
  ```
  Default `null`. 06b adds the budgets and the anomaly floor.
- **The bundle:**
  - gains `cost-sync/config.json`: `{bucket, prefix, providers, run_join_tags}`;
  - generates `COST_READER_PASSWORD`;
  - gives Grafana `COST_READER_PASSWORD = "${COST_READER_PASSWORD:?}"`.
- **User data** installs `/usr/local/bin/monitoring-cost-sync` and its units:
  - `monitoring-cost-sync.service`: oneshot, `Requires` and `After` docker;
  - `monitoring-cost-sync.timer`: `OnBootSec=2min`, `OnUnitActiveSec=30min`.
  
  With no `cost-sync/config.json` in the current release, the script removes its textfile and exits 0.
- **Overrides:** `cost-sync` reads `MONITORING_ROOT`, and `MONITORING_PSQL`, a command prefix with a default of `docker exec -i monitoring-postgres-1 psql -U monitoring -v ON_ERROR_STOP=1`. It isn't `docker compose exec`, because Compose interpolates `${…:?}` on every command and the script doesn't hold the stack's values. `MONITORING_TEXTFILE_DIR` too. These let the tests run the real script.

## Review Focus

1. **An output rewritten in place.** The normalizer overwrites `normalized/` keys, and a new ETag must replace that output's rows in one transaction: never duplicated, never briefly missing (Task 2, `a_rewritten_output_replaces_its_rows`).
2. **One bad output.** A corrupt gzip, or a header name that isn't safe, must not stop the other outputs or wipe its own last good rows (Task 3, `a_bad_output_keeps_its_rows_and_the_rest_load`).
3. **S3 or Postgres unreachable.** No partial state; `success 0`; `last_success` kept, so `cost-sync-late` fires on time (Task 3, `with_s3_unreachable_nothing_changes_and_it_says_so`, `with_postgres_down_it_says_so`).
4. **A brand-new node before the first normalizer run or delivery.** No critical in the first hours, but an alert once the thresholds pass with no data (Task 2, `before_any_data_the_clocks_start_at_the_first_run`).
5. **A run with no `max_hours` or no ceiling, or one still inside `max_hours + 1h`.** It is never overdue or over its ceiling. A swept run is never overdue (Task 2, `only_runs_past_their_limits_are_reported`).

---

### Task 1: The normalizer writes a CSV twin

**Files:**
- Create: `$NORM/files/normalizer/twin.py`, `$NORM/files/test_twin.py`, `$NORM/files/fixtures/twin/focus-aws.csv`, `$NORM/files/fixtures/twin/focus-databricks.csv`, `$NORM/files/fixtures/twin/runs.csv` (one twin per output: the contract fixtures `cost-sync`'s integration test loads)
- Modify: `$NORM/files/normalizer/run.py` (write the twin with each output), `$NORM/files/normalizer/schema.py` (`MAPPER_VERSION = "2"`), `$NORM/files/test_run.py`, `$NORM/README.md`

**Interfaces:**
- **Produces:** `write_twin(rows: Sequence[Mapping], schema: pa.Schema) -> bytes`, which returns gzip bytes in the `csv-twin-1` format, with columns in `schema` order.
- **In `run.py`:** each rebuilt output `put`s `…/data.csv.gz` (content type `application/gzip`) with the same metadata as its Parquet, and after it. An unchanged output writes neither.

- [ ] **Step 1: Write the failing tests**

`test_twin.py`:
- **`test_nulls_and_empty_strings_differ`:** a row with `None` and `""` gives `,` and `,""` in the decoded CSV.
- **`test_values_are_written_as_postgres_reads_them`:**
  - `datetime(2026, 11, 1, tzinfo=UTC)` becomes `"2026-11-01T00:00:00+00:00"`;
  - `True` becomes `"true"`;
  - `{"b": "2", "a": "1"}` becomes `"{""a"": ""1"", ""b"": ""2""}"`;
  - `0.1` becomes `"0.1"`.
- **`test_the_twin_matches_the_contract_fixtures`:** the rows defined in the test produce exactly the three fixtures (gunzipped). Write the rows to cover:
  - for focus, AWS rows and Databricks rows for 2026-11, including an untagged row and an AWS row tagged `RunId=r1,TaskId=t1` with `BilledCost = 12.5`;
  - for runs (`at` on 2026-11-20, so the open run is long overdue): r1/t1 `started` with `ceiling_usd = 10` and `max_hours = 4`, then `finished` with outcome `passed`; r2/t2 `started` with `max_hours = 1` and no end; r3/t3 `started` with no `max_hours`; r4/t4 `started`, then `swept`.

`test_run.py`:
- **`test_each_rebuilt_output_has_its_twin`:** after a run over the existing fakes, every `data.parquet` has a `data.csv.gz` with the same metadata, and their rows match.
- **`test_an_unchanged_output_rewrites_neither`:** a second run with no new deliveries `put`s nothing under `normalized/` except `_runs/`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd $NORM && uv run --no-project --python 3.13 --with-requirements files/requirements-test.txt python -m unittest discover -s files -p 'test_*.py'`
Expected: FAIL with `ModuleNotFoundError: No module named 'normalizer.twin'`.

- [ ] **Step 3: Implement `twin.py` and the twin in `run.py`, and bump `MAPPER_VERSION`**

Use `csv.writer(…, quoting=csv.QUOTE_NOTNULL, lineterminator="\n")` into a `gzip.GzipFile(mtime=0)`, so the bytes are reproducible.

- [ ] **Step 4: Run the suite**

Run: `cd $REPO && scripts/check-module.sh modules/billing-normalizer`
Expected: PASS.

- [ ] **Step 5: Commit**

`feat(billing-normalizer): write a csv twin of every output for the monitoring node`

---

### Task 2: `cost-sync` loads the twins into Postgres

**Files:**
- Create: `$MOD/files/monitoring-cost-sync.py`, `$MOD/tests/test-cost-sync-postgres.sh`, `$MOD/tests/fake_aws_s3.py` (serves a local directory as the bucket for `s3api list-objects-v2` and `s3 cp`)

**Interfaces:**
- **Produces:** `monitoring-cost-sync`. It runs once under `flock <root>/run/monitoring-cost-sync.lock` and exits 0 when everything loaded, 1 otherwise.
- **Config:** `<root>/data/config/current/cost-sync/config.json`, `{"bucket", "prefix", "providers", "run_join_tags"}`.
- **State:** `<root>/data/cost-sync/state.json`, `{"first_run", "last_success"}`.
- **The order of a run:**
  1. **Database and reader:** ensure the database, the schema (rebuilding it on a version change) and the reader.
  2. **List:** list both `schema=` prefixes, never `_runs/`.
  3. **Load:** load each twin whose ETag differs from `cost.loads`, each in its own transaction: `DELETE` its rows, `COPY` into a temp table of `text` columns named by its header, `INSERT … SELECT` with casts, then upsert `cost.loads`.
  4. **Remove:** delete the rows of outputs no longer listed.
  5. **Normalizer runs:** upsert `latest.json` into `cost.normalizer_runs`.
  6. **Metrics:** compute them in one query and write the textfile.

The integration test runs a real Postgres from the pinned image, with `MONITORING_PSQL="docker exec -i <container> psql -U monitoring -v ON_ERROR_STOP=1"`, the fake `aws` first on `PATH`, and the `$NORM` contract fixtures gzipped into a scratch bucket. It is a bash script with a Python helper for the assertions, and every check is a named case:

- [ ] **Step 1: Write the failing integration test**

- **`first_sync_loads_every_output`:**
  - `cost.lines` has the fixture's rows;
  - `cost.run_events` has its 6 events;
  - `cost.loads` has 3 rows;
  - the run exits 0;
  - `monitoring_cost_sync_success 1`.
- **`a_rewritten_output_replaces_its_rows`:** rewrite the AWS twin with one row removed, so a new ETag. After the second run, `cost.lines` for that key has one row fewer and no duplicates.
- **`a_removed_output_loses_its_rows`:** delete the Databricks twin. Its rows are gone, and so is its `cost.loads` row.
- **`task_runs_merge_their_events_and_cost`:**
  - `cost.task_runs` has 4 runs;
  - the `finished` run has `outcome = passed` and `ended_at` set;
  - the swept run has `outcome = swept`;
  - `cost.task_run_costs` for `RunId=r1;TaskId=t1` equals the fixture's tagged `billed_cost`.
- **`only_runs_past_their_limits_are_reported`:** exactly one `monitoring_task_run_overdue_hours` series, for r2/t2. Exactly one `monitoring_task_run_over_ceiling_usd` series, for r1/t1, with value 2.5. r3 (no `max_hours`) and r4 (swept) appear in neither.
- **`before_any_data_the_clocks_start_at_the_first_run`:** with an empty bucket, `newest_charge`, `newest_output` and `normalizer_last_success` all equal `state.json`'s `first_run`.
- **`grafanas_reader_reads_and_nothing_else`:**
  - `psql -U cost_reader` with the generated password can `SELECT` from `cost.task_runs`;
  - `INSERT INTO cost.lines` is denied.
- **`a_schema_version_change_rebuilds`:** set `cost.meta.schema_version` to `0`. The next run reloads every output.

- [ ] **Step 2: Run it to see it fail**

Run: `cd $MOD && bash tests/test-cost-sync-postgres.sh`
Expected: FAIL, because `files/monitoring-cost-sync.py` doesn't exist.

- [ ] **Step 3: Implement `monitoring-cost-sync.py`**

One `psql` stream per transaction (stdin, `-v ON_ERROR_STOP=1`), with the `COPY … FROM STDIN` data inline, ended by `\.`. Metrics are written to `.cost_sync.prom.tmp`, then renamed.

- [ ] **Step 4: Run it**

Run: `cd $MOD && bash tests/test-cost-sync-postgres.sh && shellcheck tests/test-cost-sync-postgres.sh`
Expected: `cost sync (postgres): OK`; shellcheck prints nothing.

- [ ] **Step 5: Commit**

`feat(monitoring-node): load the normalized cost data into postgres on the node`

---

### Task 3: `cost-sync` when things go wrong

**Files:**
- Create: `$MOD/files/test_monitoring_cost_sync.py` (stdlib `unittest`, with fake `aws` and fake `psql` executables in the style of `test_monitoring_reconcile.py`)
- Modify: `$MOD/files/monitoring-cost-sync.py`

**Interfaces:** Task 2's. The fake `psql` records each stream it receives, and can fail any stream containing a given marker.

- [ ] **Step 1: Write the failing tests**

- **`test_without_cost_config_it_removes_its_metrics_and_exits_0`.**
- **`test_a_bad_output_keeps_its_rows_and_the_rest_load`:** one twin is corrupt gzip, another has the header name `bad-name`. Both are reported (exit 1, `success 0`), no stream is sent for either, the other outputs' streams are sent, and their `cost.loads` upserts are in them.
- **`test_with_s3_unreachable_nothing_changes_and_it_says_so`:** the fake `aws` fails the listing. No load stream is sent, the textfile holds `success 0` and the earlier `last_success`, and the run exits 1.
- **`test_with_postgres_down_it_says_so`:** the fake `psql` fails the first stream, with the same expectations.
- **`test_a_failed_load_leaves_the_last_success_alone`:** run once successfully, then with one failing load. `last_success` is unchanged, and `success` is 0.
- **`test_the_reader_password_never_reaches_argv`:** no recorded argv contains the generated password, and a stream does.
- **`test_runs_one_at_a_time`:** a second run while the lock is held waits rather than overlapping. Use the reconciler test's lock pattern.

Each test also runs under Python 3.9: `uv run -q --no-project --python 3.9 python -m unittest …`.

- [ ] **Step 2: Run them to see them fail, then fix the script until they pass**

Run: `cd $MOD && python3 -m unittest discover -s files -p 'test_*.py'`
Expected: first the named failures; then `OK` under 3.13 and 3.9, with `bash tests/test-cost-sync-postgres.sh` still OK.

- [ ] **Step 3: Commit**

`fix(monitoring-node): keep cost-sync's last good data and say so when a load fails`

(Use `test(…)` instead if the tests passed as first written.)

---

### Task 4: The node runs `cost-sync`, and Grafana reads the database

**Files:**
- Modify: `$MOD/variables.tf` (`cost`), `$MOD/bundle.tf` (config file, generated secret, Grafana's environment), `$MOD/iam.tf` (the read statement), `$MOD/user-data.tf` and `files/user-data.yaml.tftpl` (script and units), `$MOD/grafana.tf` (pass `cost`), `$GRAF/variables.tf`, `$GRAF/main.tf` (the data source), `$MOD/tests/test-grafana-provisioning.sh` (Postgres in phase 1)
- Test: `$MOD/tests/monitoring_node.tftest.hcl`, `$MOD/tests/grafana.tftest.hcl`

**Interfaces:**
- **`$MOD` `cost`:** as in Global Constraints, validated:
  - `bucket` matches the S3 naming pattern;
  - `normalized_prefix` has no leading or trailing `/`;
  - `providers` ⊆ {`aws`, `databricks`};
  - `run_join_tags` is non-empty.
- **`$GRAF`** gets `cost = object({ providers = set(string) })`, or null.

- [ ] **Step 1: Write the failing tests**

`monitoring_node.tftest.hcl`, with `cost = { bucket = "acme-billing" }`:
- **`with_cost_the_node_reads_only_normalized_data`:** there is an `ReadNormalizedCost` statement whose GetObject resource is `arn:aws:s3:::acme-billing/normalized/*`, and whose ListBucket has the `s3:prefix` condition `normalized/*`. Without `cost`, there is no such statement.
- **`with_cost_the_bundle_configures_cost_sync`:**
  - `jsondecode(local.bundle.files["cost-sync/config.json"]) == {bucket = "acme-billing", prefix = "normalized", providers = ["aws", "databricks"], run_join_tags = ["RunId", "TaskId"]}`;
  - `contains(local.bundle.generated, "COST_READER_PASSWORD")`;
  - Grafana's environment has `COST_READER_PASSWORD == "$${COST_READER_PASSWORD:?}"`.
- **`the_user_data_runs_cost_sync_every_30_minutes`:** the user data has `monitoring-cost-sync.timer` with `OnUnitActiveSec=30min` and `OnBootSec=2min`.
- **`rejects_an_unknown_provider`, `rejects_a_prefix_with_slashes`:** each with `expect_failures = [var.cost]`.

`grafana.tftest.hcl`:
- **`with_cost_grafana_reads_the_cost_database`:** the data source uid `cost` has the fields above. Without `cost`, it is absent (and `prune` removes it from Grafana).

Smoke phase 1:
- starts the pinned Postgres on a Docker network with Grafana (alias `postgres`);
- runs `monitoring-cost-sync` against an empty fake bucket, to make the database and the reader;
- passes `COST_READER_PASSWORD` to Grafana;
- checks that `GET /api/datasources/uid/cost/health` reports `OK`, and that a `/api/ds/query` of `SELECT count(*) FROM cost.task_runs` returns 0.

Phase 2 has no `cost`, and the data source is gone.

- [ ] **Step 2: Run them to see them fail**

Run: `cd $MOD && terraform test && bash tests/test-grafana-provisioning.sh`
Expected: FAIL (`cost` not declared, the data source missing).

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run them**

Run: `cd $REPO && scripts/check-module.sh modules/monitoring-node`
Expected: PASS, with `grafana smoke: OK` and the data source healthy.

- [ ] **Step 5: Commit**

`feat(monitoring-node): run cost-sync on the node and let grafana read the cost database`

---

### Task 5: The Pipeline row and the pipeline alerts

**Files:**
- Create: `$GRAF/rules-pipeline.tf`
- Modify: `$GRAF/queries.tf`, `$GRAF/dashboard-host.tf` (row 60), `$GRAF/main.tf`, `$GRAF/validate.tf` (the reserved uids are every module catalogue's), `$MOD/variables.tf` (the four new `thresholds` attributes and their order validation), `$MOD/README.md`
- Test: `$MOD/tests/grafana.tftest.hcl`, `$MOD/tests/monitoring_node.tftest.hcl`

**Interfaces:** The pipeline rule table and the Pipeline row in Global Constraints. The `every_rule_mirrors_its_panel` and `every_rule_waits_at_least_two_minutes` runs now cover every module rules file.

- [ ] **Step 1: Write the failing tests**

`grafana.tftest.hcl`, with `cost = { providers = ["aws", "databricks"] }` unless stated:
- **`the_pipeline_row_shows_with_cost`:** panels 60–68 exist, and row 60 is followed by text panel 61. Without `cost`, none exist.
- **`pipeline_rules_need_their_providers`:**
  - with `providers = ["aws"]`, `pipeline-databricks-stale-*` isn't rendered and is in `deleteRules`, and panel 65 is absent;
  - without `cost`, every `pipeline-*` uid is in `deleteRules` and none is rendered.
- **`pipeline_rules_carry_area_pipeline`:** every `pipeline-*` rule has `labels.area == "pipeline"`, is in group `pipeline` in folder `Monitoring`, and links `monitoring-host`.
- **`the_task_run_rules_fire_on_any_overrun`:** `pipeline-task-run-overdue-critical` and `-over-ceiling-critical` are `gt 0`, and panels 66 and 67 draw `vector(0)`.
- **Extend `every_rule_mirrors_its_panel` and `switched_off_rules_are_deleted_and_only_those`** to `rules-pipeline.json`. The pipeline catalogue has 11 uids: 7 keys, 4 of them with both severities.
- **`rejects_a_uid_the_pipeline_rules_own`:** an extra rule with uid `pipeline-cost-sync-late-warning` fails the plan.

`monitoring_node.tftest.hcl`:
- **`the_default_thresholds_are_the_specs`:** gains the four attributes.
- **`rejects_pipeline_thresholds_in_the_wrong_order`.**

- [ ] **Step 2: Run them to see them fail**

Run: `cd $MOD && terraform test`
Expected: FAIL, with `Invalid index` on `rules-pipeline.json`, among others.

- [ ] **Step 3: Implement**

`rules-pipeline.tf` mirrors `rules-host.tf`: specs, instances, `needed`, and a file with `deleteRules`. Refactor only what both files use, the common rule fields and the threshold step, into `rules-common.tf`.

- [ ] **Step 4: Run them, the smoke test and the suite**

Run: `cd $REPO && scripts/check.sh`
Expected: `All checks passed.`. The smoke test's phase 1 lists the 21 host rules, the 11 pipeline rules and the 2 extras. Phase 2, without `cost`, lists the 21 host rules.

- [ ] **Step 5: Commit**

`feat(monitoring-node): watch the cost pipeline on the host dashboard and alert on it`

---

### Task 6: Docs and the 0.5.0 release

- [ ] **Step 1: Write the docs**
  - **`$MOD/README.md`:** the `cost` input; what `cost-sync` does and when; its metrics; the `cost` database and its tables and views (for 06b and for ad hoc SQL through a Session Manager shell); the pipeline rules; and that the node reads only `normalized/`.
  - **`$NORM/README.md`:** the twin and its format.
  - **The example** adds `cost`.
- [ ] **Step 2:** Run `cd $REPO && scripts/check.sh`. Expected: `All checks passed.`
- [ ] **Step 3:** Commit `docs(monitoring-node): document cost-sync, the cost database and the pipeline alerts`.
- [ ] **Step 4:** The final whole-branch review and fix pass (executing-plans).
- [ ] **Step 5:** Ask the owner, then publish: push, open the PR (`feat: load the cost data onto the monitoring node and watch its pipeline`), squash-merge once CI is green, merge the 0.5.0 release PR, and check the registry.
- [ ] **Step 6:** Record it: tick this plan; in the roadmap, split 06 into 06a (released) and 06b; add an "As built in v0.5.0" note to spec 6.6. Then delete the plan's workspace and update the memory note.
