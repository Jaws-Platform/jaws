[![Jaws: one platform for every project on AWS](https://raw.githubusercontent.com/Jaws-Platform/jaws-branding/main/assets/banner/jaws-readme-banner.png)](https://github.com/Jaws-Platform)

# jaws

[![GitHub release](https://img.shields.io/github/v/release/Jaws-Platform/jaws?label=release)](https://github.com/Jaws-Platform/jaws/releases/latest)
[![CI](https://github.com/Jaws-Platform/jaws/actions/workflows/ci.yml/badge.svg?event=pull_request)](https://github.com/Jaws-Platform/jaws/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/Jaws-Platform/jaws/blob/main/LICENSE)

The foundation stack for every [jwall.engineering](https://jwall.engineering) site. It owns:

- the shared Terraform state bucket `jaws-terraform-state-570327089884`
- a reference to the account's GitHub Actions OIDC identity provider (created outside this stack: by hand at bootstrap in a new account, in this account by prog-strength-infra; the foundation only reads it, and destroying the stack that owns it removes the provider every CI role trusts)
- the `jwall.engineering` Route 53 hosted zone (zone-level records only)
- for each site onboarded in `config/projects.yaml`, an S3 bucket and three CI roles
- its own plan and apply CI roles
- the `jaws` CLI that every site repository's CI runs to plan, preview, apply and publish, its image in a private ECR repository, and the reusable workflows that run it
- the owner's admin access: an IAM Identity Center user with the AdministratorAccess permission set, in its own stack that only the owner applies ([guide](docs/owner-access.md))
- bot and research projects: for each one onboarded in `config/projects.yaml`, CI roles (a research project has no release role), and the bot stack (`stacks/bot`) that runs a repository's GitHub releases as a permanent Lichess bot ([guide](docs/lichess-bot.md))
- the monitoring and cost platform: the billing bucket every bill lands in, and the monitoring stack (`monitoring/`), a node serving Grafana at `grafana.jwall.engineering` with cost and host dashboards and Slack alerts, applied by the release after the foundation ([guide](docs/monitoring.md))
- the organization's AWS billing export, in its own root (`billing-export/`) in the management account, applied only by the owner ([guide](docs/billing-export.md))

Everything is in `us-east-1`, managed with Terraform `>= 1.11` and the AWS provider `~> 6.0`. The shared building blocks are consumed from the public Terraform Registry, see [Shared modules](#shared-modules-from-the-terraform-registry). Releases are cut and applied by [Release Please](#releases-and-applies). Contribution rules are in [CONTRIBUTING.md](CONTRIBUTING.md); the rules for coding agents are in [AGENTS.md](AGENTS.md).

## Jaws: the `jaws` CLI

Jaws 🦈 started as a static-site tool and now provisions every
kind of project here: sites, bots, research projects and Databricks
workspaces. It was called JWall Engineering Infra, with the command
`jwall-engineering-sites`, until v0.44; every name it builds now starts with
`jaws` (README, "History").

`jaws` is the Python CLI (Typer, managed with `uv`) that
provisions and publishes every site from one YAML file in its repository,
`jaws.yaml`. It wraps Terraform and S3: it renders the
bundled site stack in `stacks/site/` from that file and the tool
configuration (`config/`), runs
`terraform` against the shared state bucket, syncs built content and
invalidates CloudFront. Site repositories keep no Terraform. It ships as a
versioned image in the account's private ECR repository (`jaws-cli`),
published by the
release workflow, and site repositories run it through the reusable workflows
this repository publishes. The design is in
[#26](https://github.com/Jaws-Platform/jaws/pull/26).

| Command | Role it expects | What it does |
| --- | --- | --- |
| `validate` | none | Validate both files, render the stack, `terraform validate` offline |
| `plan` | `ci-plan` | Plan with the derived backend; writes the plan comment and `changes=true\|false` |
| `preview deploy --pr N --dist DIR`, `preview remove --pr N` | `ci-preview` | Publish or remove `previews/pr-N/` |
| `apply` | `ci-apply` | Init, plan, apply, write `outputs.json` |
| `publish --dist DIR [--environment prod\|dev]` | `ci-apply` | Sync content and invalidate the distribution |
| `release --dist DIR` | `ci-apply` | `apply` then `publish` |
| `outputs`, `config show` | `ci-plan` / none | Stack outputs as JSON; the effective tool configuration |
| `config env` | none | The account this run addresses, as `key=value` lines for a workflow's `GITHUB_OUTPUT` |
| `report plan-comment --exit-code N --plan FILE --subject S` | none | Render the branded plan comment from a saved plan log (this repo's own CI uses it) |
| `access render --out DIR [--base-registry DIR]` | none (`GH_TOKEN`) | Render `data-access/`'s variables and summary from `datasets/` and every project's file; refuses dropping a dataset that a handshake still names ([guide](docs/databricks.md#datasets-and-access)) |
| `destroy --yes` | `ci-apply` | Bot and research projects: destroy the stack (the records, dataset and task results buckets and the secret are kept; refuses while tasks run). A site: only the old stack of a site that is `moving`, with `--account management` (its distributions, certificates and old-zone records; the bucket stays) |
| `bot build --version vX.Y.Z` | none | Bot projects: download and verify the release asset, build and smoke-test the image (Docker) |
| `bot push --version vX.Y.Z` | `ci-release` | Push the image under the release tag; refuses an existing tag |
| `bot deploy --version vX.Y.Z [--restart]` | `ci-release` | Roll the bot to a pushed tag and follow the swap (waits for the game in progress) |
| `bot reconcile [--version vX.Y.Z] [--dry-run]` | `ci-release` | Build, push and deploy as needed; idempotent; what the release workflow runs |
| `bot status` | `ci-plan` or `ci-release` | Instance, versions, rollout status and running hours |
| `bot start`, `bot stop [--wait]` | `ci-release` | Start the stopped instance and wait for the bot; or drain it (the game in progress finishes, then the instance powers off). For a bot with running hours ([docs/lichess-bot.md](docs/lichess-bot.md#running-hours)), or any bot |
| `bot logs [--since D] [--follow]` | `ci-plan` | The container's CloudWatch logs |
| `bot secrets set\|check NAME` | the owner's shell | Write (no echo) or check a SecureString secret |
| `task run --script P --ref SHA [--profile NAME] [--instance-type T] [--market spot\|on-demand] [--max-hours N] [--campaign SLUG] [--out DIR] -- ARGS...` | `ci-task` | Bot and research projects with a `task-runner`: refuse a worst-case cost over the ceiling, then run one script on a fresh instance (spot under a price cap by default, on demand only as a launch fallback), stream it, copy its outputs, always terminate; exits with the script's code, or 75 on a spot interruption. With `monitoring.cost` configured, it writes the run's `started` and `finished` records to the billing bucket (a failed write is only a warning); `--campaign` tags the instance and volume `Campaign` |
| `task list` | `ci-plan` or `ci-task` | The project's running task instances (read-only) |
| `task terminate (--instance ID \| --run-id ID [--task-id ID] \| --all)`, `task sweep [--dry-run]` | `ci-task` | Terminate task instances; sweep those past their lifetime (by hand: there is no scheduled sweeper), writing a `swept` record for each |
| `cost report [--project NAME [--by workflow\|profile]] [--months N]` | the owner's shell | Monthly spend from Cost Explorer: one project by component (task spend split by workflow or profile), or every project plus the untagged spend by service ([docs/costs.md](docs/costs.md)) |
| `databricks doctor [--stage config\|live\|between\|after]` | `ci-plan` or `ci-apply` | Databricks projects: run the read-only checks against the live project and print the table ([docs/databricks.md](docs/databricks.md#doctor)) |
| `databricks credentials set\|check` | the owner's shell | Write (no echo) or check the Databricks service principal's client secret in SSM |
| `monitoring secrets set NAME`, `monitoring secrets check` | the owner's shell | Write (no echo) one of the monitoring stack's SecureStrings under `/jaws/monitoring/` (`grafana-admin-user`, `grafana-admin-password`, `slack/<channel>`), or list the missing ones ([docs/monitoring.md](docs/monitoring.md#secrets)) |
| Databricks projects: `validate`, `plan`, `apply`, `destroy --yes`, `outputs` | none, `ci-plan`, `ci-apply`, `ci-apply`, `ci-plan` | Run across the account and workspace stacks: config and live checks, a deferred or stale workspace plan, apply with a readiness wait and after checks, destroy that empties the catalog bucket first, both stacks' outputs merged |

Every command checks that the credentials are the role it expects, that the
built site and bucket exist, and that the Terraform in the image is the
version this release is built with (`src/jaws/product.yaml`), before touching anything. Failures exit 1
(Terraform or AWS), 2 (configuration) or 3 (preflight). Run artifacts and a
debug log go to `./.jaws/`.

```sh
uv sync                                  # the CLI and its dev tools
uv run jaws --help
uv run ruff check && uv run mypy && uv run pytest
docker build --build-arg "TERRAFORM_VERSION=$(yq -r .terraform.version src/jaws/product.yaml)" -t jaws:local .
```

### Reusable workflows for site repositories

Site repositories do not run the image themselves. They call the reusable
workflows this repository publishes, pinned to an exact tag that Dependabot
bumps. The workflow at tag `vX.Y.Z` runs image `vX.Y.Z` (the composite action
`.github/actions/jaws` pins the tag, and Release Please
bumps it with the package version), so one pin covers both.

That holds because each reusable workflow checks this repository out at its
own commit, `job.workflow_sha`, and the next step stops the job unless the
checkout is at exactly that commit. (`github.job_workflow_sha` is empty inside
a reusable workflow, and a checkout without a ref falls back to `main`; a
consumer pinned to v0.50.0 or earlier therefore runs `main`'s action and
image tag, whatever it pinned.)

| Workflow | Calls | Caller needs |
| --- | --- | --- |
| `site-plan.yml` | `validate`, then `plan`, and posts the sticky plan comment | `plan-role-arn`; `id-token: write`, `pull-requests: write`; optionally `app-client-id` and the `app-private-key` secret |
| `site-preview.yml` | `preview deploy` on open/synchronize/reopen, `preview remove` on close, and the sticky preview comment | `artifact`, `preview-role-arn`; the same permissions and optional app inputs |
| `site-release-please.yml` | Release Please with the release bot; outputs `release_created` and `tag` | the `RELEASE_BOT_CLIENT_ID` and `RELEASE_BOT_PRIVATE_KEY` secrets, passed by name (`secrets: inherit` only reaches callers in the Jaws-Platform organization) |
| `site-deploy.yml` | `release` in the caller's `prod` environment at the tag | `artifact`, `tag`, `apply-role-arn`; `id-token: write` |

Every job uploads `.jaws/` (the debug log, plan text and
comment files) as an artifact. A site's preview workflow is a build job plus
one call:

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, closed]
jobs:
  build:
    if: github.event.action != 'closed'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v7
      - run: uv sync --frozen && uv run zensical build --strict --clean
      - uses: actions/upload-artifact@v4
        with: { name: site, path: site }
  preview:
    needs: build
    if: always() && !cancelled()
    uses: Jaws-Platform/jaws/.github/workflows/site-preview.yml@v0.6.1
    with:
      artifact: site
      preview-role-arn: ${{ vars.AWS_PREVIEW_ROLE_ARN }}
      app-client-id: ${{ vars.JAWS_APP_CLIENT_ID }} # optional: comments come from the app
    secrets:
      app-private-key: ${{ secrets.JAWS_APP_PRIVATE_KEY }}
    permissions: { contents: read, id-token: write, pull-requests: write }
```

### Bot projects

A repository whose `jaws.yaml` has `components` (one
`container-image` and one `lichess-bot`) instead of `domain` and `site` is a
bot project. `validate`, `plan`, `apply` and `outputs` work on it with the
bot stack, `stacks/bot`. That stack holds the image repository, a VPC with
public subnets and no NAT, the records bucket and the bot instance, all from
the library at the same pin. The `bot` commands build, push and roll out
images.

The bot's stack is planned on every pull request here (the `Bot plan` job)
and applied by hand (the `Bot apply` workflow). An apply can replace the
instance and end the game in progress, so it is never automatic. The bot
repository's own release workflow calls `container-release.yml`, which runs
`bot reconcile` with the bot's release role. The full guide, with every
field, the rollout guarantees, the game-records layout, costs and a
runbook, is [docs/lichess-bot.md](docs/lichess-bot.md). A note for the bot's
own README is in [docs/consumer-note.md](docs/consumer-note.md).

A bot project can also add a `task-runner` component: its CI jobs then run
long, CPU-bound scripts (an engine SPRT, a match series) on dedicated,
ephemeral EC2 instances, a 64-core `c8a.16xlarge` on spot by default,
through the reusable `remote-task.yml` workflow. The guide, with the caller,
the task script contract, spot pricing and interruptions, the security
model, the leak guards, costs and a runbook, is
[docs/remote-tasks.md](docs/remote-tasks.md). Task **profiles** add other
kinds of instance with their own image, disk, market and vCPU budget, such
as on-demand NVIDIA GPU instances for training (`profile: gpu`), or one
profile per workflow (`profile: sprt`).

`dataset` components keep data that must outlive a run, such as NNUE
training data, in kept-forever, append-only S3 buckets that task instances
can add to: [docs/datasets.md](docs/datasets.md). A dataset can also be
versioned, expire named prefixes, and protect prefixes from overwriting, all
as approved in the project's entry in `config/projects.yaml`.

### Research projects

A repository with only `dataset` and `task-runner` components (no image, no
bot) is a research project, such as a GPU training project. It uses the same
stack with the bot parts switched off, and its CI roles get `compute/*`
instead of `container/*`. What it may ask for (its entry in
`config/projects.yaml`) and the $50 per-task cost ceiling (`config/bots.yaml`)
are central guardrails. Onboarding, the
`task-artifact` helper, resuming a training across runs, costs and destroy:
[docs/research-projects.md](docs/research-projects.md).

### Databricks workspaces

A repository whose only component is a `databricks-workspace` is a Databricks
workspace project. Two stacks (`stacks/databricks-account`, then
`stacks/databricks-workspace`) give it a customer-managed VPC with a NAT
instance, a workspace on the owner's Databricks-on-AWS account, its own Unity
Catalog catalog and bucket, and central compute policies. Preflight checks run
before, between and after the stacks, and every run appends event records to
S3. The pull request plans both stacks (the `Databricks plan` job) and the
**Databricks apply** workflow applies or destroys them by hand. One-time
setup, the checks and the runbook, costs and known gaps:
[docs/databricks.md](docs/databricks.md).

### The pull request comments

The plan and preview comments are the product's face in a site repository, so
the CLI renders them (`report.py`) as one branded card rather than raw plan
text: a centred **Jaws** header naming the site, one
GitHub alert that carries the verdict, the detail a reviewer needs without
expanding anything, the full Terraform output folded away, and a footer with
the tool version, the commit and the workflow run. The alert is conditional
on what the plan found:

| Plan result | Alert | Shown without expanding |
| --- | --- | --- |
| No changes | `NOTE`: merging will not touch AWS | nothing else |
| Changes | `WARNING` with the add/change/destroy counts | a counts table and a per-resource action table |
| Any destroy or replace | `CAUTION` naming how many resources are destroyed or replaced | the same tables, with 🗑️ and ♻️ rows to check |
| Plan failed | `CAUTION` | the Terraform output, already expanded |

The resource table lists at most 40 resources (the rest are in the full
output) and the whole comment is kept under 60000 bytes (the release's
`PLAN_COMMENT_MAX_BYTES`), truncating the plan text from the head. This repository's own
`Terraform plan` job renders its comment with `report plan-comment`, so the
foundation plan and the site plans look the same.

**Who posts the comment.** By default the sticky comment is authored by
`github-actions[bot]`. Pass `app-client-id` (and the `app-private-key`
secret) to `site-plan.yml` and `site-preview.yml`, or set `JAWS_APP_CLIENT_ID`
and `JAWS_APP_PRIVATE_KEY` in this repository, and the workflows mint a
short-lived installation token for the **Jaws** GitHub
App and post as it, with the app's name and avatar. The app needs only
*Pull requests: read and write* and has to be installed on every repository
that posts. If the token cannot be minted the step warns and the comment
falls back to `github-actions[bot]`. A comment that already exists on a pull
request keeps its original author; the app shows up on new pull requests.

The release workflow (`workflow_dispatch` with a `tag`) can re-publish the
image for an existing tag without cutting a release.

## Accounts

Everything jaws builds lives in one AWS account, the JWall Engineering
production account (570327089884). `config/aws.yaml` is the account registry,
and its `primary` account is that one, with its owner's admin role
(`admin_role_arn`). The rest of the tool configuration describes what jaws
builds there: the `jaws` name root (`context.name_root`), the state
bucket, the image repository and the `jwall.engineering` zone. A run never
chooses an account, and every workflow builds its role ARNs from
`jaws config env`.

Each account in the registry has a free-form name, a type (`management`,
`development`, `staging` or `production`; at most one is `management`) and its
ID. The registry also records the organization's other two accounts, where
jaws builds nothing and no run goes:

- **management** (type `management`): AWS Organizations and IAM Identity
  Center, and with them [owner access](docs/owner-access.md) (the `jwall-admin`
  profile);
- **development** (type `development`): reached as the `jaws-dev` profile.

Projects choosing their own environments and accounts from the registry is
planned ([#294](https://github.com/Jaws-Platform/jaws/issues/294)); today every
project is built in the primary account.

Two tags are the tool's, never the project file's: every stack the tool
renders and every task instance it launches gets `Organization` (the GitHub
organization or user the project is registered under in `config/projects.yaml`;
`Jaws-Platform` for jaws's own stacks) and `ManagedBy` (`context.managed_by`, `JAWS` by default). A project
file may not state either ([docs/tagging.md](docs/tagging.md)).

Credentials must belong to the primary account, even where the role check
is skipped (`JAWS_SKIP_ROLE_CHECK`), so a secret or a stack is never written
into another account by an admin profile left active. The foundation's plan
stops the same way (`foundation/config.tf`).

## History

- **2026-10-14:** the first foundation, in what is now the organization's
  management account, adopting the `jwall.engineering` zone from
  `jwallace145/site`.
- **2026-11-17:** the production account was bootstrapped.
- **2026-11-18 to 11-21:** every project moved to production, one at a time,
  each with a stack in both accounts while it moved: the sites, the Lichess
  bot, Databricks (rebuilt as a whole), then the research projects with their
  datasets, each copy audited key, size and ETag. The registrar switched to the
  production zone on 2026-11-18.
- **2026-11-21:** the management account was retired: every jaws resource there
  destroyed and its old data deleted, after a final byte-for-byte check against
  production (Jaws-Platform/jaws#265). The repository moved from `jwallace145`
  to the `Jaws-Platform` organization the same day (#253, #259), and the
  two-account code was removed. Its runbooks are in the git history, under
  `docs/production-bootstrap.md`, `docs/migration.md` and
  `docs/management-retirement.md`.
- **2026-11-22:** `config.yaml` became the `config/` directory, and the project
  registries moved from `foundation/*.tf` into `config/projects.yaml`, with the
  accounts in a typed registry, `config/aws.yaml` (#292). Onboarding a project
  became one change to `config/projects.yaml`; nothing in AWS changed.

## Shared modules from the Terraform Registry

This stack is a consumer of the eight Jaws module families, published to the public Terraform Registry from `Jaws-Platform/terraform-aws-jaws-<family>`. Each is open source under MIT, versioned with semver on its own, and released with the same Release Please flow as this repo. Consuming them here, the same way any third party would, is deliberate: Jaws eats its own dog food, so the modules are exercised in production before anyone else depends on them.

| Family | Modules used here | Where |
| --- | --- | --- |
| [`Jaws-Platform/jaws-foundation/aws`](https://registry.terraform.io/modules/Jaws-Platform/jaws-foundation/aws) | `context` (the tag set applied through `default_tags`), `tfstate-bucket` (the shared state bucket), `service-linked-role`, `private-bucket` (bot records and task results), `identity-center-access` (the owner's access) | `foundation/`, `stacks/bot/`, `owner-access/`, `monitoring/`, `billing-export/` |
| [`Jaws-Platform/jaws-ci/aws`](https://registry.terraform.io/modules/Jaws-Platform/jaws-ci/aws) | `ci-plan-role`, `ci-preview-role`, `ci-apply-role`, `ci-release-role` and `ci-task-role`, each with policies from the `ci-policies` catalog | `foundation/` |
| [`Jaws-Platform/jaws-static-site/aws`](https://registry.terraform.io/modules/Jaws-Platform/jaws-static-site/aws) | The root module (the site stack), `site-bucket` (one S3 bucket per site, `jaws-<project>`), `hosted-zone` (the `jwall.engineering` zone, its CAA record and the GitHub Pages verification TXT record) | `stacks/site/`, `foundation/` |
| [`Jaws-Platform/jaws-lichess-bot/aws`](https://registry.terraform.io/modules/Jaws-Platform/jaws-lichess-bot/aws) | `container-instance` (the bot), `ecr-repository` (bot images, and the private repository for the `jaws` CLI image) | `stacks/bot/`, `foundation/ecr.tf` |
| [`Jaws-Platform/jaws-research/aws`](https://registry.terraform.io/modules/Jaws-Platform/jaws-research/aws) | `task-runner` (one per task profile), `dataset-bucket` | `stacks/bot/` |
| [`Jaws-Platform/jaws-network/aws`](https://registry.terraform.io/modules/Jaws-Platform/jaws-network/aws) | `vpc`, `nat-instance` | `stacks/bot/`, `stacks/databricks-account/`, `monitoring/` |
| [`Jaws-Platform/jaws-databricks/aws`](https://registry.terraform.io/modules/Jaws-Platform/jaws-databricks/aws) | The twelve `databricks-*` modules: the account baseline and shared datasets, each project's workspace, catalog and compute policies, who may read each dataset, and the billing export job | `foundation/databricks.tf`, `foundation/monitoring.tf`, `stacks/databricks-account/`, `stacks/databricks-workspace/`, `data-access/` |
| [`Jaws-Platform/jaws-monitoring/aws`](https://registry.terraform.io/modules/Jaws-Platform/jaws-monitoring/aws) | The root module (the billing normalizer and the monitoring node: the monitoring stack), `billing-bucket` (the billing bucket), `aws-billing-export` (the organization's FOCUS export) | `monitoring/`, `foundation/monitoring.tf`, `billing-export/` |

Until Jaws 0.66 these were one library, [`jwallace145/jaws/aws`](https://registry.terraform.io/modules/jwallace145/jaws/aws), which is deprecated at its last version, 0.29.0. Version 0.1.0 of each family holds the same module code, so the move changed no resource.

The root module itself creates no resources directly. It is the composition: identity, the projects it reads from `config/projects.yaml`, module calls, and outputs.

Module sources look like this, with an exact `version` on every block:

```hcl
module "site_bucket" {
  for_each = local.projects
  source   = "Jaws-Platform/jaws-static-site/aws//modules/site-bucket"
  version  = "0.1.2"

  project = each.key
}
```

Versions are pinned exactly, not with `~>`, because Terraform records provider versions in `.terraform.lock.hcl` but not module versions; an exact pin is the only way two applies of the same commit resolve the same code. Every pin of a family (in `foundation/`, the stacks under `stacks/`, `owner-access/`, `data-access/`, `monitoring/` and `billing-export/`) is always bumped together, and so is that family's entry in `src/jaws/product.yaml`.

**Upgrading.** When a family publishes a release, Dependabot's Terraform ecosystem opens a `chore(deps)` PR bumping its pins. The CI plan comment on that PR shows exactly what the new version changes in AWS. Read the family's changelog entry (`CHANGELOG.md` in `Jaws-Platform/terraform-aws-jaws-<family>`), check the plan, merge, and the change applies with the next release of this repo. While a family is on `0.x`, a breaking change bumps the minor version and is marked `!` in its changelog.

## Layout

The foundation Terraform stack lives in `foundation/`; every `.tf` path below
is relative to it. The repository root holds the `jaws`
CLI and `config/`, the tool configuration shared by the stack and the CLI
([design](https://github.com/Jaws-Platform/jaws/pull/26); [its
files](#the-tool-configuration-config)).

| Path | Owns |
| --- | --- |
| `versions.tf`, `providers.tf`, `context.tf` | Terraform and provider constraints, region, identity, and the registry `context` module whose tags are applied through `default_tags` |
| `backend.tf`, `backend/prod.hcl` | S3 backend with native lockfile locking (no DynamoDB) |
| `config.tf` | The tool configuration (`config/`) as the foundation reads it: the primary account, every onboarded project (`local.registry`), and the check that the credentials are the primary account's |
| `state.tf` | The shared state bucket (`tfstate-bucket` module) |
| `oidc.tf` | GitHub OIDC provider (data source; created outside this stack, by hand at bootstrap in a new account and in this account by prog-strength-infra: see the TODO(owner) there; destroying that stack removes the provider every CI role trusts) |
| `dns.tf` | The hosted zone, its CAA record and the zone owner's TXT records (`hosted-zone` module) |
| `ci-roles.tf` | This repo's own plan and apply roles (`ci-plan-role` and `ci-apply-role` modules) |
| `ecr.tf` | The ECR repositories for the infra CLI image (`ecr` in `config/tool.yaml`) and, with a hub, for the hub image (`platform.hub.image`), and who pulls and pushes them |
| `config/` (root) | Tool configuration for the infra CLI and the foundation stack: the account registry, every onboarded project with its central guardrails, state bucket, DNS zone, ECR lifecycle, the bot and task runtimes and Databricks ([its files](#the-tool-configuration-config)) |
| `src/jaws/`, `tests/`, `pyproject.toml` | The infra CLI, its tests and its `uv` project |
| `stacks/site/` | The site stack the CLI renders for each site, pinned to the static-site module family like any consumer |
| `stacks/bot/` | The bot stack the CLI renders for each bot or research project: ECR repository, VPC, records bucket, bot instance (the image and bot are off for a research project), task runner and dataset buckets |
| `src/jaws/kinds/lichess_bot/` | The harness Dockerfile and entrypoint of the bot image |
| `bots.tf` | The bot and research projects' roles (types `bot` and `research` in `config/projects.yaml`): plan and apply roles, a release role for bots, and a task role where the project's entry lists instance types |
| `docs/lichess-bot.md`, `docs/consumer-note.md` | The bot projects guide and the note a bot repository links to |
| `docs/remote-tasks.md`, `docs/datasets.md`, `docs/research-projects.md`, `docs/costs.md` | Task instances, dataset buckets, research projects, and cost reports |
| `docs/databricks.md` | Databricks workspace projects: setup, checks, apply and destroy, layout, costs, known gaps and the runbook |
| `docs/monitoring.md`, `docs/billing-export.md` | The monitoring stack: configuration, applies, the owner's setup, Grafana, the schedule, alerts, recovery, new providers and channels, costs; the organization's billing export |
| `monitoring.tf` | The billing bucket, the Databricks billing job and the monitoring stack's CI roles, with `config/monitoring.yaml`'s `monitoring` section |
| `stacks/databricks-account/`, `stacks/databricks-workspace/`, `foundation/databricks.tf` | The two stacks of a Databricks project; the metastore, audit log delivery and each Databricks project's roles (type `databricks` in `config/projects.yaml`) |
| `Dockerfile` | The CLI image: a pinned Terraform, the stack with modules and providers vendored, `config/` (at `/etc/jaws/config`) |
| `.github/actions/terraform-init` | `terraform init` with a retry for the registry's lag after a library release |
| `projects.tf` | The sites (type `site` in `config/projects.yaml`), each fed to the registry `site-bucket`, `ci-plan-role`, `ci-preview-role` and `ci-apply-role` modules |
| `outputs.tf` | Values the project repos and this repo's CI consume |
| `registry/` | Derives the onboarded datasets from `datasets/` (each platform name, bucket and URL), tested against the CLI's derivation |
| `scripts/apply-repo-settings.sh` | GitHub repository settings and the `main` ruleset |
| `scripts/projects.sh` | The projects of the given types in `config/projects.yaml`, as JSON: the CI plan matrices and the apply workflows' check of a project's name |
| `owner-access/` (root) | The owner's admin access through IAM Identity Center: a separate stack, applied only by the owner, never by CI ([docs/owner-access.md](docs/owner-access.md)) |
| `datasets/` (root) | Onboarded datasets, one `<owner>/<name>.yaml` each ([datasets/README.md](datasets/README.md)) |
| `data-access/` (root) | The reconcile: binds and grants each agreed dataset handshake, applied by the **Data access** workflow ([guide](docs/databricks.md#datasets-and-access)) |
| `monitoring/` (root) | The monitoring stack: the billing normalizer, the monitoring node and its watchdog, in a VPC of its own; planned on pull requests and applied by the release after the foundation ([docs/monitoring.md](docs/monitoring.md)) |
| `billing-export/` (root) | The organization's FOCUS billing export, in the management account: applied only by the owner, never by CI ([docs/billing-export.md](docs/billing-export.md)) |

### The tool configuration: `config/`

`config/` is one YAML document split across files: each file holds some of the
top-level sections, and a section lives in one file only (the CLI and the
foundation both refuse a section defined twice). One file holding every section
is also accepted, as the tests' fixtures do. The CLI reads `./config` by
default; `--config` and `JAWS_CONFIG` take the directory or one file, and the
image bakes it at `/etc/jaws/config`.

| File | Sections |
| --- | --- |
| `aws.yaml` | `aws`: the account registry, and `primary`, the account jaws builds in ([Accounts](#accounts)) |
| `projects.yaml` | `projects`: every onboarded project, by GitHub owner, with its type, repository and central guardrails ([Projects registry](#projects-registry)) |
| `terraform.yaml` | `state` (the state bucket, its region and key template) |
| `tool.yaml` | `context` (name_root, organization, owner, managed_by), `ecr` (the CLI image repository and its lifecycle) |
| `sites.yaml` | `dns` (the Route 53 zone, and its own TXT records) |
| `platform.yaml` | `platform` (the repositories whose own workflows plan and apply the platform, which its roles trust, and the hub) |
| `bots.yaml` | `bot` (the bot runtime: AMIs, availability zones, records prefix, `asset_wait`), `tasks` (remote tasks: Rust toolchain, images, `limits`, `max_run_cost_usd`) |
| `databricks.yaml` | `databricks` (`enabled`, the account, service principal, metastore, compute policies and `shared_host_url`) |
| `monitoring.yaml` | `monitoring` (the monitoring node's `instance_type`, `ami`, `domain`, `snapshots` and off-hours `schedule`; `cost`: the billing bucket, its providers, `budgets` and the anomaly floor; `slack`: the channels' webhook parameters and the alert routes; `thresholds` overrides). Platform-owned: no project file can set it |

The CLI reads these files as YAML 1.2 does, as the workflows' `yq` does: only
`true` and `false` are booleans, so a key such as `on:` stays the string `on`.
Terraform's `yamldecode` follows YAML 1.1 there and reads a bare `on:` and
`off:` as the keys `"true"` and `"false"`, so `monitoring/` reads the
schedule's `on` and `off` under either name.

## Tags

Every AWS resource this tool manages carries the same six tags, through the provider's `default_tags` (and set explicitly on task instances, which `RunInstances` does not tag by default). [docs/tagging.md](docs/tagging.md) is the tagging strategy: where each tag comes from, and why names and access never depend on `Organization` or `ManagedBy`.

| Tag | Value | Links the resource to |
| --- | --- | --- |
| `Organization` | the GitHub organization or user that owns the project's repository, as registered in `config/projects.yaml`, e.g. `Braveheart-Chess`; `Jaws-Platform` for jaws's own stacks | whose project it is |
| `Project` | the project's kebab-case name, e.g. `braveheart`; `jaws` for the foundation stack | the project that owns it (the CI roles' IAM policies also key on it) |
| `Environment` | `prod` | the deployment environment |
| `Repository` | the project's `owner/repo` | the repository whose code it serves |
| `ManagedBy` | `JAWS` | this tool, which provisions and changes it |
| `Owner` | `jwallace145` | the person responsible for it |

Project files state `Project`, `Environment`, `Repository` and `Owner`; the CLI cross-checks the first three against the rest of the file and adds `Organization` and `ManagedBy` itself (a file that states either is refused). Names come from `context.name_root` (`jaws`), never from a tag. The foundation stack gets the same set from the library's `context` module. Components add `Component`, `Purpose` and `Lifecycle` where they apply. These tags are the cost allocation tags `cost report` groups by; [docs/costs.md](docs/costs.md) lists which must be active.

## State bucket and key convention

Every jaws stack keeps its state in `jaws-terraform-state-570327089884` under the key

```
project=<project>/env=<env>/<project>-<env>.tfstate
```

For example this stack uses `project=infra/env=prod/infra-prod.tfstate`, and the main site would use `project=main-site/env=prod/main-site-prod.tfstate`. Terraform writes the lock beside it as `<key>.tflock`. The bucket has versioning, SSE-S3, Block Public Access, `BucketOwnerEnforced` ownership, `prevent_destroy`, and a hardened bucket policy:

- each state prefix is reachable only by the CI roles listed for it (`state.tf`): a project's plan role reads `project=<key>/` and may write only `.tflock` objects there, its apply role reads and writes it, and this stack's key is limited to this repo's two roles;
- nothing outside those prefixes is reachable, and bucket configuration (the bucket policy included) cannot be changed, except by the break-glass principals in `local.bucket_admin_principal_arns`: the owner's Identity Center admin role (console and CLI, [docs/owner-access.md](docs/owner-access.md)), the account root user (emergencies) and this repo's apply role. The account has no IAM users.

Every statement is a deny matched on `aws:PrincipalArn`, so it grants nothing: it stops any other principal in the account, including ones with `s3:*` on `*`, from reading or rewriting state. The statements are documented in the library's [`tfstate-bucket` README](https://github.com/Jaws-Platform/terraform-aws-jaws-foundation/tree/main/modules/tfstate-bucket#hardened-bucket-policy).

## Projects registry

`config/projects.yaml` is the one place a project is onboarded: every site, bot,
research project and Databricks workspace. Projects are grouped by the GitHub
account that owns their repository, an organization or a user, which states its
numeric ID once:

```yaml
projects:
  Braveheart-Chess:                  # the GitHub owner
    owner_id: "356866252"            # gh api users/<owner> --jq .id
    projects:
      braveheart-trainer:            # the key: kebab-case, unique across owners
        description: The trainer for Braveheart's NNUE nets, with bullet on GPU instances
        type: research               # site, bot, research or databricks
        repository: braveheart-trainer
        repository_id: "1459456509"  # gh api repos/<owner>/<repo> --jq .id
        instance_types: [c8a.xlarge, g6.xlarge, g6.2xlarge, g6e.xlarge]
        task_profiles: [cpu, gpu]
        datasets:
          jaws-braveheart-trainer-nets:
            prefix: data/
            versioning: true
```

`type` decides what the foundation gives the project:

| Type | Gets |
| --- | --- |
| `site` | a site bucket and plan, preview and apply roles (`projects.tf`); needs `domain` |
| `bot` | the bot stack's roles, a release role included (`bots.tf`) |
| `research` | the bot stack's roles without a release role, with `compute/*` instead of `container/*` (`bots.tf`) |
| `databricks` | Databricks plan and apply roles (`databricks.tf`); needs its `databricks` entry |

The rest of an entry is the project's central guardrails, reviewed here:
`instance_types`, `task_profiles`, `datasets` and `max_run_cost_usd` for a bot
or research project ([guide](docs/research-projects.md#central-guardrails)),
and `databricks` for a Databricks project
([guide](docs/databricks.md#onboarding-a-project)). The CLI refuses an entry
that does not fit its type: a site needs a `domain` and has no task or dataset
guardrails, only a site has a domain, and only a Databricks project has a
`databricks` entry. Keys are lowercase kebab-case and unique across owners.

The foundation reads the file as `local.registry` (`config.tf`), and
`projects.tf`, `bots.tf` and `databricks.tf` take the projects of their types
from it (`local.projects`, `local.bots` and `local.databricks_projects`). They
define the roles and buckets; none of them lists a project.

**Onboarding a project** is one reviewed change to `config/projects.yaml`:

1. Add its entry under its GitHub owner, with its description, type,
   repository, `repository_id` and guardrails. A new owner gets its group and
   `owner_id` as well.
2. Open a pull request. No workflow changes: the `Bot plan` and
   `Databricks plan` jobs take their projects from the file
   (`scripts/projects.sh`), and **Bot apply** and **Databricks apply** take
   the project's name as text and check it against the file.
3. Release. The foundation apply creates the project's roles, and a site's
   bucket.

What follows the release is in each kind's guide:
[bots](docs/lichess-bot.md#owner-setup-once),
[research projects](docs/research-projects.md#onboarding-a-research-project)
and [Databricks workspaces](docs/databricks.md#onboarding-a-project); a site
sets its role ARNs as repository variables ([Owner hand-off](#owner-hand-off)).

### Sites

The sites are the entries of type `site`, which `projects.tf` takes as
`local.projects`:

| Key | Repository | Domain |
| --- | --- | --- |
| `main-site` | `jwallace145/site` | `jwall.engineering` |
| `cs-survival-guide` | `jwallace145/cs-survival-guide` | `survival-guide.jwall.engineering` |
| `guitar-knowledge-base` | `jwallace145/guitar-knowledge-base` | `guitar.jwall.engineering` |

Each entry is passed to the `site-bucket`, `ci-plan-role`, `ci-preview-role` and `ci-apply-role` submodules of the [registry module](#shared-modules-from-the-terraform-registry), which create:

- bucket `jaws-<key>` (versioned, encrypted, private, CloudFront-readable). Its policy lets only the project's apply role write `prod/` and `dev/` and only its preview role write `previews/`; only the break-glass principals write anything else or change the bucket's configuration. Reads are unrestricted, since the content is public through CloudFront. See the library's [`site-bucket` README](https://github.com/Jaws-Platform/terraform-aws-jaws-static-site/tree/main/modules/site-bucket#hardened-bucket-policy).
- roles `jaws-<key>-ci-plan`, `-ci-preview`, and `-ci-apply`, trusted for the project's repository, each with managed policies from the library's `ci-policies` catalog scoped to that bucket, to the state prefix `project=<key>/`, and to Route 53 changes for `<domain>`, `*.preview.<domain>`, and the ACM validation records those names need:

| Role | Trusted for | Policies |
| --- | --- | --- |
| `jaws-<key>-ci-plan` | `pull_request` | `tfstate/read`, `static-site/read`, `ecr/pull` |
| `jaws-<key>-ci-preview` | `pull_request` | `static-site/previews`, `ecr/pull` |
| `jaws-<key>-ci-apply` | `environment:prod` | `tfstate/write`, `static-site/read`, `static-site/deploy`, `ecr/pull` |

The zone itself is owned here; every other record is owned by the project repos. `terraform output projects` lists the bucket name and role ARNs per project.

## Bot projects registry

The bot and research projects are the entries of type `bot` and `research` in
`config/projects.yaml`, which `bots.tf` takes as `local.bots`. A research
project (type `research`: a `dataset` or `task-runner` and no bot) gets
`compute/*` instead of `container/*` and no release role
([docs/research-projects.md](docs/research-projects.md)):

| Key | Repository |
| --- | --- |
| `braveheart` | `Braveheart-Chess/braveheart` |
| `braveheart-bot` | `Braveheart-Chess/braveheart-lichess-bot` |
| `braveheart-selfplay` | `Braveheart-Chess/braveheart-selfplay` |
| `braveheart-trainer` | `Braveheart-Chess/braveheart-trainer` |
| `pi-benchmarks` | `Pi-Mathematical-Reasoning/pi-benchmarks` |
| `pi-prover` | `Pi-Mathematical-Reasoning/pi` |
| `prog-strength-archive` | `Prog-Strength/prog-strength-archive` |

Each project takes `owner_id`, the numeric ID of the organization or user that
owns its repository, from its owner's group, because the release and task roles
trust GitHub's `repo:<owner>@<owner_id>/<name>@<repository_id>` subject.

`braveheart` was registered as `rusty-chess` until 2026-11-15. Its stack was
rebuilt under the new name and the old one destroyed.

Each project gets three roles (two for a research project), and a fourth when
its entry in `config/projects.yaml` lists `instance_types` (a `task-runner`
component). Their state is `project=<key>/` in the shared
bucket, readable by the plan role and writable by the apply role:

| Role | Trusted for | Policies |
| --- | --- | --- |
| `jaws-<key>-ci-plan` | `pull_request` on this repository | `tfstate/read`, `container/read`, `task/read`, and `dataset/read` with datasets |
| `jaws-<key>-ci-apply` | `environment:prod` on this repository | `tfstate/write`, `container/read`, `container/manage`, `task/read`, `task/manage`, `container/schedule` (a research project gets `compute/*` and no `container/schedule`), and `dataset/read`, `dataset/manage` with datasets |
| `jaws-<key>-ci-release` | the bot repository's `v*` tags | `container/release` (which also lets `bot start` start the instance) |
| `jaws-<key>-ci-task` | the bot repository's `pull_request` and `main` (never forks) | `task/launch`: launch from the project's task template, run commands on and terminate its `Purpose=ci-task` instances; with `monitoring.cost`, `task/records`: put the task-run records under `raw/provider=jaws/source=task-runs/project=<key>/` in the billing bucket, nothing else there |

The bot's infrastructure is planned and applied here; the bot repository
holds only the project file and a release workflow, and its release role can
ship images and roll them out, nothing else. It cannot read the Lichess
token. `terraform output bots` lists the role ARNs.

## CI roles for this repository

| Role | Trusted for | Permissions |
| --- | --- | --- |
| `jaws-infra-ci-plan` | `pull_request` | `tfstate/read` (this stack's state key, write of its `.tflock` only), `foundation/read` |
| `jaws-infra-ci-apply` | `environment:prod` | `tfstate/write`, `foundation/read`, `foundation/manage`: everything needed to manage this stack, see below; `ecr/push` for the infra CLI image |
| `jaws-monitoring-ci-plan` | `pull_request` | `tfstate/read` (the monitoring stack's state key), `monitoring/read`, `compute/read` |
| `jaws-monitoring-ci-apply` | `environment:prod` | `tfstate/write`, `monitoring/read`, `monitoring/node`, `monitoring/config`, `monitoring/functions`, `monitoring/backup` (the `jaws-monitoring` stack, its Grafana record, and with a domain `monitoring/off-hours-page`: the certificate's validation CNAME `_*.<domain>` and the `Project`-tagged ACM certificate, CloudFront distribution and function; nothing else in the zone), `compute/read`, `compute/manage` (its VPC) |

### Why the apply role is scoped the way it is

The policies come from the library's `ci-policies` catalog, whose README holds the full policy text and justification. In short, the apply role is the highest-privilege identity in the setup because it creates IAM roles, and it is constrained so that a compromised `prod` environment cannot reach beyond the `jaws-*` namespace:

- IAM actions are limited to roles and policies named `jaws-*`. It cannot touch any other principal, and it cannot modify the shared GitHub OIDC provider. The one exception is the account's EC2 Spot service-linked role (`AWSServiceRoleForEC2Spot`), in an account with a task runner: the apply role may create it (`iam:CreateServiceLinkedRole`, only for `spot.amazonaws.com`) and tag it, and the plan role may read it. Neither may delete it. EC2 needs the role before the first Spot launch in an account, and a task launch role must not be able to create it.
- `iam:AttachRolePolicy` only accepts a `jaws-*` customer-managed policy, so it cannot hand out `AdministratorAccess` to a role it creates. It can still edit the inline and customer-managed policies of `jaws-*` roles, itself included, so treat a compromise of `prod` as a compromise of the account.
- S3 access is limited to the state bucket's configuration (no `DeleteBucket`) and to the `jaws-*` buckets themselves, never their objects. The state bucket matches that pattern, so object access would have exposed every project's state; the role reaches only this stack's own state through `tfstate/write`.
- Route 53 access is limited to the `jwall.engineering` zone. It cannot create or delete zones.
- Neither role carries `ReadOnlyAccess`, which would grant `s3:GetObject` on every bucket, every project's state included. `foundation/read` grants the reads refresh and drift detection need for this stack.

Every role this repository's workflows assume trusts the repositories in `platform.repositories` (`config/platform.yaml`), today `Jaws-Platform/jaws` alone, through the OIDC provider. That covers these two, the monitoring and data access roles, and each bot, research and Databricks project's plan and apply roles. With `platform.hub`, each site's plan role also trusts the hub's pull requests. The audience stays pinned to `sts.amazonaws.com`.

## Bootstrap (one time, run locally by the owner with admin credentials)

Only for rebuilding the foundation in an account that has none. The state
bucket does not exist before the first apply, so the first apply keeps its
state in a local file and then migrates it into the bucket.

1. **Give the owner admin access to the account** with `owner-access/`
   ([docs/owner-access.md](docs/owner-access.md)), and put the admin role's ARN
   (`aws iam list-roles --path-prefix /aws-reserved/sso.amazonaws.com/`) in
   `config/aws.yaml` as the primary account's `admin_role_arn`. The hardened
   bucket policies exempt
   exactly that role: a wrong suffix locks the owner out of the state bucket.
2. **Ask for the quotas** the task runners need (Running On-Demand Standard
   and Standard Spot vCPUs, VPCs per Region, and G and VT for GPU profiles).
3. **Create the GitHub OIDC provider:** `aws iam create-open-id-connect-provider
   --url https://token.actions.githubusercontent.com --client-id-list
   sts.amazonaws.com`. The foundation reads it rather than owning it.
4. **Apply with local state.**

   ```sh
   cd foundation
   printf 'terraform {\n  backend "local" {}\n}\n' > backend_override.tf
   terraform init -reconfigure
   terraform plan -out=bootstrap.tfplan
   terraform apply bootstrap.tfplan
   ```

5. **Migrate the state into the bucket**, then check that a plan says No changes.

   ```sh
   rm backend_override.tf
   terraform init -backend-config=backend/prod.hcl -migrate-state
   rm -f terraform.tfstate terraform.tfstate.backup bootstrap.tfplan
   terraform plan
   ```

6. **Record the zone:** `terraform output -raw hosted_zone_id` is `dns.zone_id`
   in `config/sites.yaml`; the registrar's name servers follow once the zone
   holds every record.
7. **Finish the hand-off** listed at the end of this file.

## CI/CD

**On pull requests** (`.github/workflows/ci.yml`):

- `Commit messages`: commitlint over every commit in `base..head`
- `PR title`: Conventional Commit check on the title
- `Terraform fmt, validate, tflint` (`foundation/`) and `Site stack validate, tflint` (`stacks/site/`)
- `Terraform plan`: assumes the plan role through OIDC and posts the foundation plan as the branded sticky PR comment (rendered by `jaws report plan-comment`), updated on every push
- `Python lint, types, tests`: ruff, mypy and pytest for the infra CLI
- `Image build and smoke test`: builds the CLI image, runs `validate` inside it offline, checks its Terraform version and enforces the compressed-size budget
- `Bot stack validate, tflint` (`stacks/bot/`), `Databricks account stack validate, tflint` (`stacks/databricks-account/`) and `Databricks workspace stack validate, tflint` (`stacks/databricks-workspace/`)
- `Stack plans against mock providers`: `scripts/test-stack-plans.sh` plans `stacks/bot` and both Databricks stacks with tfvars the CLI renders for the cases in `tests/stack_plans/<stack>/`; no AWS or Databricks
- `Bot plan (<project>)`: for each bot and research project in `config/projects.yaml` (the `Bot projects` job lists them with `scripts/projects.sh bot research`), assumes the project's plan role and posts its plan as a sticky comment. Until the release that creates the project's roles, it skips with a notice instead of failing.
- `Databricks plan (<project>)`: for each Databricks project in `config/projects.yaml` (`scripts/projects.sh databricks`), while `databricks.enabled` in `config/databricks.yaml` is true, plans both stacks with the project's plan role and posts one sticky comment (the workspace plan is deferred until the workspace exists, and marked stale if the account plan replaces it).
- `Monitoring stack validate, tflint, test` (`monitoring/`, against mock providers) and `Monitoring plan`: with `config/monitoring.yaml`'s `monitoring` section, plans the monitoring stack with `jaws-monitoring-ci-plan` and posts its sticky comment; until the release that creates that role, it skips with a notice ([guide](docs/monitoring.md#how-it-is-applied)).

Every `terraform init` goes through `.github/actions/terraform-init`, which retries the registry's few-minute lag after a library release.

**Releases, applies and the image** (`.github/workflows/release-please.yml`, on push to `main`):

Merges to `main` accumulate in a Release Please PR. Merging that PR creates a tag; the `apply` job checks out the tag, assumes the apply role in the `prod` GitHub environment and runs `terraform apply`, then, with the `monitoring` section, applies `monitoring/` with `jaws-monitoring-ci-apply`; then the `image` job, also in `prod`, builds the CLI image and pushes it to the account's repository as `<repository>:<tag>` (`ecr.repository` in `config/tool.yaml`, `jaws-cli`). Nothing is applied to AWS without that human merge. The release bumps the package version in `src/jaws/__init__.py` and the image tag the composite action runs (`.github/actions/jaws/action.yml`); the reusable workflows carry no version, since they use the action from their own commit. `workflow_dispatch` with a `tag` re-publishes the image for an existing release.

No role ARN is a secret, and this repository needs none as a variable. The foundation's plan and apply jobs build their role (`<name_root>-infra-ci-plan` / `-ci-apply`) from the account and name root `jaws config env` reads from the tool configuration (the primary account in `config/aws.yaml`, `context.name_root` in `config/tool.yaml`), and keep their state through `backend/prod.hcl`. Bot role ARNs need no variable either: the workflows build them the same way, with the bot's name.

**Bot projects** (`.github/workflows/bot-apply.yml`, by hand): `workflow_dispatch` with the project's name, which must be a bot or research project in `config/projects.yaml`, applies or destroys its stack in the `prod` environment with its apply role. `.github/workflows/container-release.yml` is the reusable workflow a bot repository calls on each release ([guide](docs/lichess-bot.md#the-caller-workflow)).

**Databricks projects** (`.github/workflows/databricks-apply.yml`, by hand): `workflow_dispatch` with the project name, which must be a Databricks project in `config/projects.yaml`, applies both stacks in the `prod` environment with the project's apply role (`action: apply`, the default); `action: destroy` empties the catalog bucket and destroys them; `action: doctor` runs the read-only checks and changes nothing. Re-running after a partial apply is safe ([guide](docs/databricks.md#what-apply-does)).

**Dataset access** (`.github/workflows/data-access.yml`): plans on every pull request, against the base branch's `datasets/` so that dropping a dataset a handshake still names fails, and sweeps every 15 minutes in the `prod` environment with `jaws-data-access-ci-apply`: each sweep plans and applies exactly what its plan found, so a failed apply is retried and drift undone by the next one; `workflow_dispatch` runs a sweep now. Its role ARNs are built from the tool configuration like the bots' ([guide](docs/databricks.md#datasets-and-access)).

## Local development

```sh
npm ci                                   # commitlint
pre-commit install   # the pre-commit, commit-msg and pre-push hooks
terraform fmt -check -recursive          # from the repository root
cd foundation
terraform init -backend=false && terraform validate
tflint --init && tflint --config ../.tflint.hcl --recursive
```

A real plan needs AWS credentials and the remote backend, from `foundation/`: `terraform init -backend-config=backend/prod.hcl && terraform plan`.

## Owner hand-off

Not automated; these need the owner's credentials or the GitHub UI.

**From the conventions:**

- Add repository secrets `RELEASE_BOT_CLIENT_ID` and `RELEASE_BOT_PRIVATE_KEY` (the full `.pem` contents).
- Install the `jwallace145-release-bot` GitHub App on this repo with Contents read/write and Pull requests read/write.
- After the first pull request is merged, run `scripts/apply-repo-settings.sh` to set merge methods, auto-delete of head branches, and the `main` ruleset.

**For this stack:**

- The owner's admin access is IAM Identity Center (`aws sso login --profile jwall-admin`): [docs/owner-access.md](docs/owner-access.md). On a rebuild, follow its console setup, apply `owner-access/`, then put the new role's ARN in the break-glass list.

- Run the bootstrap steps above.
- Create the GitHub `prod` environment with a deployment branch restriction to `main`.
- In each site's repository, set its role ARNs and bucket name as repository variables (from `terraform output projects`). This repository needs none: its workflows derive the foundation's roles from the tool configuration (`config/`). (`AWS_PLAN_ROLE_ARN` and `AWS_APPLY_ROLE_ARN`, set here before v0.47, are no longer read and can be deleted.)
- Optional, for comments authored by the product rather than `github-actions[bot]`: create a GitHub App for the tool (the owner's is still named **JWall Engineering Infra**; the name shown beside a comment is the app's, and renaming it is the owner's; no webhook; permissions *Pull requests: read and write*; upload an avatar), generate a private key, and install it on this repo and every site repo. In each of those repos set the variable `JAWS_APP_CLIENT_ID` to the app's client ID and the secret `JAWS_APP_PRIVATE_KEY` to the full `.pem` contents, and pass them to the reusable workflows as shown above.
- Activate cost allocation tags in Billing: `Organization`, `Project`, `Environment`, `Repository`, `ManagedBy`, `Owner`, `Component`, `Purpose`, `Profile` and `Lifecycle` (task instances carry `Purpose=ci-task`, `Profile=cpu|gpu` and `Lifecycle=spot|on-demand`, for the later tag-based cost tooling).
- For GPU task profiles, raise the EC2 quotas in Service Quotas (us-east-1) as needed: *Running On-Demand G and VT instances* (5 vCPUs today, one `g6.xlarge` at a time) and *All G and VT Spot Instance Requests* (0 today). See [docs/remote-tasks.md](docs/remote-tasks.md#quotas).
- For bot projects, after the release that creates their roles:
  - commit the project file and the caller workflow in the bot repository;
  - run the **Bot apply** workflow;
  - set the token with `jaws bot secrets set LICHESS_TOKEN`.

  The [guide](docs/lichess-bot.md#owner-setup-once) has the full list.
- For bot projects with a `task-runner`, after the release that creates the `ci-task` role:
  - run the **Bot apply** workflow (it creates the launch template and the task results bucket);
  - add the caller workflow to the bot repository ([docs/remote-tasks.md](docs/remote-tasks.md#the-caller)).
- For projects with `dataset` components (listed under `datasets` in the project's entry in `config/projects.yaml`), after the release that grants `dataset/*` to their roles: run the **Bot apply** workflow; it creates the buckets ([docs/datasets.md](docs/datasets.md)). A versioned bucket needs the foundation apply that grants `s3:PutBucketVersioning` first.
- For a new research project, follow the onboarding order in [docs/research-projects.md](docs/research-projects.md#onboarding-a-research-project).
- For Databricks workspace projects, follow [One-time setup](docs/databricks.md#one-time-setup): the service principal, the IDs and emails in `config/databricks.yaml`, `databricks credentials set`, deleting a pre-existing us-east-1 metastore (only with the owner's go-ahead), then `databricks.enabled: true` there.
- For the monitoring stack, follow [First-time setup](docs/monitoring.md#first-time-setup): before its first release, the Slack webhooks, `jaws monitoring secrets set` for the Grafana admin and each channel, and the `Campaign` and `Workspace` cost allocation tags; after it, apply `billing-export/` ([docs/billing-export.md](docs/billing-export.md)) and set `monitoring.cost.protect_raw: true` once the first deliveries are checked.

## License

[MIT](LICENSE)
