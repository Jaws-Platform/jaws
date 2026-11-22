# Databricks Billing Job Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `databricks-billing-export` submodule to `terraform-aws-jaws-databricks`, and release it as 0.2.0. It is a daily serverless job in a host workspace that writes whole-billing-period snapshots of Databricks' billing system tables to the billing bucket, in the layout `billing-normalizer` reads.

**Architecture:**
- **The job script:** one Python file, `files/billing_export.py`, uploaded as a workspace file and run by a `spark_python_task` on serverless jobs compute in standard performance mode.
  - Its logic is a pure function, `export(query, put, …)`, unit-tested with fakes.
  - A thin `main()` wires it to Spark and to boto3 with a Unity Catalog service credential.
- **The credential:** backed by an IAM role allowed only `s3:PutObject` under the Databricks raw prefix. It follows `databricks-dataset`'s pattern: a built role ARN, and a trust policy taken from the credential's external ID.
- **Identity:** the job runs as whoever applies the module (Jaws: the automation service principal). The module grants that identity `USE CATALOG` on `system`, `USE SCHEMA` and `SELECT` on `system.billing`, and `ACCESS` on the credential. Every grant is additive (`databricks_grant`).

**Tech Stack:**
- Terraform `>= 1.11`, with `hashicorp/aws ~> 6.0`, `databricks/databricks >= 1.142, < 2.0` (schema checked at 1.144.0) and `hashicorp/time ~> 0.13`;
- Python, tested with `unittest` and `pyarrow==21.0.0` under uv;
- Databricks serverless `environment_version = "3"`, with `pyarrow==21.0.0` and `boto3==1.40.0`.

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md), sections 6.3, 12.3 and 12.4. Series: [00-roadmap](2026-11-21-monitoring-00-roadmap.md). Its output contract is plan 02's "Databricks" input (the `billing-normalizer` README).

## Global Constraints

**Where things live**
- **Repo:** `$REPO` = `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-databricks`. Work on branch `feat/databricks-billing-export`, cut from `origin/main` (0.1.2).
- **Module:** `$MOD` = `$REPO/modules/databricks-billing-export`.

**Family conventions** (`databricks-dataset`)
- No provider configuration, and no organisation names (examples use `acme`).
- AWS resources carry `Name` and `Component = var.component`, which defaults to `"databricks-billing-export"`; Jaws passes `"billing"`.
- terraform-docs READMEs with absolute links.
- One-line commits with the `Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>` trailer.
- No cloud calls, and CI has no credentials.

**Output contract** (`billing-normalizer` 0.2.0)
- **Keys:**
  - `<prefix>/table=usage/billing_period=YYYY-MM/run=<YYYYMMDDTHHMMSSZ>/part-0.parquet`;
  - `<prefix>/table=list_prices/run=<…>/part-0.parquet`;
  - optionally `<prefix>/table=workspaces/run=<…>/part-0.parquet`;
  - `prefix` defaults to `raw/provider=databricks/source=system-tables`.
- **Map columns** are Parquet maps; structs are structs; `usage_quantity` and the prices are `decimal(38,18)`; times are `timestamp[us, UTC]`; `usage_date` is a `date32`.
- **Rows are sorted** before writing, so unchanged content gives byte-identical objects and therefore stable ETags.

**Explicit Arrow schemas.** Export only these columns. Struct fields not listed are dropped, so a new Databricks field never changes the output.
- **`usage`:**
  - `record_id`, `account_id`, `workspace_id`, `sku_name`, `cloud`;
  - `usage_start_time`, `usage_end_time`, `usage_date`;
  - `custom_tags` (map), `usage_unit`, `usage_quantity` (decimal);
  - `usage_metadata`, a struct of strings: `cluster_id`, `job_id`, `warehouse_id`, `instance_pool_id`, `node_type`, `job_run_id`, `notebook_id`, `dlt_pipeline_id`, `endpoint_name`, `endpoint_id`, `app_id`, `app_name`, `database_instance_id`, `job_name`, `run_name`, `budget_policy_id`, `usage_policy_id`;
  - `identity_metadata`, a struct of strings: `run_as`, `owned_by`, `created_by`;
  - `record_type`, `ingestion_date`, `billing_origin_product`;
  - `product_features`, a struct: `is_serverless` (bool), `is_photon` (bool), `jobs_tier`, `sql_tier`, `serving_type`, `performance_target`;
  - `usage_type`.
