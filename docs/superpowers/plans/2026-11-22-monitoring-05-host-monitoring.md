# Host Monitoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `monitoring-node` its host monitoring, and release it as 0.4.0 of `terraform-aws-jaws-monitoring`:
- the **Monitoring node · Host health** dashboard;
- the host alert rules, in warning and critical pairs;
- Slack contact points, one message template and a notification policy per `area`;
- the rules validator;
- the `extra_dashboards` and `extra_alert_rules` hooks.

The Pipeline row, the cost dashboards and the cost and pipeline rules come in plan 06. Mute timings and the watchdog come in plan 07.

**Architecture:**
- **A new pure module, `modules/monitoring-node/grafana/`,** renders every file under `grafana/` in the bundle: data sources, the dashboard provider, dashboards, alert rules, templates, contact points and policies. It has no providers, so a plain `terraform apply` in a scratch directory renders it with no AWS at all. That is what lets a local Grafana load the real files in a test.
- **One table of PromQL queries** feeds both the panels and the rules. **One `thresholds` input** feeds the tiles' colours, the panels' dashed lines and the rules, so they can't drift apart.
- **The validator** is a port of prog-strength's `validate_rules.py` into Terraform: a precondition on the module's `files` output. It checks every rule the module renders and every rule a caller adds, so a bad rule fails `terraform plan` in CI and never reaches Grafana.
- **A local smoke test** starts the pinned Grafana image on the rendered files, twice, and compares what Grafana's API reports with what the module rendered. It also checks every PromQL query with `promtool`.

**Tech Stack:**
- Terraform `>= 1.11` and `terraform test` (mock providers for the node, none for the pure module);
- Grafana 13.3.1 file provisioning (unified alerting, no Alertmanager);
- bash, and Python 3 stdlib for the smoke test helper;
- Docker (local and CI) for the smoke test.

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md):
- 6.5, for the containers and data sources;
- 6.7, the host dashboard;
- 6.8, alerts and Slack, host rows only;
- 7, the optional-feature rule and the module inputs;
- 12.8, pressure metrics.

