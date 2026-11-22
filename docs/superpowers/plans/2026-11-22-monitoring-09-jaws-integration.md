# Jaws Integration Implementation Plan (09)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the monitoring and cost platform into Jaws, ready to provision when the owner merges. That covers:
- **a new config file,** `config/monitoring.yaml`;
- **the foundation's billing bucket** and the monitoring CI roles;
- **two new roots:** a `monitoring/` stack and an owner-applied `billing-export/` root;
- **the workflows;**
- **`jaws monitoring secrets`;**
- **task-run records** with `--campaign`;
- **the docs.**

Nothing is applied by this plan. Every apply happens when the owner merges the Jaws release PR, or runs an owner root.

**Architecture:** spec 8, adjusted to the split `config/` directory (since #295).
- **The settings:** `config/monitoring.yaml` holds one `monitoring` section, validated by `MonitoringSection` in `src/jaws/settings.py`.
- **`foundation/`:** creates the billing bucket (`billing-bucket`), the Databricks billing export (`databricks-billing-export`), and the monitoring stack's plan and apply roles (the `monitoring/*` leaves of `jaws-ci` 0.3.0), like `data-access`'s.
- **`monitoring/`:** a new top-level root, like `data-access/`. It applies the root module of `jaws-monitoring` 0.8.0 from the merged config.
- **`billing-export/`:** an owner root, like `owner-access/`. It creates the org-wide FOCUS export in the management account.

**Tech Stack:** Python 3.13 (Pydantic, Typer, boto3; `uv`, `pytest`, `ruff`, `mypy`), Terraform (`terraform test`, tflint), GitHub Actions, and `npm` (commitlint).

**Spec:** [docs/superpowers/specs/2026-11-21-monitoring-node-design.md](../specs/2026-11-21-monitoring-node-design.md):
- 8, Jaws integration;
- 6.12, task records;
- 10, rollout;
- 3, constraints.

## Global Constraints

**Where things live**
- **Repo:** `/Users/jimmywallace/Projects/Jaws-Platform/jaws`, branch `feat/monitoring-stack` from `origin/main` (v0.77.1).

**Agent rules** (`AGENTS.md`): never run `terraform apply`, `jaws apply/publish/release/destroy`, `bot …`, or `task run/terminate/sweep` against AWS. Never plan `owner-access/` or `billing-export/` against real state. Never push to `main`. This PR is left open for the owner, and is never merged by an agent, nor is the release PR.

**Commits**
- One line `type(scope): subject`, at most 100 characters, lowercase, then only `Co-authored-by: Claude Opus 5.5 <noreply@anthropic.com>`.
- Task 1 adds the scope `monitoring` (the `monitoring/` and `billing-export/` roots, `config/monitoring.yaml`, and their docs).
- The PR uses `.github/pull_request_template.md`.

**Checks before the PR** (`AGENTS.md:25-35`):
- `terraform fmt -recursive`, then `terraform init -backend=false && terraform validate` in each root;
- `tflint --init && tflint --recursive`;
- `npm ci && npm test && npm run test:commitlint`;
- `uv sync && uv run ruff format --check && uv run ruff check && uv run mypy && uv run pytest`;
- `scripts/test-stack-plans.sh`.

**Versions** (exact pins, as every root does):
- `Jaws-Platform/jaws-monitoring/aws` is `0.8.0`, with family `jaws-monitoring` added to `config/terraform.yaml` `library.families`. It's the eighth family, so update the "seven families" docs.
- `Jaws-Platform/jaws-databricks/aws` keeps its pin (its `databricks-billing-export` is in v0.2.0).
- Every `Jaws-Platform/jaws-ci/aws` pin moves from `0.2.0` to `0.3.0`, all 13 of them.

**`config/monitoring.yaml`** (from spec 8; Jaws's values):

```yaml
monitoring:
  instance_type: t9g.medium
  ami: al2023-ami-2023.12.20261026.1-kernel-6.18-arm64   # pinned image name; patching is a PR that bumps it
  domain: grafana.jwall.engineering                       # in the dns zone (config/sites.yaml)
  snapshots: true
  schedule:                                               # off while the owner sleeps; omit for 24/7
    timezone: America/Denver
    days: [mon, tue, wed, thu, fri, sat, sun]
    on: "08:00"
    off: "24:00"                                          # midnight; off 00:00-08:00 MT
  cost:
    bucket: jaws-billing-570327089884                     # bucket names are global; the account makes it ours
    protect_raw: false                                    # true once the first deliveries are checked (spec 10)
    aws: true
    databricks: true
    budgets:
      total: 100
    anomaly_floor_usd: 2
  slack:
    channels:
      platform: /jaws/monitoring/slack/platform
      costs: /jaws/monitoring/slack/costs
    routes: { host: platform, pipeline: platform, cost: costs }
  # thresholds: overrides of the module's defaults (spec 6.8), by name
```

**`MonitoringSection` rules:**
- `extra="forbid"`;
- the schedule rules from 6.10, with the time zone checked by `zoneinfo`;
- every route names a channel, and `routes.host` is required;
- every channel is an SSM parameter under `/jaws/monitoring/`;
- budgets above 0, and an anomaly floor of at least 0;
- `ami` matches `^al2023-ami-.+-arm64$`;
- `cost.bucket` is a valid S3 name;
- project files can't set monitoring keys.

**Names**
- **The stack:** `name_root`-`monitoring`, so `jaws-monitoring` in Jaws. The CI policies (plan 08) scope to that prefix.
- **SSM:** the stack's own parameters are `/jaws-monitoring/node/*` (the module's). The owner's secrets are `/jaws/monitoring/{grafana-admin-user,grafana-admin-password,slack/<channel>}`.
- **The export:** `jaws-focus-daily`, delivered under the bucket's `aws_export_prefix`.

## Review Focus

1. **Merging the PR provisions nothing.** Only the release PR's apply job and the owner's own roots spend money. Test: the workflow tests, or a reading of `ci.yml` and `release-please.yml` that shows `monitoring/` planned on PRs and applied only in the release job, after `foundation/`.
2. **The first release runs in order.** The foundation creates the monitoring roles and the bucket before `monitoring/` plans or applies. A PR plan of `monitoring/` before those roles exist must not block the PR. Test: the CI job's condition; `tests/` for the workflow structure, if Jaws has them.
3. **`billing-export/` stays owner-only.** No CI role, workflow or state prefix references it. Test: like owner-access's isolation test.
4. **Bad config fails early, with the key named.** A 30-minute schedule time, an overnight window, an unknown zone, a route to a missing channel, a zero budget. Tests: `tests/test_settings.py` cases.
5. **A failed task-record write never fails or delays a task,** and a task without `--campaign` writes no `Campaign` tag. Tests: `tests/test_tasks.py`.

---

### Task 1: The scope and the design docs

- [ ] Add the scope `monitoring` to `commitlint.config.mjs` and the CONTRIBUTING scope table (`chore(repo): add the monitoring commit scope`), with its test, if the repo pins the scope list.
- [ ] Bring the spec and the plans (00–09) onto the branch, from the local branch `docs/monitoring-node-design`: `git cherry-pick` its commits after the scope commit. Their `docs(monitoring)` subjects then pass commitlint. Update the spec's `config.yaml` references to `config/monitoring.yaml`.
- [ ] Run `npm test && npm run test:commitlint`. Expected: it passes.

### Task 2: `config/monitoring.yaml` and `MonitoringSection`

- [ ] **Failing tests first** in `tests/test_settings.py`:
  - add `"monitoring": "monitoring.yaml"` to `SECTION_FILES`;
  - `test_the_monitoring_section_loads`;
  - one rejection per rule above, each asserting the error names the key;
  - `test_project_files_cannot_set_monitoring`.
- [ ] Implement `MonitoringSection` (and its parts) and `Settings.monitoring: MonitoringSection | None = None`. Add `config/monitoring.yaml`, and regenerate `foundation/tests/fixtures/*.yaml` (`uv run python -m tests.test_foundation_fixtures`).
- [ ] Docs: `config/README.md`'s table, and the README's config section.
- [ ] Run `uv run pytest tests/test_settings.py`, then the full Python checks. Expected: they pass.
- [ ] Commit `feat(config): add the monitoring config file and its settings`.

### Task 3: The foundation

- [ ] **Failing `foundation/tests/*.tftest.hcl` runs:**
  - **the billing bucket:** `jaws-billing-570327089884`, when `monitoring.cost` is set; its export source is the management account (`management.account_id`); `protect_raw` comes from config;
  - **the Databricks billing export,** when `cost.databricks` is set and Databricks is enabled;
  - **the monitoring plan and apply roles,** with the `monitoring/read` leaf for plan, and every `monitoring/*` leaf for apply, `zone_id` and `domain` from config;
  - **the state prefix entry** for `monitoring/`;
  - **none of it without the `monitoring` section;**
  - **each project's `ci-task` role** gets `s3:PutObject` on `raw/provider=jaws/source=task-runs/project=<project>/*` in the bucket, and nothing else in it.
- [ ] Implement, copying `data_access_ci_*` (`foundation/ci-roles.tf:105-175`) and `foundation/state.tf:49-53`. Bump the 13 `jaws-ci` pins to `0.3.0`, and add the `jaws-monitoring` family.
- [ ] Run `terraform test` in `foundation/` and `scripts/test-stack-plans.sh`. Expected: they pass.
- [ ] Commit `feat(foundation): add the billing bucket and the monitoring stack's roles`.

### Task 4: The `monitoring/` root

**Files:** `monitoring/{main,variables,outputs,versions,providers,config}.tf`, `monitoring/backend/prod.hcl`, `monitoring/tests/monitoring.tftest.hcl` and `monitoring/README.md`; `tests/test_versions.py` scans `monitoring/*.tf`.

- [ ] **The root:**
  - It reads `config/*.yaml` like `foundation/config.tf`.
  - It calls `Jaws-Platform/jaws-monitoring/aws` `0.8.0` with `name = "jaws-monitoring"` and the bucket.
  - **The VPC and subnet** come from the foundation's network, looked up the way `stacks/bot` does.
  - **`aws`:** the export's `delivery_prefix`. **`databricks`:** from `jaws-shared`'s workspace projects.
  - **`runs`:** prefix `raw/provider=jaws/source=task-runs`, join tags `RunId` and `TaskId`.
  - **`zone_id`** comes from the `dns` zone. **`grafana_admin`:** the `/jaws/monitoring/grafana-admin-*` parameters. **`slack`:** the channels and routes.
  - **Pass-through:** `schedule`, `snapshots = { enabled = true }`, the budgets, the floor, and `databricks_workspace_tag = "Workspace"`.
  - Provider `default_tags` as every stack: `Project = monitoring`, and the rest.
- [ ] **Tests** (mock providers):
  - `the_stack_reads_its_config`;
  - `the_node_is_named_for_the_platform`;
  - `the_stack_runs_on_its_schedule`.
- [ ] Commit `feat(monitoring): add the monitoring stack`.

### Task 5: The `billing-export/` owner root

- [ ] **The root:** `aws-billing-export` 0.8.0 in the management account (the owner's profile), named `jaws-focus-daily`, into the bucket and prefix above. It has its own state, as `owner-access/` has. Add a README with the owner's run steps.
- [ ] **Failing isolation test,** copying owner-access's: no CI role, workflow or state prefix names `billing-export`.
- [ ] Commit `feat(monitoring): add the billing-export owner root`.

### Task 6: Workflows

- [ ] **Pull requests:** `ci.yml` validates, tests and plans `monitoring/` with the monitoring plan role, as `data-access` is. The plan job is skipped, with a notice, while that role doesn't exist yet: the first release creates it.
- [ ] **The release:** `release-please.yml` `apply` applies `monitoring/` after `foundation/`, with the monitoring apply role, so one release creates both in order.
- [ ] **Tests:** add or extend workflow tests if the repo has them.
- [ ] Commit `ci(workflows): plan the monitoring stack on pull requests and apply it on release`.

### Task 7: `jaws monitoring secrets`

- [ ] **Failing tests:**
  - `secrets set grafana-admin-user`, `grafana-admin-password` and `slack/<channel>` write SecureStrings under `/jaws/monitoring/`, with a no-echo prompt;
  - `secrets check` lists the missing ones;
  - an unknown name or channel is refused.

  Mirror `bot secrets` (`cli.py:1128-1167`, `bot.put_secret`).
- [ ] Implement; document in `docs/monitoring.md`.
- [ ] Commit `feat(cli): add jaws monitoring secrets`.

### Task 8: Task-run records and `--campaign`

- [ ] **Failing tests** (`tests/test_tasks.py`):
  - **`started`:** `task run` writes the record at launch (runs-1 fields, spec 6.12) to `raw/provider=jaws/source=task-runs/project=<p>/date=YYYY-MM-DD/<run-id>.<task-id>.started.json`;
  - **`finished`:** written at the end, with the outcome, exit code and `interrupted_at`;
  - **`swept`:** `task sweep` writes one;
  - **a failed write** logs a warning, and the task goes on;
  - **`--campaign <slug>`:** validated (`^[a-z0-9-]{1,63}$`), tagged `Campaign` on the instance and volume, and in the record. Without it, there is no tag.
- [ ] Implement.
  - The GPU count comes from `ec2:DescribeInstanceTypes`, which the role already has.
  - The prices come from the launch.
  - The links are the GitHub run, PR and commit, from the workflow environment.
  - The reusable workflow gains a `campaign` input.
  - **If `jaws-ci`'s `task/launch` doesn't allow a `Campaign` request tag:** add it there as a 0.3.x fix (`fix(ci-policies): …`), released before this PR's pins.
- [ ] Commit `feat(cli): write task-run records and tag campaigns`.

### Task 9: Docs and the PR

- [ ] **New docs:** `docs/monitoring.md` (operations, recovery, adding a provider or a channel, the owner's steps) and `docs/billing-export.md`.
- [ ] **Updates:** `docs/costs.md` (`cost report` stays, and points to the dashboards), `docs/remote-tasks.md` (the records), and the README's stack list.
- [ ] **Run every check** in Global Constraints. Then do the final review (opus) and one fix pass.
- [ ] **Push, open the PR,** and leave it open for the owner. The body lists **the owner's steps before the release:**
  - create the Slack webhooks, and set `jaws monitoring secrets` for the Grafana admin and both channels;
  - activate the `Campaign` and `Workspace` cost allocation tags;
  - after the release, run `billing-export/`;
  - set `protect_raw: true` once the first deliveries are checked.