- **`list_prices`:**
  - `price_start_time`, `price_end_time`, `account_id`, `sku_name`, `cloud`, `currency_code`, `usage_unit`;
  - `pricing`, a struct: `default` (decimal), `promotional` (struct of `default` decimal), `effective_list` (struct of `default` decimal).
- **`workspaces`:** `workspace_id`, `workspace_name`, `workspace_url`, `status`.

**Periods**
- `recent` (the default) exports the previous and the current UTC month.
- `all` exports every month present in `system.billing.usage`; it is the backfill.
- A comma list of `YYYY-MM` exports those months.

**The job**
- schedule `0 0 6 * * ?`, `UTC`, `UNPAUSED`;
- `performance_target = "STANDARD"`, `max_concurrent_runs = 1`, `timeout_seconds = 3600`;
- task `export` with `max_retries = 2` and `min_retry_interval_millis = 600000`;
- job parameter `periods`, default `recent`, passed as `"{{job.parameters.periods}}"`. Job parameters are not pushed down to Python script tasks.

**Credential and role**
- `databricks_credential` with `purpose = "SERVICE"`, `isolation_mode = "ISOLATION_MODE_OPEN"`, `skip_validation = true` (the role's trust only exists after the credential) and `owner = var.owner_group_name`.
- The role's policy: `s3:PutObject` on `arn:aws:s3:::<bucket>/<prefix>/*`, plus the self `sts:AssumeRole` that Databricks requires.
- The role is created after the credential and waits 30 s for IAM propagation (`time_sleep`), as in `databricks-dataset`.

**The script**
- It reads the credential through `from databricks.sdk.runtime import dbutils` and `dbutils.credentials.getServiceCredentialsProvider(<name>)`, as Databricks documents it.
- Spec 12.3 is resolved this way: the documented path, Runtime 16.2+, on serverless. That serverless direct use works is confirmed by the job's first run in plan 08. A failure there fails the job, and the node's pipeline alert (Databricks delivery over 36 h old) fires.

## Review Focus

1. **Map and struct columns.** `custom_tags` (a dict) and the structs must come out as a Parquet `map` and `struct`, not a list of key/value structs, or the normalizer can't read the tags (Task 1, `test_written_usage_has_map_struct_and_decimal_types`).
2. **A Databricks field added tomorrow.** An extra struct field or column must not change or break the output (Task 1, `test_unknown_fields_are_dropped`).
3. **Unchanged prices give an unchanged object.** Rows arriving in a different order must give byte-identical Parquet, or every Databricks period rebuilds daily (Task 1, `test_parquet_is_byte_identical_for_the_same_rows`).
4. **January.** `recent` in January must export December of the previous year (Task 1, `test_recent_periods_cross_the_year`).
5. **A month with no usage, or a malformed periods value.** No usage still writes an empty, valid usage object for the period, so the normalizer sees the month. A bad `periods` value fails before anything is written (Task 2, `test_an_empty_period_writes_an_empty_snapshot`; Task 1, `test_bad_periods_are_rejected`).

---

### Task 1: Tooling and the exporter's pure functions

**Files:**
- Modify: `$REPO/scripts/check-module.sh` and `$REPO/.github/workflows/ci.yml` (add `- uses: astral-sh/setup-uv@v7` before "Check the module and its examples") and `$REPO/CONTRIBUTING.md`. Copy exactly what `terraform-aws-jaws-monitoring` 0.2.0 has.
- Create:
  - `$MOD/{versions.tf,main.tf,variables.tf,outputs.tf,README.md}` as a skeleton: `versions.tf` declares the three providers, the rest are comments, and the README is a title plus markers;
  - `$MOD/files/requirements-test.txt` (`pyarrow==21.0.0`);
  - `$MOD/files/billing_export.py`.
- Test: `$MOD/files/test_billing_export.py`, which loads the script with `importlib`, as `container-instance`'s tests do.

**Interfaces** (in `billing_export.py`):
- `periods_to_export(spec: str, today: date, available: Callable[[], list[str]]) -> list[str]`. `available` is called only for `all`. Raises `ValueError` on a bad spec.
- `month_bounds(period: str) -> tuple[str, str]`, returning ISO dates `[start, next month start)`.
- `run_stamp(now: datetime) -> str`, formatted `YYYYMMDDTHHMMSSZ`.
- `usage_key(prefix: str, period: str, run: str) -> str` and `table_key(prefix: str, table: str, run: str) -> str`.
- `USAGE_SCHEMA`, `PRICES_SCHEMA` and `WORKSPACES_SCHEMA` (`pa.Schema`, as in Global Constraints) and `SORT_KEYS` (by table: `usage` → `record_id`; `list_prices` → `sku_name`, `cloud`, `price_start_time`; `workspaces` → `workspace_id`).
- `to_parquet(rows: list[dict], schema: pa.Schema, sort_keys: Sequence[str]) -> bytes`. Its rules:
  - sort the rows, with `None` first, using `str()` for the comparison;
  - map columns given as dicts become `(key, value)` lists;
  - snappy compression;
  - `write_statistics=False`, so the output doesn't depend on the pyarrow build's statistics details.

- [x] **Step 1: Port the uv tooling** from `terraform-aws-jaws-monitoring` (`scripts/check-module.sh`'s Python step, the CI step and the CONTRIBUTING sentence). Then run `scripts/check.sh`.
  Expected: `All checks passed.` (no module uses it yet).

- [x] **Step 2: Write the failing tests**

```python
def test_recent_periods_are_the_previous_and_current_month(self):
    self.assertEqual(export.periods_to_export("recent", date(2026, 11, 21), lambda: []), ["2026-10", "2026-11"])

def test_recent_periods_cross_the_year(self):
    self.assertEqual(export.periods_to_export("recent", date(2026, 1, 3), lambda: []), ["2025-12", "2026-01"])

def test_all_uses_every_available_month_sorted(self):
    self.assertEqual(export.periods_to_export("all", date(2026, 11, 21), lambda: ["2026-02", "2025-12"]), ["2025-12", "2026-02"])

def test_explicit_months(self):
    self.assertEqual(export.periods_to_export("2026-09, 2026-10", date(2026, 11, 21), lambda: []), ["2026-09", "2026-10"])

def test_bad_periods_are_rejected(self):
    for spec in ("", "last", "2026-13", "2026-9", "2026-09,,2026-10"):
        with self.subTest(spec=spec), self.assertRaises(ValueError):
            export.periods_to_export(spec, date(2026, 11, 21), lambda: [])

def test_month_bounds_and_keys(self):
    self.assertEqual(export.month_bounds("2026-12"), ("2026-12-01", "2027-01-01"))
    self.assertEqual(export.run_stamp(datetime(2026, 11, 21, 6, 0, 7, tzinfo=UTC)), "20261121T060007Z")
    self.assertEqual(export.usage_key("raw/p", "2026-11", "R"), "raw/p/table=usage/billing_period=2026-11/run=R/part-0.parquet")
    self.assertEqual(export.table_key("raw/p", "list_prices", "R"), "raw/p/table=list_prices/run=R/part-0.parquet")
```

Also, with a fixture `usage_row()`: a dict shaped like `Row.asDict(recursive=True)`, with `custom_tags={"Project": "a"}`, `usage_quantity=Decimal("2.5")`, a `usage_metadata` dict and a `product_features` dict.
- **`test_written_usage_has_map_struct_and_decimal_types`:** read back with `pq.read_table`, `custom_tags` is a map, `usage_metadata` a struct, `usage_quantity` `decimal128(38, 18)` and `usage_date` `date32`. `to_pylist()[0]["custom_tags"] == [("Project", "a")]`.
- **`test_unknown_fields_are_dropped`:** an extra top-level key and an extra `usage_metadata` key give the same bytes as the row without them.
- **`test_parquet_is_byte_identical_for_the_same_rows`:** two price rows written in either order give equal bytes.

- [x] **Step 3: Run them to see them fail**

Run: `scripts/check-module.sh modules/databricks-billing-export`
Expected: FAIL at "script unit tests" (no `billing_export.py` yet).

- [x] **Step 4: Implement the pure functions and schemas.** A `periods` spec matches `^\d{4}-(0[1-9]|1[0-2])$` after splitting on commas and stripping.

- [x] **Step 5: Run them to see them pass**

Expected: `Ran 9 tests … OK`.

- [x] **Step 6: Commit**

`feat(databricks-billing-export): add the exporter's periods, keys and deterministic parquet` (with the trailer).

---

### Task 2: The export, and its glue to Spark and S3

**Files:**
- Modify: `$MOD/files/billing_export.py`
- Test: `$MOD/files/test_billing_export.py`

**Interfaces:**
- `export(query: Callable[[str], list[dict]], put: Callable[[str, bytes], None], *, prefix: str, periods: str, include_workspaces: bool, now: datetime) -> list[str]`. It returns the keys written, in order:
  1. `list_prices`;
  2. `workspaces`, if included;
  3. each period's usage.
  
  Every object of one run shares one run stamp.
- `USAGE_QUERY` = `"SELECT * FROM system.billing.usage WHERE usage_date >= DATE'{start}' AND usage_date < DATE'{end}'"`.
- `PRICES_QUERY` = `"SELECT * FROM system.billing.list_prices"`.
- `WORKSPACES_QUERY` = `"SELECT workspace_id, workspace_name, workspace_url, status FROM system.access.workspaces_latest"`.
- `PERIODS_QUERY` = `"SELECT DISTINCT date_format(usage_date, 'yyyy-MM') AS period FROM system.billing.usage"`.
- `main(argv: list[str]) -> None`:
  - parses `--bucket --prefix --credential --region --periods --include-workspaces`;
  - builds `spark` with `SparkSession.builder.getOrCreate()`;
  - defines `query = lambda q: [row.asDict(recursive=True) for row in spark.sql(q).collect()]`;
  - builds an S3 client from `boto3.Session(botocore_session=dbutils.credentials.getServiceCredentialsProvider(credential), region_name=region)`;
  - defines `put = lambda key, body: client.put_object(Bucket=…, Key=key, Body=body, ContentType="application/vnd.apache.parquet")`;
  - prints each key written.
- `if __name__ == "__main__": main(sys.argv[1:])`.

- [x] **Step 1: Write the failing tests** (a fake `query` maps each SQL string to rows; a fake `put` records keys and bytes)

- **`test_recent_export_writes_prices_then_each_period`:** with `now = 2026-11-21T06:00Z`, the keys are:
  - `[…list_prices/run=20261121T060000Z/part-0.parquet, …usage/billing_period=2026-10/run=…, …usage/billing_period=2026-11/run=…]`;
  - the usage queries asked for `2026-10-01..2026-11-01` and `2026-11-01..2026-12-01`;
  - no workspaces query was made.
- **`test_workspaces_are_exported_when_included`.**
- **`test_all_exports_every_month_the_table_has`:** `PERIODS_QUERY` returns `[{"period": "2025-12"}, {"period": "2026-01"}]`, so two usage keys are written.
- **`test_an_empty_period_writes_an_empty_snapshot`:** no usage rows still `put`s the period's object, and it reads back with 0 rows and the usage schema.
- **`test_nothing_is_written_when_periods_is_malformed`:** `periods="soon"` raises `ValueError`, and `put` was never called.

- [x] **Step 2: Run them to see them fail.** Expected: `AttributeError: … 'export'`.

- [x] **Step 3: Implement `export` and `main`.** Resolve the periods before querying or writing anything. In `main`, import pyspark, boto3 and the databricks SDK, so the tests never need them.

- [x] **Step 4: Run them to see them pass.** Expected: `Ran 14 tests … OK`.

- [x] **Step 5: Commit**

`feat(databricks-billing-export): export billing snapshots through a service credential` (with the trailer).

---

### Task 3: The Terraform module

**Files:**
- Modify: `$MOD/{versions.tf,variables.tf,main.tf,outputs.tf,README.md}`
- Create: `$MOD/iam.tf`, `$MOD/job.tf`, `$MOD/examples/basic/{main.tf,versions.tf}`
- Modify: `$REPO/README.md` (the submodule table).
- Test: `$MOD/tests/databricks_billing_export.tftest.hcl`

**Interfaces:**
- **Inputs:**
  - `name` (string, required, `^[a-z0-9-]{1,48}$`): names the role, the credential, the job and the workspace folder;
  - `bucket_name` (string, required);
  - `prefix` (default `"raw/provider=databricks/source=system-tables"`, with no leading, trailing or doubled slash);
  - `owner_group_name` (string, required): the credential's owner;
  - `include_workspaces` (bool, default `false`): also grant and export `system.access.workspaces_latest`, whose schema must be enabled;
  - `schedule` = `object({ cron = optional(string, "0 0 6 * * ?"), timezone = optional(string, "UTC"), paused = optional(bool, false) })`, default `{}`;
  - `environment_version` (default `"3"`);
  - `job_tags` (`map(string)`, default `{}`);
  - `component` (default `"databricks-billing-export"`).
- **Outputs:** `job_id`, `job_name`, `credential_name`, `role_arn`, `role_name`, `prefix`, `run_as` (the applying identity's user name).

- [x] **Step 1: Write the failing tests**

`tests/databricks_billing_export.tftest.hcl` uses mocked `aws` (`override_during = plan`, `aws_caller_identity` = `123456789012`, `aws_region` = `us-east-1`), mocked `databricks` with:
- `mock_data "databricks_current_user" { defaults = { user_name = "11111111-2222-3333-4444-555555555555" } }`;
- `mock_data "databricks_aws_unity_catalog_assume_role_policy" { defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" } }`;
- `mock_resource "databricks_workspace_file" { defaults = { workspace_path = "/Workspace/Shared/acme-billing-export/billing_export.py" } }`;

and mocked `time`. The variables are `name = "acme-billing-export"`, `bucket_name = "acme-billing"` and `owner_group_name = "acme-metastore-admins"`.

Its runs:
- **`the_credential_is_a_service_credential_on_a_built_role`:**
  - `purpose == "SERVICE"`, `aws_iam_role[0].role_arn == "arn:aws:iam::123456789012:role/acme-billing-export"`;
  - `skip_validation`, `isolation_mode == "ISOLATION_MODE_OPEN"`, `owner == "acme-metastore-admins"`.
- **`the_role_may_only_put_under_the_databricks_prefix`:** the policy statements are exactly `[{Sid = "PutSnapshots", Effect = "Allow", Action = "s3:PutObject", Resource = "arn:aws:s3:::acme-billing/raw/provider=databricks/source=system-tables/*"}, {Sid = "SelfAssume", Effect = "Allow", Action = "sts:AssumeRole", Resource = "arn:aws:iam::123456789012:role/acme-billing-export"}]`, and the role's tags are `{ Name, Component = "databricks-billing-export" }`.
- **`the_applying_identity_may_read_billing_and_use_the_credential`:**
  - `databricks_grant.system_catalog` gives `USE_CATALOG` on `system`;
  - `databricks_grant.billing` gives `USE_SCHEMA` and `SELECT` on `system.billing`;
  - `databricks_grant.credential` gives `ACCESS`;
  - all to `11111111-2222-3333-4444-555555555555`;
  - `length(databricks_grant.access) == 0`.
- **`workspaces_are_opt_in`:** `include_workspaces = true` gives one `system.access` grant (`USE_SCHEMA`, `SELECT`), and the task parameters contain `"--include-workspaces", "true"`.
- **`the_job_is_a_daily_serverless_python_task`:**
  - `performance_target == "STANDARD"`, `max_concurrent_runs == 1`;
  - schedule `0 0 6 * * ?`, `UTC`, `UNPAUSED`;
  - one task `export` with `environment_key == "default"`, no `new_cluster`, `spark_python_task[0].python_file == "/Workspace/Shared/acme-billing-export/billing_export.py"`;
  - the parameters are exactly `["--bucket", "acme-billing", "--prefix", "raw/provider=databricks/source=system-tables", "--credential", "acme-billing-export", "--region", "us-east-1", "--periods", "{{job.parameters.periods}}", "--include-workspaces", "false"]`;
  - one job parameter, `periods`, defaulting to `recent`;
  - environment `version "3"`, with dependencies `["pyarrow==21.0.0", "boto3==1.40.0"]`.
- **`the_script_is_uploaded_to_the_shared_folder`:** `databricks_workspace_file.script.path == "/Shared/acme-billing-export/billing_export.py"`, sourced from the module's `files/billing_export.py`.
- **`the_schedule_is_an_input`:** `{ cron = "0 30 7 * * ?", paused = true }` gives that cron and `PAUSED`.
- **`rejects_prefixes_with_stray_slashes`** and **`rejects_an_invalid_name`.**

- [x] **Step 2: Run them to see them fail.** Expected: undeclared variables and resources.

- [x] **Step 3: Implement the module**, following `databricks-dataset`.

**`main.tf`:**
- the data sources `aws_caller_identity`, `aws_region` and `databricks_current_user`;
- `databricks_credential.this`.

**`iam.tf`:**
- `data.databricks_aws_unity_catalog_assume_role_policy.this`, with `role_name = var.name` and `external_id = databricks_credential.this.aws_iam_role[0].external_id`;
- `aws_iam_role.this` and `aws_iam_role_policy.this`;
- `time_sleep.role_propagation`.

**`job.tf`:**
- `databricks_workspace_file.script`;
- the four grants, all `databricks_grant`;
- `databricks_job.this`, with `depends_on` the grants and `time_sleep`.

**README:**
- what it writes, pointing to `billing-normalizer`'s contract;
- the backfill: run the job once with `periods = all`;
- who it runs as, and what it is granted;
- that `include_workspaces` needs the `system.access` schema enabled;
- the cost (standard serverless mode, a one-minute minimum per run, cents a month);
- that this job's own spend shows on the Databricks dashboard;
- a usage snippet with `# x-release-please-version`.

- [x] **Step 4: Run them to see them pass.** Expected: `Success! 9 passed, 0 failed.`

- [x] **Step 5: Run the whole suite.** Run: `scripts/check.sh`. Expected: `All checks passed.`

- [x] **Step 6: Commit**

`feat(databricks-billing-export): run the billing export daily on serverless` (with the trailer).

---

### Task 4: Publish 0.2.0 (owner permission, asked for at this step)

- [x] **Step 1:** Push `feat/databricks-billing-export` and open the PR with `--template feat.md`. Expected: CI is green, including `terraform (databricks-billing-export)` running the Python tests.
- [x] **Step 2:** Squash-merge, then merge the `release 0.2.0` PR. Expected: the tag `v0.2.0` exists.
- [x] **Step 3: Record it on the Jaws docs branch.**
  - Tick this plan, and set the roadmap row to `released`.
  - Update spec 6.3: the job runs as the applying identity; the credential is open, with `ACCESS` only for that identity; the workspace table is opt-in.
  - Update spec 12.3 and 12.4 with what was verified and what plan 08's first run must confirm.