Series: [00-roadmap](2026-11-21-monitoring-00-roadmap.md). Style reference: [prog-strength-infra `monitoring/`](https://github.com/Prog-Strength/prog-strength-infra/tree/main/monitoring) (`host.json`, `templates.yml`, `contact-points.yml`, `policies.yml`, `validate_rules.py`).

## Global Constraints

**Where things live**
- **Repo:** `$REPO` = `/Users/jimmywallace/Projects/Jaws-Platform/terraform-aws-jaws-monitoring`, on branch `feat/host-monitoring` cut from `origin/main` (0.3.0).
- **Modules:** `$MOD` = `$REPO/modules/monitoring-node`, and `$GRAF` = `$MOD/grafana` (internal; not a registry submodule).

**Conventions**
- The plan 04 conventions hold: no provider configuration, no organisation names (`acme`, `example.com`), terraform-docs READMEs with absolute links, one-line commits with the `Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>` trailer, and no cloud calls.
- **The house style** (prog-strength):
  - stat tiles turn green, yellow or red at the rule thresholds;
  - time series draw warning and critical as `vector(N)` targets with dashed yellow and red overrides, legends `warning (<N><unit>)` and `critical (<N><unit>)`;
  - every row opens with a short text panel;
  - every panel has a description, which states the thresholds where there are any;
  - 30s refresh, last 6 hours;
  - dashboards are read-only (`editable: false`; provider `allowUiUpdates: false`).
- **No Grafana macros in queries.** Panel queries use fixed windows (`[5m]`), not `$__rate_interval`, so every query is plain PromQL that `promtool` can parse.

**Files `$GRAF` renders** (keys of its `files` output, relative to the bundle root)

| Path | Content |
|---|---|
| `grafana/provisioning/datasources/datasources.yaml` | `prometheus` (default) and `cloudwatch` (as in 0.3.0), plus `prune: true` |
| `grafana/provisioning/dashboards/dashboards.yaml` | one file provider at `/var/lib/grafana/dashboards`, `foldersFromFilesStructure: true`, `allowUiUpdates: false`, `disableDeletion: false` (Task 2) |
| `grafana/dashboards/Monitoring/host.json` | the host dashboard, uid `monitoring-host` |
| `grafana/dashboards/<Folder>/<name>.json` | each `extra_dashboards` entry |
| `grafana/provisioning/alerting/rules-host.json` | group `host` (folder `Monitoring`, interval `1m`) plus `deleteRules` |
| `grafana/provisioning/alerting/rules-extra-<name>.json` | each `extra_alert_rules` entry, `jsonencode(yamldecode(...))` |
| `grafana/provisioning/alerting/templates.json` | with `slack` only: template group `monitoring-slack` |
| `grafana/provisioning/alerting/contact-points.json` | with `slack` only |
| `grafana/provisioning/alerting/policies.json` | with `slack`: the policy tree; without: `{"apiVersion": 1, "resetPolicies": [1]}` |

- **Alerting files are JSON.** Grafana reads YAML or JSON there. JSON lets the smoke test's stdlib Python read them.
- **The folder.** The rule folder and the host dashboard's directory are both titled `Monitoring`, so Grafana has one folder for both. The smoke test checks this.

**Rules**
- **uid:** `host-<key>-<severity>`, at most 40 characters of `[A-Za-z0-9_-]`.
- **title:** `<Title> — <severity>`.
- **labels:** `area = "host"`, `severity`.
- **annotations:** `summary`, `__dashboardUid__ = "monitoring-host"`, `__panelId__ = "<id>"` (a string).
- **Prometheus rules:** `data` is A, an instant query (`datasourceUid: prometheus`, `relativeTimeRange {from: 600, to: 0}`, `model {refId, expr, instant: true, intervalMs: 1000, maxDataPoints: 43200}`), then C, a `__expr__` `threshold` on A. `condition: C`.
- **CloudWatch rules:**
  - A is the CloudWatch query below, with `relativeTimeRange {from: 1800, to: 0}`;
  - B is a `__expr__` `reduce` (`last`, `settings.mode = dropNN`);
  - C is the threshold on B.
- **States:** `noDataState: OK` (CloudWatch: `NoData`, so a wrong instance id shows up); `execErrState: Alerting` (the prog-strength convention, and the spec's rule for AWS data).
- **`for`:** in whole minutes, never below `2m`, so a Prometheus or Grafana restart during a config change doesn't post. The values are in the rule table.
- **`deleteRules`:** the file also deletes every uid in the host catalogue that isn't rendered: a feature switched off, or a threshold with no warning. Grafana's docs promise deletion only through `deleteRules`.
- **Counts that fire on a whole number** (`≥ n`) use threshold parameter `n - 0.5`. `increase()` extrapolates, and this is the prog-strength gotcha. Their panel lines are drawn at `n`.

**The CloudWatch query** (credits; panel and rule)

```json
{"refId": "A", "datasource": {"type": "cloudwatch", "uid": "cloudwatch"}, "queryMode": "Metrics",
 "namespace": "AWS/EC2", "metricName": "CPUCreditBalance", "dimensions": {"InstanceId": ["<instance_id>"]},
 "statistic": "Minimum", "period": "300", "region": "default", "matchExact": true,
 "metricQueryType": 0, "metricEditorMode": 0, "id": "", "expression": "", "label": ""}
```

- **Burstable types:** `t3`, `t3a`, `t4g` and `t9g`. Their maximum balance by size: `nano 144, micro 288, small 576, medium 576, large 864, xlarge 2304, 2xlarge 4608`.
  - Credit thresholds are absolute: percent ÷ 100 × maximum. For `t9g.medium` that is warning `144` and critical `28.8`, so no rule needs a math step.
  - T9g's maximums are assumed equal to T4g's until plan 09 verifies them (spec 12.5).
  - Any other type gets no credit tile, panels or rules.

**Queries** (`$GRAF/queries.tf`, `local.q`; `V` = `mountpoint=~"/|/data"`)

| Key | PromQL |
|---|---|
| `cpu` | `100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[10m])))` |
| `memory` | `avg_over_time((100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))[5m:1m])` |
| `swap` | `avg_over_time((100 * (1 - node_memory_SwapFree_bytes / clamp_min(node_memory_SwapTotal_bytes, 1)))[15m:1m])` |
| `oom_kills` | `increase(node_vmstat_oom_kill[10m])` |
| `disk` | `100 * (1 - node_filesystem_avail_bytes{V} / node_filesystem_size_bytes{V})` |
| `disk_full_days` | `node_filesystem_avail_bytes{V} / -(deriv(node_filesystem_avail_bytes{V}[24h]) < 0) / 86400` |
| `inodes` | `100 * (1 - node_filesystem_files_free{V} / node_filesystem_files{V})` |
| `prometheus_size` | `100 * (prometheus_tsdb_storage_blocks_bytes + prometheus_tsdb_wal_storage_size_bytes + prometheus_tsdb_head_chunks_storage_size_bytes) / prometheus_tsdb_retention_limit_bytes` |
| `up` | `up` |
| `restarts` | `changes(container_start_time_seconds{name=~".+"}[15m])` |
| `tls_days` | `(probe_ssl_earliest_cert_expiry - time()) / 86400` |
| `eval_failures` | `sum(increase(grafana_alerting_rule_evaluation_failures_total[10m]))` |
| `os_update_days` | `(time() - monitoring_os_release_update_since_seconds) / 86400 and monitoring_os_release_update_available == 1` |

Panel-only queries are written in the panel table.

**Thresholds** (the `thresholds` input, defaults from spec 6.8)

| Attribute | Warning | Critical | Worse when |
|---|---|---|---|
| `cpu_percent` | 60 | 85 | higher |
| `cpu_credits_percent` | 25 | 5 | lower |
| `memory_percent` | 70 | 90 | higher |
| `swap_percent` | 25 | 75 | higher |
| `disk_percent` | 70 | 90 | higher |
| `disk_full_days` | 7 | 2 | lower |
| `inodes_percent` | 70 | 90 | higher |
| `prometheus_size_percent` | 85 | — | higher |
| `container_restarts` | 1 | 3 | higher (whole numbers ≥ 1) |
| `tls_days` | 14 | 3 | lower |
| `os_release_update_days` | 7 | — | higher |

- OOM kills, a target down, and Grafana rule-evaluation failures fire on any occurrence. They are not inputs.
- Every attribute is `optional(object(...), <default>)` in an object variable with `default = {}`, so plan 06 can add its own attributes without breaking callers.

**Slack**
- **Input:** `slack = object({ channels = map(string), routes = map(string) })`, default `null`.
- **Webhook variables:** channel `c` maps to `SLACK_WEBHOOK_<upper(c), - → _>`.
- **Contact points:** contact point `slack-<c>`, receiver uid `slack-<c>`, type `slack`.
  - `settings.url` is `$SLACK_WEBHOOK_<C>`, which Grafana expands from its environment.
  - `title` is `{{ template "monitoring.title" . }}` and `text` is `{{ template "monitoring.text" . }}`.
  - `disableResolveMessage: false`.
- **Policy tree:**
  - the root receiver is `slack-<routes.host>`;
  - `group_by [grafana_folder, alertname]`, `group_wait 30s`, `group_interval 5m`, `repeat_interval 4h`;
  - one child route per `routes` entry, `{receiver: slack-<channel>, object_matchers: [[area, =, <area>]]}`.
- **Template group `monitoring-slack`:** ported from `ps-slack`, with the defines renamed to `monitoring.title` and `monitoring.text`.
  - Its label list leaves out `alertname`, `grafana_folder` and `severity`.
  - The link is `.PanelURL` when set, else `.DashboardURL`.
  - No `$` anywhere.
- **On the node:** each webhook parameter becomes a bundle secret named after its variable, and Grafana's environment gets `SLACK_WEBHOOK_<C> = "${SLACK_WEBHOOK_<C>:?}"`. The role may read each parameter.

## Review Focus

1. **A Prometheus or Grafana restart during a config change.** Every bundle change that touches `grafana/` or `prometheus/` recreates that container. The rules use `execErrState: Alerting`, so a rule that fires at once would post a burst to Slack on every deploy. Every rule must wait at least 2 minutes (Task 4, `every_rule_waits_at_least_two_minutes`).
2. **A rule that stops being rendered:** a domain removed, a non-burstable instance type, a caller's extra rule dropped. It must leave Grafana, not keep firing with its old numbers. The covering checks:
   - Task 4, `switched_off_rules_are_deleted_and_only_those`;
   - Task 2, the smoke test's phase 2, which checks that Grafana's rule set equals what was rendered after the change;
   - for extra rules, the README tells callers to list removed uids under `deleteRules`, and the smoke test exercises that.
3. **A malformed extra rule.** One bad rule makes Grafana reject the whole provisioning run at boot: no dashboards, no alerting. The validator must fail the plan instead (Task 1, the `rejects_*` runs). The smoke test checks that Grafana logs no provisioning error for anything the validator lets through (Task 2).
4. **A threshold override.** Jaws may override any threshold. The tile colour, the dashed line and the rule must all move together (Task 4, `every_rule_mirrors_its_panel`, run with overrides).
5. **Slack never configured, or removed later.** A dashboards-only node must provision cleanly, and removing Slack must reset Grafana's stored policy tree instead of leaving it pointing at the old webhooks:
   - Task 5, `without_slack_the_policy_tree_is_reset`;
   - the smoke test's phase 2.

---

### Task 1: The Grafana config module and the rules validator

**Files:**
- Create: `$GRAF/{versions.tf,variables.tf,main.tf,validate.tf,outputs.tf}`, `$MOD/grafana.tf`
- Modify: `$MOD/bundle.tf`, `$MOD/iam.tf`, `$MOD/variables.tf`, `$MOD/README.md` (terraform-docs)
- Delete: `$MOD/extensions.tf` (its three locals move to `$MOD/grafana.tf`)
- Test: `$MOD/tests/grafana.tftest.hcl` (new), `$MOD/tests/monitoring_node.tftest.hcl`

**Interfaces:**
- **`$GRAF` inputs:**
  - `region`, `instance_id`, `instance_type` (strings);
  - `domain` (string, nullable);
  - `extra_dashboards` (`map(string)`: key `<Folder>/<name>.json`, value dashboard JSON);
  - `extra_alert_rules` (`map(string)`: key `<name>` matching `^[a-z0-9-]+$`, value a Grafana alerting provisioning YAML document).
  
  Tasks 3 and 5 add `thresholds` and `slack`.
- **`$GRAF` outputs:**
  - `files` (`map(string)`), with a precondition that `local.problems` is empty, `error_message = "Grafana provisioning problems: ${join("; ", local.problems)}"`;
  - `webhook_env` (`map(string)`, channel to variable name), `{}` until Task 5.
- **`$MOD`:**
  - `module "grafana" { source = "./grafana" … instance_id = aws_instance.this.id }`;
  - `local.bundle_files` merges `module.grafana.files`;
  - the 0.3.0 `datasources`, `dashboard_providers` and `grafana/dashboards/.keep` locals are removed;
  - new inputs `extra_dashboards` and `extra_alert_rules`, both default `{}`.
- **`local.problems`** (`$GRAF/validate.tf`) is a `list(string)` of `<file> [<group>/<uid>]: <problem>`. It is built over every rules file the module renders and every `extra_alert_rules` entry. Each line below is checked:
  1. the YAML decodes (`try(yamldecode(…))`), else `not valid YAML`;
  2. `uid`, `title` and `condition` are present and non-empty, and `uid` is at most 40 characters of `[A-Za-z0-9_-]`;
  3. rule uids are unique across every file;
  4. `__dashboardUid__` and `__panelId__` are both present or both absent;
  5. `condition` names a `refId` in the rule's `data`;
  6. no lone `$` (after removing `$$`) in the fields Grafana expands. That is everything in a rule except `annotations`, `relativeTimeRange` and `data[].model`, which Grafana 13.3 doesn't expand;
  7. a linked `__dashboardUid__` is a rendered dashboard (module or extra), and `__panelId__` is one of its panel ids;
  8. `labels.area` is one of `host`, `pipeline`, `cost`, and `labels.severity` is `warning` or `critical`, so routing works;
  9. each extra dashboard decodes as JSON with a non-empty `uid` and `title`, dashboard uids are unique, and no extra path is one the module renders itself (`Monitoring/host.json`).
  
  A file may also hold `deleteRules`; those entries are not rules and aren't checked.
- **Validated in `$MOD/variables.tf`:** `extra_dashboards` keys match `^[A-Za-z0-9 _-]+/[a-z0-9-]+\.json$`, and `extra_alert_rules` keys match `^[a-z0-9-]+$`.
- **CI:** check how the `discover` job in `.github/workflows/ci.yml` lists modules. If it picks up `grafana/`, that directory must pass `scripts/check-module.sh` on its own (it has no README, so terraform-docs is skipped).

- [ ] **Step 1: Write the failing tests**

`tests/grafana.tftest.hcl` has no providers. Every run sets `module { source = "./grafana" }` and `region = "us-east-1"`, `instance_id = "i-0123456789abcdef0"`, `instance_type = "t9g.medium"`, `domain = null`. The fixture extra dashboard is `{"uid": "extra-smoke", "title": "Extra", "panels": [{"id": 1, "type": "timeseries", "title": "Up", "targets": [{"expr": "up", "refId": "A", "datasource": {"type": "prometheus", "uid": "prometheus"}}]}]}`. The fixture extra rule is one group (`orgId 1`, `name extra`, `folder Extra`, `interval 1m`) with one Prometheus rule, uid `extra-up-critical`, linked to `extra-smoke` panel 1, labels `area: host`, `severity: critical`.

Runs:
- **`it_provisions_both_data_sources_and_prunes_removed_ones`:** the decoded `datasources.yaml` has `prune == true`, uid `prometheus` with `isDefault`, and uid `cloudwatch` with `jsonData.defaultRegion == "us-east-1"`.
- **`extra_dashboards_and_rules_are_provisioned`:**
  - `files["grafana/dashboards/Extra/extra.json"]` equals the fixture;
  - `jsondecode(files["grafana/provisioning/alerting/rules-extra-smoke.json"]) == yamldecode(<fixture>)`.
- **`rejects_*`,** each with `expect_failures = [output.files]` and one fixture defect:
  - `rejects_a_rule_linked_to_a_dashboard_but_not_a_panel`;
  - `rejects_a_duplicate_rule_uid` (two extra files share a uid);
  - `rejects_a_condition_without_its_query` (`condition: D`);
  - `rejects_a_dollar_grafana_would_expand` (title `Cost over $5`);
  - `rejects_a_link_to_a_missing_panel` (`__panelId__: "99"`);
  - `rejects_a_rule_without_its_area_and_severity`;
  - `rejects_extra_rules_that_are_not_yaml` (`"groups: [unclosed"`);
  - `rejects_a_dashboard_without_a_uid`.
- **`accepts_a_dollar_where_grafana_does_not_expand`:** a math step `$A * 2` in `data[].model.expression` and `$` in `annotations.summary`. The plan succeeds.

In `tests/monitoring_node.tftest.hcl`:
- **`the_bundle_carries_grafanas_files`:** every key of `module.grafana.files` is in `local.bundle.files` with the same content, and `grafana/dashboards/.keep` is gone.
- Point `grafana_uses_postgres_and_provisioned_sources` at the module's files; its assertions are unchanged.

- [ ] **Step 2: Run them to see them fail**

Run: `cd $MOD && terraform init -backend=false >/dev/null && terraform test -filter=tests/grafana.tftest.hcl`
Expected: FAIL with `Unreadable module directory` for `./grafana`.

- [ ] **Step 3: Implement `$GRAF` and the wiring**

Move the data sources and the dashboard provider into `$GRAF/main.tf` unchanged, adding only `prune = true`. `disableDeletion` stays `true` until Task 2, which shows why it can't. Build `local.problems` in `validate.tf` from flattened `(file, group, rule)` tuples, and each check as a for-expression that yields problem strings.

- [ ] **Step 4: Run every test**

Run: `cd $MOD && terraform fmt -recursive && terraform test`
Expected: PASS, the 20 earlier runs and the new ones.

- [ ] **Step 5: Commit**

```bash
git add -A modules/monitoring-node && git commit -m "feat(monitoring-node): render grafana provisioning in its own module and validate every rule" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: A real Grafana loads what the module renders

**Files:**
- Create: `$MOD/tests/test-grafana-provisioning.sh`, `$MOD/tests/grafana_smoke.py`
- Modify: `$GRAF/main.tf` (`disableDeletion`)

**Interfaces:**
- `scripts/check-module.sh modules/monitoring-node` runs `tests/test-*.sh`, so this runs locally and in CI.
- **Needs:** `docker`, `terraform`, `python3`. A missing `docker` is a failure with a clear message, never a skip.
- **Images:** the Grafana and Prometheus references are read from `local.default_images` in `$MOD/bundle.tf`, so the test runs exactly the pinned digests.

**What it does:**
1. **Phase 1.** Write a scratch root (`mktemp -d`) whose `main.tf` calls `$GRAF` by absolute path and outputs `files`. Run `terraform init` and `apply -auto-approve`, then `terraform output -json files`, and write each file under `<scratch>/release/`.
   - The variables: `instance_type = "t9g.medium"`, `domain = null`, the Task 1 extra dashboard and rule, and, from Task 5 on, `slack` with channels `platform` and `costs` and routes for `host`, `pipeline` and `cost`.
2. **`promtool`.** Collect every PromQL query: each rule `data[].model.expr` whose `datasourceUid` is `prometheus`, and each dashboard target whose datasource uid is `prometheus`. Write them as recording rules `q_<n>`, and run `promtool check rules` in the Prometheus image (`--entrypoint promtool`).
3. **Start Grafana:**
   - `docker run -d` the Grafana image, with the provisioning and dashboards directories mounted read-only at their 0.3.0 paths and a named volume at `/var/lib/grafana`;
   - environment `GF_SECURITY_ADMIN_USER=smoke` and a random `GF_SECURITY_ADMIN_PASSWORD`, plus each `SLACK_WEBHOOK_*` set to `https://hooks.slack.invalid/smoke`;
   - published on `127.0.0.1` on a random port.
   
   Wait up to 120 s for `/api/health`.
4. **Compare** (`grafana_smoke.py`, stdlib, reading the rendered files and querying the API with basic auth):
   - the alert-rule uids (`/api/v1/provisioning/alert-rules`) equal the uids in the rendered `groups`;
   - the dashboard uids (`/api/search?type=dash-db`) equal the rendered dashboards' uids;
   - `/api/folders` has exactly one folder titled `Monitoring`;
   - the data-source uids are `prometheus` and `cloudwatch`;
   - the contact points (`/api/v1/provisioning/contact-points`) include every rendered `slack-*`;
   - the root policy's receiver (`/api/v1/provisioning/policies`) is the rendered root receiver, or not a `slack-*` one after `resetPolicies`;
   - the template `monitoring-slack` exists when it was rendered;
   - `docker logs` has no `level=error` line mentioning `provision`.
5. **Phase 2.** Render again with `instance_type = "m7g.medium"`, `domain = "grafana.example.com"`, no extra dashboard, `slack = null`, and an extra rules file that holds only `deleteRules: [{orgId: 1, uid: extra-up-critical}]`. Replace the release, start a new Grafana container on the same volume, and compare again. Removed dashboards, rules and policies must be gone.
6. A `trap` removes the containers, the volume and the scratch directory, whatever happened.

- [ ] **Step 1: Write the test and run it to see it fail**

Run: `cd $MOD && bash tests/test-grafana-provisioning.sh`
Expected: FAIL in phase 2: dashboard `extra-smoke` is still listed, because `disableDeletion: true` keeps a dashboard whose file is gone.

If phase 2 passes with `disableDeletion: true`, the test isn't exercising deletion the way the docs describe. Ledger a ruling, then make the change in Step 2 on the documented semantics anyway.

- [ ] **Step 2: Set `disableDeletion = false` in `$GRAF/main.tf`, and assert it in `tests/grafana.tftest.hcl`, run `dashboards_follow_their_files`**

The run asserts `providers[0].disableDeletion == false`, `allowUiUpdates == false` and `foldersFromFilesStructure == true`.

- [ ] **Step 3: Run the test and the suite**

Run: `cd $MOD && bash tests/test-grafana-provisioning.sh && terraform test`
Expected: `grafana smoke: OK` for both phases; terraform PASS.

- [ ] **Step 4: Commit**

```bash
git add -A modules/monitoring-node && git commit -m "test(monitoring-node): load the rendered provisioning into a real grafana" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The host dashboard

**Files:**
- Create: `$GRAF/queries.tf`, `$GRAF/dashboard-host.tf`
- Modify: `$GRAF/variables.tf`, `$GRAF/main.tf`, `$MOD/variables.tf`, `$MOD/grafana.tf`, `$MOD/README.md`
- Test: `$MOD/tests/grafana.tftest.hcl`, `$MOD/tests/monitoring_node.tftest.hcl`

**Interfaces:**
- **`$MOD` input `thresholds`,** as in Global Constraints. Its validations:
  - each "higher" pair has warning < critical, and each "lower" pair has warning > critical;
  - percentages are in (0, 100];
  - `container_restarts` values are whole numbers of at least 1.
  
  `$GRAF` takes the resolved object (same attribute names, all required).
- **Locals:**
  - `local.q`, the query table;
  - `local.credits_max` (number or null), from `instance_type`;
  - `local.host_dashboard`, an object, rendered to `grafana/dashboards/Monitoring/host.json`.
- **Dashboard:**
  - uid `monitoring-host`, title `Monitoring node · Host health`, tags `["monitoring"]`;
  - `editable: false`, `refresh: "30s"`, `time: {from: "now-6h", to: "now"}`, `timezone: "browser"`, `graphTooltip: 1`, `schemaVersion: 39`.
- **Panels.** These ids are fixed: rules link to them, and plan 06 adds the Pipeline row at 60.
  - `L` = the dashed lines for that threshold.
  - `T` = tile thresholds: base green, then yellow and red. For "lower" pairs the steps run red, yellow, green.
  - Rows are `type: row` at full width. Text panels are 24×2. Time series are 8×8 unless the table says otherwise.
  - The implementer writes the `gridPos` x and y.

| Id | Row | Type | Title | Query (legend) | Unit | Lines/colours |
|---|---|---|---|---|---|---|
| 1 | tiles (h 4, w 3) | stat | CPU | `q.cpu` | percent | T cpu |
| 2 | tiles (w 3) | stat | Memory | `q.memory` | percent | T memory |
| 3 | tiles (w 3) | stat | Root disk | `q.disk` with `mountpoint="/"` | percent | T disk |
| 4 | tiles (w 3) | stat | Data disk | `q.disk` with `mountpoint="/data"` | percent | T disk |
| 5 | tiles (w 4), burstable only | stat | CPU credits | the CloudWatch query | none | T credits (absolute) |
| 6 | tiles (w 4) | stat | Targets up | `100 * avg(up)` | percent | red base, green at 100 |
| 7 | tiles (w 4) | stat | Uptime | `time() - node_boot_time_seconds` | s | fixed blue |
| 10, 11 | CPU | row, text | | | | |
| 12 | CPU | timeseries | CPU used | `q.cpu` (`% used`) | percent | L cpu |
| 13 | CPU, burstable only | timeseries, datasource `-- Mixed --` | CPU credit balance | CloudWatch A (`balance`) plus `vector(...)` lines | none | L credits (absolute) |
| 14 | CPU | timeseries | Load | `node_load1`, `node_load5`, `node_load15`, `count(node_cpu_seconds_total{mode="idle"})` (`cores`) | short | |
| 20, 21 | Memory | row, text | | | | |
| 22 | Memory | timeseries | Memory used | `q.memory` | percent | L memory |
| 23 | Memory | timeseries | Swap used | `q.swap` | percent | L swap |
| 24 | Memory | timeseries (bars) | OOM kills (10 min) | `q.oom_kills` | short | critical line at 1 |
| 25 | Memory (12×8) | timeseries | Memory pressure | `100 * rate(node_pressure_memory_waiting_seconds_total[5m])` (`some`), `100 * rate(node_pressure_memory_stalled_seconds_total[5m])` (`full`) | percent | `noValue: "Not exposed by this kernel"` |
| 26 | Memory (12×8) | timeseries, stacked | Memory by container | `container_memory_working_set_bytes{name=~".+"}` (`{{name}}`) | bytes | |
| 30, 31 | Disk | row, text | | | | |
| 32 | Disk | timeseries | Disk used | `q.disk` (`{{mountpoint}}`) | percent | L disk |
| 33 | Disk | timeseries | Days until full | `q.disk_full_days` (`{{mountpoint}}`) | d | L disk_full_days |
| 34 | Disk | timeseries | Inodes used | `q.inodes` (`{{mountpoint}}`) | percent | L inodes |
| 35 | Disk | timeseries | Prometheus size vs its cap | `q.prometheus_size` | percent | L prometheus_size (warning only) |
| 36 | Disk | timeseries | Postgres size | `pg_database_size_bytes` (`{{datname}}`) | bytes | |
| 37 | Disk | timeseries | Disk I/O | `sum(rate(node_disk_read_bytes_total[5m]))` (`read`), `sum(rate(node_disk_written_bytes_total[5m]))` (`written`) | Bps | |
| 40, 41 | Services | row, text | | | | |
| 42 | Services | timeseries | Targets up | `q.up` (`{{job}}`) | short | critical line at 1 |
| 43 | Services | timeseries | Container restarts (15 min) | `q.restarts` (`{{name}}`) | short | L container_restarts |
| 44 | Services | timeseries | CPU by container | `rate(container_cpu_usage_seconds_total{name=~".+"}[5m])` (`{{name}}`) | short | |
| 45 | Services, domain only | timeseries | TLS days left | `q.tls_days` | d | L tls_days |
| 46 | Services, domain only | timeseries | HTTPS probe | `probe_success` | short | |
| 47 | Services | timeseries | Grafana rule-evaluation failures (10 min) | `q.eval_failures` | short | warning line at 1 |
| 50, 51 | Patching | row, text | | | | |
| 52 | Patching | timeseries | Newer AL2023 release available | `q.os_update_days` | d | L os_release_update_days (warning only) |
| 53 | Patching | stat | Running release | `monitoring_os_release_info` (`{{release}}`, text mode `name`) | | |
| 54 | Patching | stat | Last boot | `node_boot_time_seconds * 1000` | dateTimeAsIso | |

**Text and descriptions**
- Each text panel says in one or two sentences what the row answers and where the thresholds come from.
- A thresholded panel's description is generated from the numbers: for example `Warning above 60 %, critical above 85 %, the same numbers as the alert rules.`

**Interpretation calls**
- Panel 25 is the spec's "hidden if the kernel lacks PSI": it shows `Not exposed by this kernel` instead. Spec 12.8 is verified at plan 09's first run.
- Panel 43 counts Docker's own restarts of a container. A reconcile that *recreates* a container starts a new series, so it doesn't count. Plan 09's first run confirms this against a real config change.

- [ ] **Step 1: Write the failing tests**

**Where the defaults live.** The defaults live once, in `$MOD`'s `thresholds` variable. `tests/grafana.tftest.hcl` gets a file-level `variables { thresholds = { … } }` block that copies the Global Constraints table, and runs override it with `merge(var.thresholds, { … })`. `tests/monitoring_node.tftest.hcl` gets `the_default_thresholds_are_the_specs`, which asserts every resolved `var.thresholds` value against that table, so the two copies can't drift.

In `tests/grafana.tftest.hcl` (`thresholds` at their defaults unless stated):
- **`the_host_dashboard_follows_the_house_style`:**
  - the dashboard fields above;
  - panel ids unique;
  - every `row` is followed by a `text` panel;
  - every non-row, non-text panel has a non-empty `description`.
- **`tiles_and_lines_use_the_thresholds`,** with `cpu_percent = {warning = 50, critical = 80}`:
  - panel 1's steps are `[green null, yellow 50, red 80]`;
  - panel 12's targets include `vector(50)` with legend `warning (50%)` and `vector(80)` with legend `critical (80%)`, and both overrides have `custom.lineStyle.fill == "dash"`;
  - panel 12's description contains `50` and `80`.
- **`credit_panels_need_a_burstable_type`:**
  - for `t9g.medium`, panels 5 and 13 exist, panel 13 has `vector(144)` and `vector(28.8)`, and its CloudWatch target names `i-0123456789abcdef0`;
  - for `m7g.medium`, neither panel exists;
  - for `t3.large`, panel 13 has `vector(216)` and `vector(43.2)`.
- **`tls_panels_need_a_domain`:** panels 45 and 46 exist only with `domain = "grafana.example.com"`.
- **`every_panel_query_is_plain_promql`:** no Prometheus target `expr` contains `$`.

In `tests/monitoring_node.tftest.hcl`:
- `rejects_thresholds_in_the_wrong_order` (`cpu_percent = {warning = 90, critical = 80}`), with `expect_failures = [var.thresholds]`;
- `rejects_lower_is_worse_thresholds_in_the_wrong_order` (`tls_days = {warning = 3, critical = 14}`);
- `rejects_a_fractional_restart_count`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd $MOD && terraform test -filter=tests/grafana.tftest.hcl`
Expected: FAIL. `thresholds` isn't declared yet, and `files["grafana/dashboards/Monitoring/host.json"]` doesn't exist.

- [ ] **Step 3: Implement `queries.tf` and `dashboard-host.tf`**

Build the panels from typed spec lists, `local.stat_specs`, `local.series_specs`, `local.text_specs` and `local.row_specs`. Each list has one for-expression that produces Grafana panel objects. Concatenate them, and order by id. The dashed-line targets and overrides come from one helper local, keyed by threshold name. Add conditional panels with filtered for-expressions, never a conditional between object shapes.

- [ ] **Step 4: Run the tests, the smoke test and the suite**

Run: `cd $MOD && terraform test && bash tests/test-grafana-provisioning.sh`
Expected: PASS; `grafana smoke: OK`, with `monitoring-host` listed in folder `Monitoring` and `promtool` reporting every query valid.

- [ ] **Step 5: Commit**

```bash
git add -A modules/monitoring-node && git commit -m "feat(monitoring-node): add the host health dashboard" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The host alert rules

**Files:**
- Create: `$GRAF/rules-host.tf`
- Modify: `$GRAF/main.tf`
- Test: `$MOD/tests/grafana.tftest.hcl`

**Interfaces:**
- `local.host_rule_specs` is the table below. From it:
  - `local.host_rules` is the rendered rules;
  - `local.host_rule_catalog` is every uid the table can produce;
  - `deleteRules` is the catalogue minus the rendered rules.
  
  The file is `rules-host.json`, `{"apiVersion": 1, "groups": [ {orgId 1, name host, folder Monitoring, interval 1m, rules} ], "deleteRules": [...]}`.
- **Columns of the table below:**
  - **Op:** the threshold `type`, `gt` or `lt`;
  - **Warning / Critical:** the threshold parameter (— means that severity isn't rendered);
  - **Panel:** `__panelId__`;
  - **Needs:** the feature the rule depends on.

| Key | Title | Query | Op | Warning | Critical | For | Panel | Needs |
|---|---|---|---|---|---|---|---|---|
| `cpu` | CPU used | `q.cpu` | gt | cpu.w | cpu.c | 2m | 12 | |
| `cpu-credits` | CPU credit balance | CloudWatch | lt | credits.w × max ÷ 100 | credits.c × max ÷ 100 | 15m | 13 | burstable |
| `memory` | Memory used | `q.memory` | gt | memory.w | memory.c | 2m | 22 | |
| `swap` | Swap used | `q.swap` | gt | swap.w | swap.c | 2m | 23 | |
| `oom-kill` | OOM kill | `q.oom_kills` | gt | — | 0.5 | 2m | 24 | |
| `disk` | Disk used | `q.disk` | gt | disk.w | disk.c | 5m | 32 | |
| `disk-full` | Disk full forecast | `q.disk_full_days` | lt | days.w | days.c | 30m | 33 | |
| `inodes` | Inodes used | `q.inodes` | gt | inodes.w | inodes.c | 5m | 34 | |
| `prometheus-size` | Prometheus size vs its cap | `q.prometheus_size` | gt | size.w | — | 15m | 35 | |
| `target-down` | Scrape target down | `q.up` | lt | — | 0.5 | 2m | 42 | |
| `container-restarts` | Container restarts | `q.restarts` | gt | restarts.w − 0.5 | restarts.c − 0.5 | 2m | 43 | |
| `tls-expiry` | TLS certificate expiry | `q.tls_days` | lt | tls.w | tls.c | 2m | 45 | domain |
| `rule-eval-failures` | Grafana rule-evaluation failures | `q.eval_failures` | gt | 0.5 | — | 2m | 47 | |
| `os-release` | Newer AL2023 release available | `q.os_update_days` | gt | os.w | — | 2m | 52 | |

- **Summaries** state the fact, the number and the window: for example `CPU averaged above 85 % over 10 minutes.` and `Scrape target is down: Prometheus can't reach it.`
- **`prometheus-size`** also says what to do: `raise prometheus_retention.size_gb (and data_volume_gb), or accept that the oldest metrics are dropped`. Once the cap is reached the rule keeps firing. That is the spec's choice, so the owner decides, and the summary says how.

- [ ] **Step 1: Write the failing tests**

In `tests/grafana.tftest.hcl`. Two helpers: `local` lookups through `jsondecode(output files)`, and a for-expression over every rule.

- **`every_rule_mirrors_its_panel`,** run at the defaults and again with `cpu_percent = {50, 80}`, `disk_full_days = {10, 3}` and `container_restarts = {2, 5}`. For every rendered rule:
  - its `__dashboardUid__` is `monitoring-host`;
  - the panel `__panelId__` exists;
  - for a Prometheus rule, the panel has a target whose `expr` equals the rule's A `expr`;
  - the panel has a `vector(<line>)` target for the rule's severity. `<line>` is the threshold parameter, plus 0.5 for `container-restarts`, `oom-kill`, `target-down` (whose line is 1) and `rule-eval-failures`.
- **`rules_pair_and_carry_area_and_severity`:**
  - every uid is `host-<key>-<severity>`;
  - titles end with ` — <severity>`;
  - `labels == {area = "host", severity = <severity>}`;
  - `condition == "C"`.
- **`count_rules_fire_on_the_whole_number`:** at the defaults, `host-container-restarts-warning` has parameter `0.5` and `-critical` has `2.5`.
- **`credit_rules_use_the_types_maximum`:**
  - for `t9g.medium`, `host-cpu-credits-warning` has `lt 144` and `-critical` has `lt 28.8`, with `noDataState == "NoData"`, `execErrState == "Alerting"`, and a reduce step B;
  - for `m7g.medium`, neither is rendered, and both are in `deleteRules`.
- **`switched_off_rules_are_deleted_and_only_those`,** in each of the four combinations of domain and burstable:
  - the rendered uids and the `deleteRules` uids don't overlap;
  - together they are the whole catalogue;
  - the catalogue has 23 uids: 14 keys, 9 of them with both severities.
- **`every_rule_waits_at_least_two_minutes`:** every `for` ends in `m`, and its number is at least 2.

- [ ] **Step 2: Run them to see them fail**

Run: `cd $MOD && terraform test -filter=tests/grafana.tftest.hcl`
Expected: FAIL, `Invalid index` on `files["grafana/provisioning/alerting/rules-host.json"]`.

- [ ] **Step 3: Implement `rules-host.tf`**

Expand each spec into its severities with a for-expression over `[{severity = "warning", value = s.warning}, {severity = "critical", value = s.critical}]`, filtered on non-null values and the spec's feature. Prometheus rules and CloudWatch rules are built by separate for-expressions, because their `data` shapes differ.

- [ ] **Step 4: Run the tests, the smoke test and the suite**

Run: `cd $MOD && terraform test && bash tests/test-grafana-provisioning.sh`
Expected: PASS. The smoke test passes both phases:
- in phase 1, the API lists 21 host rules plus the extra rule;
- in phase 2, the API lists 21 host rules again, with the two TLS rules in and the two credit rules out, and the extra rule is gone;
- `promtool` reports every query valid.

- [ ] **Step 5: Commit**

```bash
git add -A modules/monitoring-node && git commit -m "feat(monitoring-node): add the host alert rules in warning and critical pairs" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Slack routing

**Files:**
- Create: `$GRAF/notifications.tf`
- Modify: `$GRAF/variables.tf`, `$GRAF/main.tf`, `$GRAF/outputs.tf`, `$MOD/variables.tf`, `$MOD/grafana.tf`, `$MOD/bundle.tf` (Grafana's environment), `$MOD/iam.tf`, `$MOD/README.md`, `$MOD/tests/test-grafana-provisioning.sh` (phase 1 gets `slack`)
- Test: `$MOD/tests/grafana.tftest.hcl`, `$MOD/tests/monitoring_node.tftest.hcl`

**Interfaces:**
- **`$MOD` input `slack`,** default `null`, validated:
  - channel names match `^[a-z][a-z0-9-]{0,29}$`, and there is at least one;
  - every parameter starts with `/`;
  - route keys are a subset of `host`, `pipeline` and `cost`, and include `host`, which the root policy and the plan 07 watchdog use;
  - every route value is a channel.
- **`$GRAF` input `slack`** is the same object. Output `webhook_env = { for c in keys(channels) : c => "SLACK_WEBHOOK_${upper(replace(c, "-", "_"))}" }`.
- **`$MOD/grafana.tf`:**
  - `local.slack_channels` is `var.slack.channels`, or `{}`;
  - `local.slack_secrets` is `{ env => parameter }`;
  - the bundle `secrets` merge `local.slack_secrets`;
  - `local.secret_parameter_names` gains `values(local.slack_channels)`;
  - Grafana's `environment` gains `{ for env in keys(local.slack_secrets) : env => "$${${env}:?}" }`.

- [ ] **Step 1: Write the failing tests**

In `tests/grafana.tftest.hcl`:
- **`each_channel_is_a_contact_point_and_each_area_a_route`,** with `slack = { channels = { platform = "/acme/monitoring/slack/platform", costs = "/acme/monitoring/slack/costs" }, routes = { host = "platform", pipeline = "platform", cost = "costs" } }`:
  - the contact points are `slack-platform` and `slack-costs`, each with url `$SLACK_WEBHOOK_PLATFORM` and `$SLACK_WEBHOOK_COSTS` respectively, the two template references, and `disableResolveMessage == false`;
  - the policy root has `receiver == "slack-platform"`, `group_by == ["grafana_folder", "alertname"]` and `repeat_interval == "4h"`;
  - it has 3 child routes, and the `cost` route's receiver is `slack-costs` with `object_matchers == [["area", "=", "cost"]]`;
  - `webhook_env == { costs = "SLACK_WEBHOOK_COSTS", platform = "SLACK_WEBHOOK_PLATFORM" }`.
- **`one_template_formats_every_message`:**
  - `templates.json` has one group, `monitoring-slack`, whose template contains `define "monitoring.title"` and `define "monitoring.text"`, and no `$`;
  - the text skips `alertname`, `grafana_folder` and `severity`, and links `.PanelURL`.
- **`without_slack_the_policy_tree_is_reset`:**
  - with `slack = null`, there are no `contact-points.json` or `templates.json` files;
  - `policies.json` decodes to `{apiVersion = 1, resetPolicies = [1]}`;
  - `webhook_env == {}`.

In `tests/monitoring_node.tftest.hcl` (same `slack`):
- **`with_slack_the_node_reads_each_webhook`:**
  - the `ReadTheParameters` resources include both parameter ARNs;
  - `local.bundle.secrets.SLACK_WEBHOOK_COSTS == "/acme/monitoring/slack/costs"`;
  - Grafana's environment has `SLACK_WEBHOOK_PLATFORM == "$${SLACK_WEBHOOK_PLATFORM:?}"`.
- **Validation runs,** each with `expect_failures = [var.slack]`:
  - `rejects_a_route_to_an_unknown_channel`;
  - `rejects_routes_without_host`;
  - `rejects_an_unknown_area` (`billing`);
  - `rejects_a_bad_channel_name` (`Platform_1`);
  - `rejects_a_relative_parameter`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd $MOD && terraform test`
Expected: FAIL, `An argument named "slack" is not expected here`.

- [ ] **Step 3: Implement `notifications.tf` and the wiring, and give phase 1 of the smoke test its `slack`**

- [ ] **Step 4: Run the tests, the smoke test and the suite**

Run: `cd $MOD && terraform test && bash tests/test-grafana-provisioning.sh`
Expected:
- PASS;
- in phase 1, the API lists `slack-platform` and `slack-costs`, the root receiver `slack-platform`, and the template `monitoring-slack`;
- in phase 2, the root receiver is no longer a `slack-*` contact point;
- no provisioning errors are logged.

- [ ] **Step 5: Commit**

```bash
git add -A modules/monitoring-node && git commit -m "feat(monitoring-node): route alerts to slack channels by area" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The release check the patching rule relies on

**Files:**
- Modify: `$MOD/files/monitoring-release-check.sh`
- Test: `$MOD/tests/test-release-check.sh` (new)

**Interfaces:**
- **Path overrides:** `MONITORING_TEXTFILE_DIR` (default `/var/lib/node_exporter/textfile`) and `MONITORING_STATE_DIR` (default `/var/lib/monitoring`). They exist so the test can run the real script.
- **Behaviour:** capture `dnf -q check-release-update` output and status first, then decide:
  - output mentions `newer release` (whatever the exit status): `available 1`, and `since` is kept from the state file, or set now;
  - status 0 without it: `available 0`, `since 0`, state removed;
  - anything else (dnf failed, for example no network): leave the state and the textfile untouched, print the error, and exit 1. A network blip must not restart the 7-day clock.

This was plan 04's deferred minor. The `os-release` rule now depends on it, so it's in scope.

- [ ] **Step 1: Write the failing test**

`tests/test-release-check.sh` puts fake `dnf` and `rpm` on `PATH` (`rpm` prints `2023.12.20261026`) and runs the script against a scratch directory. Cases:
1. `dnf` prints `WARNING: A newer release of "Amazon Linux" is available.` and exits 100. Then `os_release.prom` has `monitoring_os_release_update_available 1` and a non-zero `since`.
2. Run again. `since` is unchanged.
3. `dnf` exits 1 with `Error: Failed to download metadata`. The script exits 1, and the file is byte-identical to case 2.
4. `dnf` prints nothing and exits 0. Then `available 0`, `since 0`, and no state file.
5. Every run leaves `monitoring_os_release_info{release="2023.12.20261026"} 1`.

- [ ] **Step 2: Run it to see it fail**

Run: `cd $MOD && bash tests/test-release-check.sh`
Expected: FAIL in case 1. Under `pipefail`, the `dnf` exit status 100 makes the `if` false, so the file says `available 0`.

- [ ] **Step 3: Implement, then run it and shellcheck**

Run: `cd $MOD && bash tests/test-release-check.sh && shellcheck files/*.sh tests/*.sh`
Expected: `release check: OK`; shellcheck prints nothing.

- [ ] **Step 4: Commit**

```bash
git add -A modules/monitoring-node && git commit -m "fix(monitoring-node): report a newer al2023 release whatever dnf exits with" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Docs, the example, and the 0.4.0 release

**Files:**
- Modify: `$MOD/README.md`, `$MOD/examples/basic/main.tf`, `$REPO/README.md` (only if it describes the module's features)

- [ ] **Step 1: Write the docs**

The README covers:
- **What the node watches:** the dashboard's rows, and a table of every rule with its default thresholds and `for`.
- **Thresholds:** how to override them.
- **Slack:**
  - channels and routes;
  - adding a channel: one webhook parameter and one line of `slack.channels`;
  - rotating a webhook: change the parameter, and the node applies it within 5 minutes.
- **Silences:** before a planned expensive run, silence its rule in Grafana's UI; silences are allowed even though rules are provisioned.
- **The extension hooks:** dashboard paths, the rule labels routing needs, and that a removed extra rule's uid goes under `deleteRules` in its file.
- **The local smoke test:** what it needs (Docker).

The example adds `slack` with the `acme` parameters.

- [ ] **Step 2: Run the whole suite**

Run: `cd $REPO && scripts/check.sh`
Expected: `All checks passed.`, including both `tests/test-*.sh` scripts.

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "docs(monitoring-node): document host monitoring, slack routing and the hooks" -m "Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Final whole-branch review and fix pass** (executing-plans)

- [ ] **Step 5: Ask the owner, then publish**

With the owner's permission:
1. push `feat/host-monitoring`;
2. open the PR from `.github/PULL_REQUEST_TEMPLATE/feat.md` with the title `feat: add host monitoring to the monitoring node`;
3. squash-merge it once CI is green;
4. merge the `chore(main): release 0.4.0` PR;
5. confirm `v0.4.0` on the registry.

- [ ] **Step 6: Record it**

On the docs branch:
- tick this plan;
- mark 05 released in the roadmap;
- add an "As built in v0.4.0" note to spec 6.7 and 6.8: JSON alerting files, the `deleteRules` catalogue, `disableDeletion: false`, absolute credit thresholds, `for ≥ 2m`, and PSI checked at first run.

Then delete the plan's workspace, and update the memory note.
