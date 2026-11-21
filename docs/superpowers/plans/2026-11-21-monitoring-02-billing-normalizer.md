# Billing Normalizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `billing-normalizer` submodule to `terraform-aws-jaws-monitoring`. It is an hourly Lambda that turns every billing source's newest delivery under `raw/` into FOCUS-aligned Parquet under `normalized/`, and flattens task-run records into an event table. Release it as 0.2.0.

**Architecture:**
- **The code:** a plain-Python package, `normalizer`, in `modules/billing-normalizer/files/`. A `Store` protocol is the only boundary: S3 in Lambda, a dict in tests.
- **Mappers:** one per provider (`aws`, `databricks`), plus `runs` for task-run events. They are pure functions over rows.
- **The orchestrator** (`run`) rebuilds a `(provider, period)` only when the signature of its source changes. It writes a run record every time.
- **Terraform:** packages the directory with `archive_file`, and runs it on the AWS SDK for pandas layer, which provides pyarrow.

**Tech Stack:**
- Python 3.13, with tests using `unittest` and `pyarrow==21.0.0` under uv;
- Terraform `>= 1.11`, `hashicorp/aws ~> 6.0` and `hashicorp/archive ~> 2.7`;
- Lambda on arm64;
- EventBridge Scheduler.

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md), sections 5 (the generalizing contract), 6.4, 6.12 and 12.6. Series: [00-roadmap](2026-11-21-monitoring-00-roadmap.md). Builds on plan 01 (`billing-bucket` layout).

## Global Constraints

**Where things live**
- **Repo:** `$REPO` = `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-monitoring`. Work on branch `feat/billing-normalizer`, cut from `origin/main`.
- **Module:** `$MOD` = `$REPO/modules/billing-normalizer`.

**Conventions carried over from plan 01**
- **Module code:** no provider configuration, no tag maps, `Name` and `Component = "billing"`, no organisation names (examples use `acme`), and a terraform-docs README with absolute links.
- **Commits:** one line, plus `Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>`.
- **No cloud:** nothing calls AWS. CI has no credentials.

**The Lambda**
- runtime `python3.13`, architecture `arm64`, handler `normalizer.handler.handler`;
- timeout `900`, memory `1024`, no reserved concurrency (new accounts can have too little to reserve);
- schedule `rate(1 hour)`, using EventBridge Scheduler;
- log group `/aws/lambda/<name>`, retained 30 days by default.

**The layer**
- Default `arn:aws:lambda:<region>:336392948345:layer:AWSSDKPandas-Python313-Arm64:17` (awswrangler 3.18.0, verified 2026-11-21). Its pyarrow is `>=21, <27`, so the code uses only `pyarrow.parquet.read_table`, `pa.Table.from_pylist` and `pyarrow.parquet.write_table`.
- Tests pin `pyarrow==21.0.0`.

**Output layout** (`<np>` = `normalized_prefix`, default `normalized`)
- `<np>/schema=focus-1.2/provider=<aws|databricks>/billing_period=YYYY-MM/data.parquet`
- `<np>/schema=runs-1/event_month=YYYY-MM/data.parquet`
- `<np>/_runs/<YYYYMMDDTHHMMSSZ>.json` and `<np>/_runs/latest.json`
- Each Parquet object carries the S3 user metadata `source-signature`, the sha256 of `MAPPER_VERSION`, the provider's config fingerprint and its source ETags.
- `MAPPER_VERSION = "1"`. Bumping it rebuilds everything.

**Input contracts** (the normalizer reads; other plans write)
- **AWS (plan 01):**
  - Under `aws.delivery_prefix` (the export's `delivery_prefix`), each `metadata/BILLING_PERIOD=YYYY-MM/` folder holds manifests named `…Manifest.json`. The newest by LastModified wins.
  - Its `executionId` and `dataFiles` (`s3://<bucket>/<key>` URIs) name the delivery.
- **Databricks (plan 03 writes this):**
  - `<prefix>/table=usage/billing_period=YYYY-MM/run=<YYYYMMDDTHHMMSSZ>/part-*.parquet`, the columns of `system.billing.usage`;
  - `<prefix>/table=list_prices/run=<…>/part-*.parquet`, the columns of `system.billing.list_prices`;
  - optionally `<prefix>/table=workspaces/run=<…>/part-*.parquet`, with `workspace_id` and `workspace_name`;
  - the newest `run=` (compared as a string) wins.
- **Runs (plan 08 writes this):** one JSON object per event, under each prefix in `runs.prefixes`, at `…/date=YYYY-MM-DD/<anything>.json`, matching the `runs-1` event format in Task 4.

**Databricks pricing.** `cost = usage_quantity × pricing.effective_list.default`, falling back to `pricing.default`. The price matches on `sku_name` and `cloud` where `price_start_time <= usage_end_time < price_end_time`, with a null end meaning open. This is the documented join. List price is the billed price for a pay-as-you-go account.

## Review Focus

1. **A month with no deliveries yet,** or a provider whose prefix is empty. The run must succeed and write nothing for it, not fail (Task 5, `test_empty_sources_write_only_a_run_record`).
2. **One provider failing,** for example a corrupt Parquet file or a manifest pointing at another bucket. The other providers must still be normalized, and the failure must show in the run record and the Lambda's error metric (Task 5, `test_one_provider_failing_still_builds_the_others_and_raises`).
3. **Databricks usage with no matching price,** for example a new SKU. It must not crash or vanish: it is kept at zero cost and counted as a warning (Task 3, `test_unpriced_usage_costs_zero_and_is_reported`).
4. **A malformed task-run record.** It must be skipped and reported, never block the cost data or the other records (Task 4, `test_invalid_records_are_skipped_and_reported`).
5. **Tags written as `user:Project` or `user_project` instead of `Project`.** AWS doesn't document FOCUS's tag key format. Every form must promote to `x_Project` (Task 1, `test_promotes_user_prefixed_keys`).

---

### Task 1: Python tooling, the package skeleton, tags and Parquet

**Files:**
- Modify: `$REPO/scripts/check-module.sh`, in the "script unit tests" step.
- Modify: `$REPO/.github/workflows/ci.yml`, in the `modules` job.
- Modify: `$REPO/CONTRIBUTING.md`, in the section on module scripts.
- Create: `$MOD/files/requirements-test.txt` (`pyarrow==21.0.0`).
- Create: `$MOD/files/normalizer/{__init__.py,tags.py,schema.py,parquet.py}`.
- Create: `$MOD/files/fakes.py`, the test helpers: `FakeStore` (Task 2) and `parquet_bytes(rows, schema)`.
- Create: `$MOD/{versions.tf,main.tf,variables.tf,outputs.tf,README.md}`. The first three are comments only for now; `README.md` is a title plus empty terraform-docs markers. They make `list-modules.sh` find the module.
- Test: `$MOD/files/test_tags.py`, `$MOD/files/test_parquet.py`

**Interfaces:**
- Produces:
  - `normalizer.tags.promote(tags: Mapping[str, str] | None, names: Sequence[str]) -> dict[str, str | None]`
  - `normalizer.schema`:
    - `MAPPER_VERSION: str = "1"`;
    - `promoted_column(name: str) -> str`, returning `"x_" + name`;
    - `focus_schema(promoted_tags: Sequence[str]) -> pa.Schema`;
    - `runs_schema() -> pa.Schema`.
  - `normalizer.parquet.read_rows(body: bytes) -> list[dict]`, where map columns come back as `dict`.
  - `normalizer.parquet.write_rows(rows: Sequence[Mapping], schema: pa.Schema) -> bytes`, snappy-compressed. Map fields are accepted as `dict`.

- [x] **Step 1: Teach `check-module.sh` to run Python tests with their requirements**

In the `files/test_*.py` step:
- If `files/requirements-test.txt` exists, run `uv run --no-project --python 3.13 --with-requirements files/requirements-test.txt python -m unittest discover -s files -p 'test_*.py'`.
- Otherwise run `python3 -m unittest …` as today.

In `ci.yml`, add `- uses: astral-sh/setup-uv@v10` before "Check the module and its examples".

In `CONTRIBUTING.md`, add one sentence on `files/requirements-test.txt`.

- [x] **Step 2: Write the failing tests**

`files/test_tags.py`:

```python
import unittest
from normalizer.tags import promote

class PromoteTest(unittest.TestCase):
    def test_promotes_exact_keys(self):
        self.assertEqual(promote({"Project": "braveheart", "Owner": "x"}, ["Project", "Component"]),
                         {"Project": "braveheart", "Component": None})

    def test_promotes_user_prefixed_keys(self):
        self.assertEqual(promote({"user:Project": "a"}, ["Project"]), {"Project": "a"})
        self.assertEqual(promote({"user_project": "b"}, ["Project"]), {"Project": "b"})

    def test_exact_key_wins_over_prefixed_forms(self):
        self.assertEqual(promote({"user:Project": "a", "Project": "b"}, ["Project"]), {"Project": "b"})

    def test_blank_values_and_missing_maps_are_untagged(self):
        self.assertEqual(promote({"Project": "  "}, ["Project"]), {"Project": None})
        self.assertEqual(promote(None, ["Project"]), {"Project": None})
```

`files/test_parquet.py` round-trips one FOCUS row. It has these columns: every column `focus_schema(["Project"])` lists, `Tags = {"Project": "a"}`, `ChargePeriodStart = datetime(2026, 11, 1, tzinfo=UTC)` and `x_Project = "a"`. Its tests:
- `test_round_trip_preserves_maps_and_utc_timestamps`: `read_rows(write_rows([row], schema)) == [row]`.
- `test_schema_lists_focus_columns_then_promoted_then_extensions`:
  - `focus_schema(["Project", "Component"]).names[:3] == ["ProviderName", "BillingAccountId", "BillingAccountName"]`;
  - `.names[-4:] == ["x_Project", "x_Component", "x_Serverless", "x_Source"]`.
- `test_runs_schema_has_the_event_columns`: `runs_schema().names` starts `["run_key", "tags", "event", "at"]`.

- [x] **Step 3: Run them to see them fail**

Run: `cd $REPO && scripts/check-module.sh modules/billing-normalizer`
Expected: FAIL at "script unit tests" with `ModuleNotFoundError: No module named 'normalizer.tags'`.

- [x] **Step 4: Implement `tags.py`, `schema.py` and `parquet.py`**

**`promote`:** for each name, try the keys `name`, `f"user:{name}"` and `f"user_{name.lower()}"`, in that order. Strip the value; blank becomes `None`.

**`focus_schema` columns, in order:**
- `ProviderName`, `BillingAccountId`, `BillingAccountName`, `SubAccountId`, `SubAccountName` (string);
- `BillingPeriodStart`, `ChargePeriodStart`, `ChargePeriodEnd` (`timestamp("ms", tz="UTC")`);
- `ChargeCategory`, `ChargeClass`, `ServiceName`, `ServiceCategory`, `SkuId`, `RegionId`, `ResourceId` (string);
- `ConsumedQuantity` (float64), `ConsumedUnit` (string);
- `ListCost`, `BilledCost`, `EffectiveCost` (float64), `BillingCurrency` (string);
- `Tags` (`map_(string, string)`);
- then `x_<tag>` (string) for each promoted tag, then `x_Serverless` (bool) and `x_Source` (string).

**`runs_schema` columns:**
- `run_key`, `tags` (map), `event` and `at` (`timestamp ms UTC`);
- `project`, `campaign`, `kind`, `instance_type`;
- `accelerators` (int32);
- `market`, `zone`, `instance_id`;
- `hourly_usd`, `on_demand_hourly_usd`, `worst_case_usd`, `ceiling_usd` and `max_hours` (float64);
- `outcome`, `exit_code` (int32), `interrupted_at` (timestamp), `reason`;
- `links` and `attributes` (map), then `x_Source`.

**`write_rows`:** convert map fields from `dict` to a list of `(key, value)` tuples before `pa.Table.from_pylist(rows, schema=schema)`.

**`read_rows`:** do the reverse.

- [x] **Step 5: Run them to see them pass**

Run: `scripts/check-module.sh modules/billing-normalizer`
Expected: every step passes, and the unit tests report `Ran 7 tests … OK`.

- [x] **Step 6: Commit**

```bash
git add scripts/check-module.sh .github/workflows/ci.yml CONTRIBUTING.md modules/billing-normalizer
git commit -q -m "feat(billing-normalizer): add the FOCUS schema, tag promotion and parquet io" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The store and the AWS mapper

**Files:**
- Create: `$MOD/files/normalizer/store.py`, `$MOD/files/normalizer/aws.py`
- Modify: `$MOD/files/fakes.py`, adding `FakeStore`.
- Test: `$MOD/files/test_aws.py`

**Interfaces:**
- Consumes: `promote`, `promoted_column`, `read_rows` (Task 1).
- Produces:
  - `store.ObjectInfo(key: str, etag: str, last_modified: datetime)`, a frozen dataclass;
  - the `store.Store` Protocol:
    - `list(prefix: str) -> list[ObjectInfo]`, sorted by key;
    - `get(key: str) -> bytes`;
    - `metadata(key: str) -> dict[str, str] | None`, where `None` means missing;
    - `put(key: str, body: bytes, *, metadata: dict[str, str], content_type: str) -> None`.
  - `store.S3Store(bucket: str, client)`, using `list_objects_v2` with a paginator, `get_object`, `head_object` (a 404 means `None`) and `put_object`.
  - `fakes.FakeStore()`:
    - `.add(key: str, body: bytes, last_modified: datetime | None = None)`;
    - implements `Store`;
    - its ETag is the quoted md5 hex;
    - `.puts` lists the keys written.
  - `aws.AwsDelivery(period: str, execution_id: str, data_keys: tuple[str, ...])`.
  - `aws.latest_aws_deliveries(store: Store, bucket: str, delivery_prefix: str) -> dict[str, AwsDelivery]`.
  - `aws.map_aws_rows(rows: Iterable[Mapping], *, promoted_tags: Sequence[str], exclude_publishers: Sequence[str], source: str) -> list[dict]`.

- [x] **Step 1: Write the failing tests**

`files/test_aws.py` builds manifests with `json.dumps`, and data with `fakes.parquet_bytes` in the shape of the FOCUS 1.2 AWS columns. Its tests:

- **`test_latest_delivery_per_period_comes_from_its_newest_manifest`:**
  - Setup: `metadata/BILLING_PERIOD=2026-11/` holds `x-Manifest.json` (execution `a`, older) and `Manifest.json` (execution `b`, newer). `2026-10` holds one manifest (execution `c`).
  - Assert: `{p: d.execution_id for p, d in latest_aws_deliveries(...).items()} == {"2026-10": "c", "2026-11": "b"}`, and the `data_keys` are the manifest's `dataFiles` with `s3://acme-billing/` stripped.
- **`test_manifest_files_in_another_bucket_are_an_error`:** a `dataFiles` entry of `s3://other/x.parquet` raises `ValueError` naming the manifest key.
- **`test_maps_focus_columns_and_promotes_tags`:**
  - Setup: one row with `BilledCost = 1.5`, `Tags = {"user:Project": "braveheart"}`, `ServiceName = "Amazon Elastic Compute Cloud"` and `SubAccountId = "570327089884"`.
  - Assert: the output keeps those values, sets `x_Project == "braveheart"`, `x_Serverless is None` and `x_Source == "src"`, and has exactly the keys of `focus_schema(["Project"]).names`.
- **`test_rows_from_excluded_publishers_are_dropped`:** `PublisherName = "Databricks"` with `exclude_publishers=["Databricks"]` gives `[]`.
- **`test_null_tags_become_an_empty_map`:** `Tags = None` gives `Tags == {}` and `x_Project is None`.

- [x] **Step 2: Run them to see them fail**

Run: `scripts/check-module.sh modules/billing-normalizer`
Expected: FAIL with `ModuleNotFoundError: No module named 'normalizer.aws'`.

- [x] **Step 3: Implement `store.py`, `fakes.FakeStore` and `aws.py`**

**`latest_aws_deliveries`:**
- List `f"{delivery_prefix}/metadata/"`.
- Group keys ending in `Manifest.json` by the `BILLING_PERIOD=(\d{4}-\d{2})` path segment.
- Take the newest `last_modified` in each group.
- Parse its JSON into an `AwsDelivery`.

**`map_aws_rows`:**
- Copy the base FOCUS columns.
- Coerce `Tags` to a `dict`.
- Add the promoted `x_` columns, `x_Serverless = None` and `x_Source = source`.
- Drop rows whose `PublisherName` is in `exclude_publishers`.

- [x] **Step 4: Run them to see them pass**

Run: `scripts/check-module.sh modules/billing-normalizer`
Expected: `Ran 12 tests … OK`.

- [x] **Step 5: Commit**

`git commit -m "feat(billing-normalizer): map AWS FOCUS 1.2 deliveries"` (with the trailer).

---

### Task 3: The Databricks mapper

**Files:**
- Create: `$MOD/files/normalizer/databricks.py`
- Test: `$MOD/files/test_databricks.py`

**Interfaces:**
- Consumes: `ObjectInfo`, `Store` (Task 2), and `promote` and `promoted_column` (Task 1).
- Produces:
  - `databricks.DatabricksDeliveries(usage: dict[str, tuple[ObjectInfo, ...]], prices: tuple[ObjectInfo, ...], workspaces: tuple[ObjectInfo, ...])`.
  - `databricks.latest_databricks_deliveries(store: Store, prefix: str) -> DatabricksDeliveries`.
  - `databricks.map_databricks_rows(usage: Iterable[Mapping], prices: Sequence[Mapping], workspaces: Sequence[Mapping], *, account_name: str, workspace_names: Mapping[str, str], workspace_projects: Mapping[str, str], promoted_tags: Sequence[str], source: str) -> tuple[list[dict], int]`, which returns the rows and the number of unpriced rows.
  - `databricks.SERVICE_CATEGORIES: dict[str, str]`.
  - `databricks.RESOURCE_ID_FIELDS: tuple[str, ...]`.

- [x] **Step 1: Write the failing tests**

`files/test_databricks.py` uses usage rows shaped like `system.billing.usage`:
- `usage_quantity` is a `Decimal`, `usage_date` a `date`, and `usage_end_time` a UTC datetime;
- `custom_tags` is a dict;
- `usage_metadata` and `product_features` are dicts;
- `record_type` is set.

Its tests:
- **`test_newest_run_per_period_and_table`:**
  - Setup: usage for `2026-11` in runs `20261120T060000Z` and `20261121T060000Z`, plus `list_prices` in two runs.
  - Assert: `usage["2026-11"]` holds the 1121 objects, and `prices` the newest run's objects.
- **`test_cost_is_quantity_times_the_effective_list_price`:** `Decimal("2.5")` DBUs with `effective_list.default = Decimal("0.35")` give `BilledCost == ListCost == EffectiveCost == 0.875`, with `BillingCurrency == "USD"`.
- **`test_price_window_uses_usage_end_time`:**
  - Setup: two prices for the same SKU, `[Nov 1, Nov 15)` at 0.30 and `[Nov 15, open)` at 0.40.
  - Assert: usage ending Nov 15 00:00 costs at 0.40, and usage ending Nov 14 23:00 at 0.30.
- **`test_retractions_and_restatements_are_corrections`:** `record_type = "RETRACTION"` with quantity `-2` gives `ChargeClass == "Correction"` and a negative `BilledCost`. `ORIGINAL` gives `ChargeClass is None`.
- **`test_unpriced_usage_costs_zero_and_is_reported`:** an unknown SKU gives a row with `BilledCost == 0.0` and an unpriced count of `1`.
- **`test_project_falls_back_to_the_workspace`:** empty `custom_tags` with `workspace_projects = {"111": "braveheart"}` gives `x_Project == "braveheart"`. A `custom_tags` `Project` wins over the workspace.
- **`test_workspace_name_comes_from_the_table_then_the_input_then_the_id`.**
- **`test_service_name_category_resource_and_serverless`:**
  - `billing_origin_product = "JOBS"` with `usage_metadata.job_id = "42"` and `cluster_id = "c"`, and `product_features.is_serverless = True`;
  - gives `ServiceName == "Databricks JOBS"`, `ServiceCategory == "Compute"`, `ResourceId == "42"` and `x_Serverless is True`;
  - with `ChargePeriodStart == usage_date 00:00 UTC`, `ChargePeriodEnd == + 1 day` and `BillingPeriodStart == the first of that month`.

- [x] **Step 2: Run them to see them fail**

Run: `scripts/check-module.sh modules/billing-normalizer`
Expected: FAIL with `ModuleNotFoundError: No module named 'normalizer.databricks'`.

- [x] **Step 3: Implement `databricks.py`**

**`SERVICE_CATEGORIES`:**
- `Compute`: JOBS, DLT, ALL_PURPOSE, INTERACTIVE, BASE_ENVIRONMENTS, LAKEFLOW_CONNECT, APPS.
- `Analytics`: SQL, GENIE, LAKEHOUSE_MONITORING, DATA_QUALITY_MONITORING, DATA_CLASSIFICATION, PREDICTIVE_OPTIMIZATION.
- `AI and Machine Learning`: MODEL_SERVING, VECTOR_SEARCH, FOUNDATION_MODEL_TRAINING, AGENT_EVALUATION, AI_GATEWAY, AI_RUNTIME, AI_FUNCTIONS, AGENT_BRICKS, SUPERVISOR_AGENT, FEATURE_STORE.
- `Storage`: DEFAULT_STORAGE.
- `Databases`: DATABASE, LAKEBASE, ONLINE_TABLES, LAKEHOUSE_REAL_TIME.
- `Networking`: NETWORKING, DATA_SHARING, CLEAN_ROOM.
- `Security`: FINE_GRAINED_ACCESS_CONTROL.
- Anything else is `Other`.

**`RESOURCE_ID_FIELDS`:** `job_id`, `dlt_pipeline_id`, `warehouse_id`, `endpoint_id`, `app_id`, `database_instance_id`, `cluster_id`, `instance_pool_id`. The first non-empty one wins.

**Pricing:** as in Global Constraints. `cloud` must match when both rows have it.

**Other columns:**
- `ProviderName = "Databricks"`;
- `BillingAccountId = account_id`, `BillingAccountName = account_name`;
- `SubAccountId = workspace_id`;
- `RegionId = None`, because no system table gives it;
- `ConsumedQuantity = float(usage_quantity)`, `ConsumedUnit = usage_unit`;
- `Tags = custom_tags or {}`.

- [x] **Step 4: Run them to see them pass**

Run: `scripts/check-module.sh modules/billing-normalizer`
Expected: `Ran 20 tests … OK`.

- [x] **Step 5: Commit**

`git commit -m "feat(billing-normalizer): map Databricks system-table deliveries at list price"` (with the trailer).

---

### Task 4: Task-run events

**Files:**
- Create: `$MOD/files/normalizer/runs.py`
- Test: `$MOD/files/test_runs.py`

**Interfaces:**
- Produces:
  - `runs.records_by_month(store: Store, prefixes: Sequence[str]) -> dict[str, list[ObjectInfo]]`. It groups `*.json` keys by the month of their `date=YYYY-MM-DD` segment; keys without one are ignored.
  - `runs.flatten_event(record: Mapping, *, join_tags: Sequence[str], source: str) -> dict`, which raises `ValueError` with the reason.
  - `runs.RUN_EVENTS = ("started", "finished", "swept")`.

**The `runs-1` event format** (documented in the README; plan 08 writes it):

```json
{"schema": "runs-1", "event": "started", "at": "2026-11-24T21:10:03Z",
 "tags": {"RunId": "123456-1", "TaskId": "net-v12"}, "project": "braveheart-trainer",
 "campaign": "net-v12", "kind": "train",
 "instance": {"type": "g6e.xlarge", "accelerators": 1, "market": "spot", "zone": "use1-az4", "id": "i-0abc"},
 "prices": {"hourly_usd": 1.07, "on_demand_hourly_usd": 1.861, "worst_case_usd": 11.17, "ceiling_usd": 50, "max_hours": 6},
 "outcome": null, "exit_code": null, "interrupted_at": null, "reason": null,
 "links": {"run": "https://github.com/acme/x/actions/runs/123456/attempts/1"},
 "attributes": {"profile": "gpu"}}
```

`finished` events set `outcome`, `exit_code` and `interrupted_at`; `swept` events set `reason`. Every field except `schema`, `event`, `at`, `tags` and `project` is optional.

- [x] **Step 1: Write the failing tests**

- **`test_records_group_by_the_month_of_their_date_folder`:** keys under `date=2026-11-30/` and `date=2026-12-01/` land under `"2026-11"` and `"2026-12"`. A key with no `date=` segment is ignored.
- **`test_flattens_a_started_event`:** the example above gives:
  - `run_key == "RunId=123456-1;TaskId=net-v12"`, `instance_type == "g6e.xlarge"`, `accelerators == 1`, `hourly_usd == 1.07`;
  - `at == datetime(2026, 11, 24, 21, 10, 3, tzinfo=UTC)`;
  - `links == {"run": "…"}`, `x_Source == "src"`;
  - the keys equal `runs_schema().names`.
- **`test_run_key_follows_the_join_tag_order`:** `join_tags=["TaskId", "RunId"]` gives `"TaskId=net-v12;RunId=123456-1"`.
- **`test_invalid_records_are_skipped_and_reported`:** each of these raises `ValueError`:
  - `schema = "runs-2"`;
  - `event = "paused"`;
  - a missing `RunId` tag;
  - a blank `project`;
  - `at = "yesterday"`.

- [x] **Step 2: Run them to see them fail**

Expected: `ModuleNotFoundError: No module named 'normalizer.runs'`.

- [x] **Step 3: Implement `runs.py`**

- [x] **Step 4: Run them to see them pass**

Expected: `Ran 24 tests … OK`.

- [x] **Step 5: Commit**

`git commit -m "feat(billing-normalizer): flatten task-run event records"` (with the trailer).

---

### Task 5: The orchestrator, run records and the handler

**Files:**
- Create: `$MOD/files/normalizer/{config.py,run.py,handler.py}`
- Test: `$MOD/files/test_run.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - **Config dataclasses** (frozen):
    - `config.AwsConfig(delivery_prefix: str, exclude_publishers: tuple[str, ...])`;
    - `config.DatabricksConfig(prefix: str, account_name: str, workspace_names: dict, workspace_projects: dict)`;
    - `config.RunsConfig(prefixes: tuple[str, ...], join_tags: tuple[str, ...])`;
    - `config.Config(bucket, normalized_prefix, promoted_tags, aws, databricks, runs)`.
  - `config.load_config(raw: str) -> Config`, parsing the JSON in the `NORMALIZER_CONFIG` environment variable that Task 6 renders.
  - `run.run(store: Store, config: Config, now: datetime) -> dict`, which returns the run record. It raises `run.NormalizeError` after writing the record if anything failed.
  - `handler.handler(event, context) -> dict`, returning `{"status": ..., "rebuilt": N}`.
- **Run record** (`schema: "normalizer-run-1"`):
  - `started_at` and `ended_at`, as ISO UTC;
  - `status`, `ok` or `error`;
  - `outputs`, a list of `{key, provider, period, rebuilt, rows, billed_cost}`;
  - `warnings` and `errors`, lists of strings.

- [x] **Step 1: Write the failing tests**

Each test uses `FakeStore` with one AWS period, one Databricks period and one runs month. Its tests:
- **`test_first_run_builds_every_output_and_writes_a_run_record`:**
  - `FakeStore.puts` contains:
    - `normalized/schema=focus-1.2/provider=aws/billing_period=2026-11/data.parquet`;
    - `…/provider=databricks/billing_period=2026-11/data.parquet`;
    - `normalized/schema=runs-1/event_month=2026-11/data.parquet`;
    - `normalized/_runs/20261121T120000Z.json`;
    - `normalized/_runs/latest.json`.
  - The record has `status == "ok"` and three outputs with `rebuilt=True`.
  - Each Parquet object's metadata has `source-signature`.
- **`test_a_second_run_without_new_deliveries_rewrites_nothing`:** the second `run` puts only the two run-record keys, and every output has `rebuilt=False`.
- **`test_a_new_aws_execution_rebuilds_only_that_period`.**
- **`test_a_mapper_version_change_rebuilds_everything`:** patch `normalizer.schema.MAPPER_VERSION` to `"2"`, and all three outputs rebuild.
- **`test_empty_sources_write_only_a_run_record`:** no deliveries give only the run-record puts and `status == "ok"`.
- **`test_one_provider_failing_still_builds_the_others_and_raises`:**
  - Setup: the Databricks usage object holds the bytes `b"not parquet"`.
  - Assert: `run` raises `NormalizeError`; the AWS and runs outputs are written; `latest.json` has `status == "error"` and one error naming `databricks`.
- **`test_load_config_reads_the_rendered_json`:** the JSON Task 6 renders for all three providers gives the right dataclasses. `null` providers give `None`.

- [x] **Step 2: Run them to see them fail**

Expected: `ModuleNotFoundError: No module named 'normalizer.run'`.

- [x] **Step 3: Implement `config.py`, `run.py` and `handler.py`**

**`run`, provider by provider, each in its own `try`:**
- List the deliveries.
- Compute each output's `source-signature`, the sha256 of `MAPPER_VERSION`, `json.dumps(provider config, sort_keys=True)`, `promoted_tags` and the sorted source ETags.
- Compare it with `store.metadata(key)`.
- If it changed, rebuild the output: read, map, `write_rows`, then `put` with `content_type="application/vnd.apache.parquet"`.

**Warnings:**
- Unpriced Databricks rows: `"databricks 2026-11: 3 rows have no list price"`.
- Skipped run records: `"runs: <key>: <reason>"`.

**The run record:** always put both record keys (`application/json`), then raise if there are errors.

**`handler`:** builds `S3Store(config.bucket, boto3.client("s3"))`. Import boto3 inside the handler, so tests never need it.

- [x] **Step 4: Run them to see them pass**

Expected: `Ran 31 tests … OK`.

- [x] **Step 5: Commit**

`git commit -m "feat(billing-normalizer): rebuild changed periods and record every run"` (with the trailer).

---

### Task 6: The Terraform module

**Files:**
- Modify: `$MOD/{versions.tf,variables.tf,main.tf,outputs.tf,README.md}`
- Create: `$MOD/iam.tf`, `$MOD/schedule.tf`, `$MOD/examples/basic/{main.tf,versions.tf}`
- Modify: `$REPO/README.md` and `$REPO/main.tf`: add the submodule, `schema=runs-1` and `_runs/` to the layout.
- Test: `$MOD/tests/billing_normalizer.tftest.hcl`

**Interfaces:**
- Consumes: `billing-bucket`'s `name`, `aws_export_prefix` and `normalized_prefix`, and `aws-billing-export`'s `delivery_prefix`, all passed by the caller.
- Produces (used by plans 05 and 08):
  - **Inputs:**
    - `name` (string, required, `^[A-Za-z0-9_-]{1,64}$`);
    - `bucket_name` (string, required);
    - `normalized_prefix` (default `"normalized"`);
    - `promoted_tags` (default `["Project", "Component", "Environment"]`);
    - `aws` = `object({ delivery_prefix = string, exclude_publishers = optional(list(string), []) })`, default null;
    - `databricks` = `object({ prefix = optional(string, "raw/provider=databricks/source=system-tables"), account_name = optional(string, "Databricks"), workspace_names = optional(map(string), {}), workspace_projects = optional(map(string), {}) })`, default null;
    - `runs` = `object({ prefixes = list(string), join_tags = list(string) })`, default null;
    - `schedule_expression` (default `"rate(1 hour)"`);
    - `pandas_layer_arn` (default null, meaning the verified layer in the current region);
    - `log_retention_days` (default `30`, one of CloudWatch's allowed values).
  - **Outputs:**
    - `function_name`, `function_arn`, `role_name`, `role_arn`, `log_group_name`, `schedule_name`;
    - `outputs = { focus = "<np>/schema=focus-1.2", runs = "<np>/schema=runs-1", run_records = "<np>/_runs" }`.

- [x] **Step 1: Write the failing tests**

`tests/billing_normalizer.tftest.hcl` mocks `aws` (with `aws_region` = `us-east-1` and `aws_caller_identity` = `222222222222`) and `archive`. It sets these variables:
- `name = "acme-billing-normalizer"`, `bucket_name = "acme-billing"`;
- `aws = { delivery_prefix = "raw/provider=aws/source=data-exports/acme-focus-daily" }`;
- `databricks = {}`;
- `runs = { prefixes = ["raw/provider=acme/source=task-runs"], join_tags = ["RunId", "TaskId"] }`.

Its runs:
- **`function_is_python_3_13_on_arm64_with_the_pandas_layer`:**
  - `runtime == "python3.13"`, `architectures == ["arm64"]` and `handler == "normalizer.handler.handler"`;
  - `timeout == 900` and `memory_size == 1024`;
  - `layers == ["arn:aws:lambda:us-east-1:336392948345:layer:AWSSDKPandas-Python313-Arm64:17"]`;
  - tags `{ Name, Component = "billing" }`.
- **`config_renders_every_enabled_provider`:** `jsondecode(environment[0].variables.NORMALIZER_CONFIG)` equals the full expected object. Databricks defaults are applied, and `exclude_publishers` is `[]`.
- **`role_reads_the_sources_and_writes_only_normalized`:** the policy's Statement equals, in order:
  - `ListTheSources`: `s3:ListBucket` on the bucket, with `StringLike s3:prefix` = each source prefix and `normalized` (as `"<p>/*"`);
  - `ReadTheSources`: `s3:GetObject` on each source `/*` and `normalized/*`;
  - `WriteTheNormalizedLayer`: `s3:PutObject` on `arn:aws:s3:::acme-billing/normalized/*` only;
  - `WriteLogs`: `logs:CreateLogStream` and `logs:PutLogEvents` on the log group ARN with `:*`.
- **`disabled_providers_leave_no_trace`:** with only `aws` set, `databricks` and `runs` are `null` in the config, and the policy names only the AWS prefix and `normalized`.
- **`runs_hourly_through_the_scheduler`:**
  - `aws_scheduler_schedule.this.schedule_expression == "rate(1 hour)"`;
  - its target ARN is the function's;
  - the scheduler role may only `lambda:InvokeFunction` that function.
- **`logs_are_kept_30_days`:** `aws_cloudwatch_log_group.this.name == "/aws/lambda/acme-billing-normalizer"` and `retention_in_days == 30`.
- **`a_custom_layer_replaces_the_default`.**
- **`needs_at_least_one_source`:** all three providers null gives `expect_failures = [aws_lambda_function.this]` (a lifecycle precondition).
- **`rejects_runs_without_join_tags`:** `expect_failures = [var.runs]`.
- **`rejects_prefixes_with_stray_slashes`:** `normalized_prefix = "normalized/"` gives `expect_failures = [var.normalized_prefix]`.

- [x] **Step 2: Run them to see them fail**

Run: `cd $MOD && terraform init -backend=false -input=false >/dev/null && terraform test`
Expected: FAIL, because the variables and resources are undeclared.

- [x] **Step 3: Implement the module**

- **`versions.tf`:** `aws ~> 6.0` and `archive ~> 2.7`.
- **`main.tf`:**
  - `data "archive_file" "code"` zips `files/`, excluding `test_*.py`, `fakes.py`, `requirements-test.txt` and `**/__pycache__/**`, into `${path.module}/.build/normalizer.zip`. Add `.build/` to `.gitignore`.
  - `aws_cloudwatch_log_group.this`.
  - `aws_lambda_function.this`:
    - `source_code_hash = data.archive_file.code.output_base64sha256`;
    - `environment.variables.NORMALIZER_CONFIG = jsonencode(local.config)`;
    - `logging_config { log_format = "Text", log_group = aws_cloudwatch_log_group.this.name }`;
    - a precondition that at least one source is set.
- **`iam.tf`:** the Lambda role, with a `lambda.amazonaws.com` trust and `aws:SourceAccount`, and its inline policy as tested.
- **`schedule.tf`:** the scheduler role, with a `scheduler.amazonaws.com` trust and `aws:SourceAccount`, and `aws_scheduler_schedule.this` with `flexible_time_window { mode = "OFF" }`, as in `container-instance`.
- **README:**
  - what it does, and when it rebuilds (signatures, `MAPPER_VERSION`);
  - the output layout;
  - the three input contracts (AWS manifests, the Databricks tables, the `runs-1` event JSON);
  - the Databricks pricing rule, and that `RegionId` is null;
  - the tag-key tolerance;
  - the run record;
  - a usage snippet with `# x-release-please-version`.

- [x] **Step 4: Run them to see them pass**

Run: `terraform test`
Expected: `Success! 10 passed, 0 failed.`

- [x] **Step 5: The example, the docs and the module check**

- **`examples/basic/main.tf`:** all three sources, for `acme-billing`.
- Regenerate the README docs, and update the root README and the `main.tf` comment.

Run: `cd $REPO && scripts/check.sh`
Expected: `All checks passed.`, with four modules.

- [x] **Step 6: Commit**

`git commit -m "feat(billing-normalizer): run the normalizer hourly as a Lambda"` (with the trailer).

---

### Task 7: Publish 0.2.0

Every step here needs the owner's explicit permission for this plan, asked for at this step; plan 01's permission doesn't carry over.

- [x] **Step 1 (owner permission): Push and open the PR**

Run: `git push -u origin feat/billing-normalizer`, then `gh pr create --template feat.md --title "feat: add the billing normalizer"` with every section filled.
Expected: CI passes, including the new uv step, in the `terraform (billing-normalizer)` leg.

- [x] **Step 2 (owner permission): Merge, then release**

Squash-merge the PR, then merge the `chore(main): release 0.2.0` PR.
Expected: the tag `v0.2.0` exists.

- [x] **Step 3: Record**

On the Jaws docs branch:
- tick this plan;
- set the roadmap row for plan 02 to `released v0.2.0`;
- update spec 6.12: the normalizer writes one row per event, and the node (plan 05) merges events into runs.

Commit: `docs(monitoring): record the billing normalizer release`.
