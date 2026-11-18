# Jaws

The foundation stack for every [jwall.engineering](https://jwall.engineering) site. It owns:

- the shared Terraform state bucket `jwall-engineering-tfstate`
- a reference to the account's GitHub Actions OIDC identity provider (owned by prog-strength-infra for now)
- the `jwall.engineering` Route 53 hosted zone (zone-level records only)
- for each site in the `projects` registry, an S3 bucket and three CI roles
- its own plan and apply CI roles
- the `jaws` CLI that every site repository's CI runs to plan, preview, apply and publish, its image in a private ECR repository, and the reusable workflows that run it
- the owner's admin access: an IAM Identity Center user with the AdministratorAccess permission set, in its own stack that only the owner applies ([guide](docs/owner-access.md))
- bot and research projects: for each entry in the `bots` registry, CI roles (a research project has no release role), and the bot stack (`stacks/bot`) that runs a repository's GitHub releases as a permanent Lichess bot ([guide](docs/lichess-bot.md))

Everything is in `us-east-1`, managed with Terraform `>= 1.11` and the AWS provider `~> 6.0`. The shared building blocks are consumed from the public Terraform Registry, see [Shared modules](#shared-modules-from-the-terraform-registry). Releases are cut and applied by [Release Please](#releases-and-applies). Contribution rules are in [CONTRIBUTING.md](CONTRIBUTING.md); the rules for coding agents are in [AGENTS.md](AGENTS.md).

## Jaws: the `jaws` CLI

Jaws 🦈 started as a static-site tool and now provisions every
kind of project here: sites, bots, research projects and Databricks
workspaces. It was called JWall Engineering Infra, with the command
`jwall-engineering-sites`, until v0.44. The old command, the old project file
name (`jwall-engineering-sites.yaml`) and the old `JES_*` variables still work
and print a warning naming their replacement; they are removed once every
consumer has moved. The cloud resources (the ECR repository
`jwall-engineering-sites`, every `jwall-engineering-` name) and this
repository's name have not moved yet.

`jaws` is the Python CLI (Typer, managed with `uv`) that
provisions and publishes every site from one YAML file in its repository,
`jaws.yaml`. It wraps Terraform and S3: it renders the
bundled site stack in `stacks/site/` from that file and `config.yaml`, runs
`terraform` against the shared state bucket, syncs built content and
invalidates CloudFront. Site repositories keep no Terraform. It ships as a
versioned image in each account's private ECR repository
(`jwall-engineering-sites` in management, `jaws-cli` in production; the
composite action pulls from the account its role is in), published by the
release workflow, and site repositories run it through the reusable workflows
this repository publishes. The design is in
[#26](https://github.com/jwallace145/jaws/pull/26).

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
| `task run --script P --ref SHA [--profile NAME] [--instance-type T] [--market spot\|on-demand] [--max-hours N] [--out DIR] -- ARGS...` | `ci-task` | Bot and research projects with a `task-runner`: refuse a worst-case cost over the ceiling, then run one script on a fresh instance (spot under a price cap by default, on demand only as a launch fallback), stream it, copy its outputs, always terminate; exits with the script's code, or 75 on a spot interruption |
| `task list` | `ci-plan` or `ci-task` | The project's running task instances (read-only) |
| `task terminate (--instance ID \| --run-id ID [--task-id ID] \| --all)`, `task sweep [--dry-run]` | `ci-task` | Terminate task instances; sweep those past their lifetime (by hand: there is no scheduled sweeper) |
| `cost report [--project NAME [--by workflow\|profile]] [--months N]` | the owner's shell | Monthly spend from Cost Explorer: one project by component (task spend split by workflow or profile), or every project plus the untagged spend by service ([docs/costs.md](docs/costs.md)) |
| `databricks doctor [--stage config\|live\|between\|after]` | `ci-plan` or `ci-apply` | Databricks projects: run the read-only checks against the live project and print the table ([docs/databricks.md](docs/databricks.md#doctor)) |
| `databricks credentials set\|check` | the owner's shell | Write (no echo) or check the Databricks service principal's client secret in SSM |
| Databricks projects: `validate`, `plan`, `apply`, `destroy --yes`, `outputs` | none, `ci-plan`, `ci-apply`, `ci-apply`, `ci-plan` | Run across the account and workspace stacks: config and live checks, a deferred or stale workspace plan, apply with a readiness wait and after checks, destroy that empties the catalog bucket first, both stacks' outputs merged |

Every command checks that the credentials are the role it expects, that the
built site and bucket exist, and that the Terraform in the image is the
version `config.yaml` pins, before touching anything. Failures exit 1
(Terraform or AWS), 2 (configuration) or 3 (preflight). Run artifacts and a
debug log go to `./.jaws/`.

```sh
uv sync                                  # the CLI and its dev tools
uv run jaws --help
uv run ruff check && uv run mypy && uv run pytest
docker build --build-arg "TERRAFORM_VERSION=$(yq -r .terraform.version config.yaml)" -t jaws:local .
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
| `site-release-please.yml` | Release Please with the release bot; outputs `release_created` and `tag` | `secrets: inherit` |
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
    uses: jwallace145/jaws/.github/workflows/site-preview.yml@v0.6.1
    with:
      artifact: site
      preview-role-arn: ${{ vars.AWS_PREVIEW_ROLE_ARN }}
      app-client-id: ${{ vars.JES_APP_CLIENT_ID }} # optional: comments come from the app
    secrets:
      app-private-key: ${{ secrets.JES_APP_PRIVATE_KEY }}
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
as approved in `config.yaml`.

### Research projects

A repository with only `dataset` and `task-runner` components (no image, no
bot) is a research project, such as a GPU training project. It uses the same
stack with the bot parts switched off, and its CI roles get `compute/*`
instead of `container/*`. What it may ask for, and the $50 per-task cost
ceiling, are central guardrails in `config.yaml`. Onboarding, the
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
output) and the whole comment is kept under `plan.comment_max_bytes` from
`config.yaml`, truncating the plan text from the head. This repository's own
`Terraform plan` job renders its comment with `report plan-comment`, so the
foundation plan and the site plans look the same.

**Who posts the comment.** By default the sticky comment is authored by
`github-actions[bot]`. Pass `app-client-id` (and the `app-private-key`
secret) to `site-plan.yml` and `site-preview.yml`, or set `JES_APP_CLIENT_ID`
and `JES_APP_PRIVATE_KEY` in this repository, and the workflows mint a
short-lived installation token for the **Jaws** GitHub
App and post as it, with the app's name and avatar. The app needs only
*Pull requests: read and write* and has to be installed on every repository
that posts. If the token cannot be minted the step warns and the comment
falls back to `github-actions[bot]`. A comment that already exists on a pull
request keeps its original author; the app shows up on new pull requests.

The release workflow (`workflow_dispatch` with a `tag`) can re-publish the
image for an existing tag without cutting a release.

## Two accounts, while everything moves

Everything is moving from the management account to a production account.
`config.yaml` describes the management account, and its `production` section
holds what differs in production (account, name prefix `jaws`, state bucket,
image repository) and which projects have a stack there. Its `development`
section records the organization's third account, where nothing is built yet:
no run addresses it, `config accounts` never lists it, and the owner reaches it
through [owner access](docs/owner-access.md) (the `jaws-dev` profile). A run addresses one
account:

- production, for a project listed under `production.projects` (`moving` while
  its old stack still exists, `moved` once that is destroyed);
- management, for every other project and for a run without a project file;
- `--account management` addresses the old stack of a project that is `moving`
  (to destroy it), and `--account production` a run without a project file.

The tags that differ between the accounts are the account's, never the project
file's: every stack the tool renders and every task instance it launches gets
`Organization` and `ManagedBy` from the view's `context.organization` and
`context.managed_by` (`jwall-engineering` and `jwall-engineering-infra` in
management, `jaws` and `jaws` in production), so one project file, which may
state either organization, plans in both accounts while its project moves.

The foundation is one root for both accounts: `terraform plan -var
account=production` plans the production account (state in
`backend/production.hcl`), and the default plans the management account. Each
creates roles and buckets only for the projects with a stack in its account,
and a plan made with the other account's credentials stops before it starts.

The owner bootstrapped the production account on 2026-11-17
([docs/production-bootstrap.md](docs/production-bootstrap.md)). Since then a
pull request's checks plan the foundation in both accounts, and a release
applies it in both and publishes the image to both registries.

Two refusals keep a run in one account. Credentials must belong to the account
the run addresses, even where the role check is skipped (`JAWS_SKIP_ROLE_CHECK`),
so a secret or a stack is never written into the other account by an admin
profile left active. And `destroy` on a project that is `moving` must name its
account: both stacks exist, and the default is the new one.

A site that has moved keeps its old bucket in the management account (without
roles or writers) until the owner deletes it; a move never destroys a bucket.

**Moving a site.** The production zone answers for `jwall.engineering` since
2026-11-18. Every site record was copied into it first, still pointing at the
old distributions. A CloudFront hostname belongs to one distribution at a time,
so a site is down from its old stack's destroy until its new stack is deployed,
about 20–30 minutes:

1. `production.projects: {<site>: moving}`; the release creates the site's
   bucket (`jaws-<site>`) and roles in production. Nothing changes for the site
   yet.
2. In the site's repository, set `AWS_PLAN_ROLE_ARN`, `AWS_PREVIEW_ROLE_ARN`
   and `AWS_APPLY_ROLE_ARN` to
   `arn:aws:iam::<production>:role/jaws-<site>-ci-{plan,preview,apply}`, and
   pin the reusable workflows at that release. Merging the pin deploys nothing.
3. The outage. From the site's checkout, with admin credentials:
   `jaws --account management destroy --yes` removes the old stack (its
   distributions, certificates and old-zone records; the bucket is the
   foundation's and stays). Then dispatch the site's **Release** workflow
   without a tag: it applies the production stack, whose records take over the
   copies, and publishes the latest release.
4. `<site>: moved`. The management foundation drops the site's roles and keeps
   its old bucket for the owner, and the copied validation records of the old
   certificates are deleted from the zone.

`jaws config show` prints the view a run would use, and `jaws config env` the
few values a workflow needs to build a role ARN: every workflow gets a
project's account from it (`config env --project <name>`), never from its own
reading of `config.yaml`. **Bot apply** and **Databricks apply** take an
`account` input for the same choice. `braveheart-bot` has run in production
since 2026-11-18; every other project still addresses the management account.

## Shared modules from the Terraform Registry

This stack is a consumer of [`jwallace145/jwall-engineering/aws`](https://registry.terraform.io/modules/jwallace145/jwall-engineering/aws), the jwall-engineering module library published to the public Terraform Registry from [`jwallace145/terraform-aws-jwall-engineering`](https://github.com/jwallace145/terraform-aws-jwall-engineering). The library is open source under MIT, versioned with semver, and released with the same Release Please flow as this repo. Consuming it here, the same way any third party would, is deliberate: the foundation stack eats its own dog food, so the modules are exercised in production before anyone else depends on them.

| Submodule | Used for | Where |
| --- | --- | --- |
| `//modules/context` | The tag set applied to every resource through `default_tags` | `context.tf` |
| `//modules/tfstate-bucket` | The shared Terraform state bucket | `state.tf` |
| `//modules/hosted-zone` | The `jwall.engineering` zone, its CAA record and the GitHub Pages domain-verification TXT record | `dns.tf` |
| `//modules/ci-plan-role` | Plan roles for this repo and each project, with read policies from the `ci-policies` catalog | `ci-roles.tf`, `projects.tf` |
| `//modules/ci-preview-role` | Preview role per project, with `static-site/previews` | `projects.tf` |
| `//modules/ci-apply-role` | Apply roles for this repo and each project, with read and write policies from the `ci-policies` catalog | `ci-roles.tf`, `projects.tf` |
| `//modules/site-bucket` | One S3 bucket per project, `jwall-engineering-<project>` | `projects.tf` |
| `//modules/ecr-repository` | The private repository for the `jaws` CLI image, configured from `config.yaml` | `ecr.tf` |
| `//modules/identity-center-access` | The owner's Identity Center user and `AdministratorAccess` permission set | `owner-access/main.tf` (its own stack) |

The root module itself creates no resources directly. It is the composition: identity, the `projects` map, module calls, and outputs.

Module sources look like this, with an exact `version` on every block:

```hcl
module "site_bucket" {
  for_each = local.projects
  source   = "jwallace145/jwall-engineering/aws//modules/site-bucket"
  version  = "0.13.0"

  project = each.key
}
```

Versions are pinned exactly, not with `~>`, because Terraform records provider versions in `.terraform.lock.hcl` but not module versions; an exact pin is the only way two applies of the same commit resolve the same code. Every pin (in `foundation/` and both stacks under `stacks/`) is always bumped together, and so is `library.version` in `config.yaml`.

**Upgrading.** When the library publishes a release, Dependabot's Terraform ecosystem opens a `chore(deps)` PR bumping the pins. The CI plan comment on that PR shows exactly what the new version changes in AWS. Read the library's [CHANGELOG](https://github.com/jwallace145/terraform-aws-jwall-engineering/blob/main/CHANGELOG.md) entry, check the plan, merge, and the change applies with the next release of this repo. While the library is on `0.x`, a breaking change bumps the minor version and is marked `!` in its changelog.

## Layout

The foundation Terraform stack lives in `foundation/`; every `.tf` path below
is relative to it. The repository root holds the `jaws`
CLI and `config.yaml`, the tool configuration shared by the stack and the CLI
([design](https://github.com/jwallace145/jaws/pull/26)).

| Path | Owns |
| --- | --- |
| `versions.tf`, `providers.tf`, `context.tf` | Terraform and provider constraints, region, identity, and the registry `context` module whose tags are applied through `default_tags` |
| `backend.tf`, `backend/management.hcl`, `backend/production.hcl` | S3 backend with native lockfile locking (no DynamoDB), one state per account |
| `accounts.tf` | `var.account`: which account this root is planned for, the configuration as that account sees it, and the projects it serves |
| `state.tf` | The shared state bucket (`tfstate-bucket` module) |
| `oidc.tf` | GitHub OIDC provider (data source; owned by prog-strength-infra, see the TODO there) |
| `dns.tf` | The hosted zone, its CAA record and the zone owner's TXT records (`hosted-zone` module) |
| `ci-roles.tf` | This repo's own plan and apply roles (`ci-plan-role` and `ci-apply-role` modules) |
| `ecr.tf` | The ECR repository for the infra CLI image, configured from `config.yaml` at the repository root |
| `config.yaml` (root) | Tool configuration for the infra CLI and the foundation stack: Terraform version, library pin, state bucket, DNS zone, ECR lifecycle, sync headers, and the central guardrails (`tasks.limits`, `tasks.max_run_cost_usd`, and per project the instance types, task profiles and dataset retention) |
| `src/jaws/`, `tests/`, `pyproject.toml` | The infra CLI, its tests and its `uv` project |
| `stacks/site/` | The site stack the CLI renders for each site, pinned to the library like any consumer |
| `stacks/bot/` | The bot stack the CLI renders for each bot or research project: ECR repository, VPC, records bucket, bot instance (the image and bot are off for a research project), task runner and dataset buckets |
| `src/jaws/kinds/lichess_bot/` | The harness Dockerfile and entrypoint of the bot image |
| `bots.tf` | The `bots` map: one entry per bot or research project, each with plan and apply roles, a release role for bots, and a task role where `config.yaml` lists instance types |
| `docs/lichess-bot.md`, `docs/consumer-note.md` | The bot projects guide and the note a bot repository links to |
| `docs/remote-tasks.md`, `docs/datasets.md`, `docs/research-projects.md`, `docs/costs.md` | Task instances, dataset buckets, research projects, and cost reports |
| `docs/databricks.md` | Databricks workspace projects: setup, checks, apply and destroy, layout, costs, known gaps and the runbook |
| `stacks/databricks-account/`, `stacks/databricks-workspace/`, `foundation/databricks.tf` | The two stacks of a Databricks project; the metastore, audit log delivery and the project registry |
| `Dockerfile` | The CLI image: a pinned Terraform, the stack with modules and providers vendored, `config.yaml` |
| `.github/actions/terraform-init` | `terraform init` with a retry for the registry's lag after a library release |
| `projects.tf` | The `projects` map: one entry per site, each fed to the registry `site-bucket`, `ci-plan-role`, `ci-preview-role` and `ci-apply-role` modules |
| `outputs.tf` | Values the project repos and this repo's CI consume |
| `registry/` | Derives the onboarded datasets from `datasets/` (each platform name, bucket and URL), tested against the CLI's derivation |
| `docs/migration.md` | Legacy resources to retire after the move |
| `scripts/apply-repo-settings.sh` | GitHub repository settings and the `main` ruleset |
| `owner-access/` (root) | The owner's admin access through IAM Identity Center: a separate stack, applied only by the owner, never by CI ([docs/owner-access.md](docs/owner-access.md)) |
| `datasets/` (root) | Onboarded datasets, one `<owner>/<name>.yaml` each ([datasets/README.md](datasets/README.md)) |
| `data-access/` (root) | The reconcile: binds and grants each agreed dataset handshake, applied by the **Data access** workflow ([guide](docs/databricks.md#datasets-and-access)) |

## Tags

Every AWS resource this tool manages carries the same six tags, through the provider's `default_tags` (and set explicitly on task instances, which `RunInstances` does not tag by default):

| Tag | Value | Links the resource to |
| --- | --- | --- |
| `Organization` | `jwall-engineering` | the umbrella all projects belong to |
| `Project` | the project's kebab-case name, e.g. `braveheart`; `jwall-engineering-infra` for the foundation stack | the project that owns it (the CI roles' IAM policies also key on it) |
| `Environment` | `prod` | the deployment environment |
| `Repository` | the project's `owner/repo` | the repository whose code it serves |
| `ManagedBy` | `jwall-engineering-infra` | this tool, which provisions and changes it |
| `Owner` | `jwallace145` | the person responsible for it |

Project files state the first five; the CLI cross-checks `Project`, `Repository`, `Environment` and `Organization` against the rest of the file and `config.yaml`, and adds `ManagedBy` itself. The foundation stack gets the same set from the library's `context` module. Components add `Component`, `Purpose` and `Lifecycle` where they apply. These tags are the cost allocation tags `cost report` groups by; [docs/costs.md](docs/costs.md) lists which must be active.

## State bucket and key convention

Every jwall-engineering stack keeps its state in `jwall-engineering-tfstate` under the key

```
project=<project>/env=<env>/<project>-<env>.tfstate
```

For example this stack uses `project=infra/env=prod/infra-prod.tfstate`, and the main site would use `project=main-site/env=prod/main-site-prod.tfstate`. Terraform writes the lock beside it as `<key>.tflock`. The bucket has versioning, SSE-S3, Block Public Access, `BucketOwnerEnforced` ownership, `prevent_destroy`, and a hardened bucket policy:

- each state prefix is reachable only by the CI roles listed for it (`state.tf`): a project's plan role reads `project=<key>/` and may write only `.tflock` objects there, its apply role reads and writes it, and this stack's key is limited to this repo's two roles;
- nothing outside those prefixes is reachable, and bucket configuration (the bucket policy included) cannot be changed, except by the break-glass principals in `local.bucket_admin_principal_arns`: the owner's Identity Center admin role (console and CLI, [docs/owner-access.md](docs/owner-access.md)), the account root user (emergencies) and this repo's apply role. The account has no IAM users.

Every statement is a deny matched on `aws:PrincipalArn`, so it grants nothing: it stops any other principal in the account, including ones with `s3:*` on `*`, from reading or rewriting state. The statements are documented in the library's [`tfstate-bucket` README](https://github.com/jwallace145/terraform-aws-jwall-engineering/tree/main/modules/tfstate-bucket#hardened-bucket-policy).

## Projects registry

`local.projects` in `projects.tf` is the single list of sites:

| Key | Repository | Domain |
| --- | --- | --- |
| `main-site` | `jwallace145/site` | `jwall.engineering` |
| `cs-survival-guide` | `jwallace145/cs-survival-guide` | `survival-guide.jwall.engineering` |
| `guitar-knowledge-base` | `jwallace145/guitar-knowledge-base` | `guitar.jwall.engineering` |

Each entry is passed to the `site-bucket`, `ci-plan-role`, `ci-preview-role` and `ci-apply-role` submodules of the [registry module](#shared-modules-from-the-terraform-registry), which create:

- bucket `jwall-engineering-<key>` (versioned, encrypted, private, CloudFront-readable). Its policy lets only the project's apply role write `prod/` and `dev/` and only its preview role write `previews/`; only the break-glass principals write anything else or change the bucket's configuration. Reads are unrestricted, since the content is public through CloudFront. See the library's [`site-bucket` README](https://github.com/jwallace145/terraform-aws-jwall-engineering/tree/main/modules/site-bucket#hardened-bucket-policy).
- roles `jwall-engineering-<key>-ci-plan`, `-ci-preview`, and `-ci-apply`, trusted for the project's repository, each with managed policies from the library's `ci-policies` catalog scoped to that bucket, to the state prefix `project=<key>/`, and to Route 53 changes for `<domain>`, `*.preview.<domain>`, and the ACM validation records those names need:

| Role | Trusted for | Policies |
| --- | --- | --- |
| `jwall-engineering-<key>-ci-plan` | `pull_request` | `tfstate/read`, `static-site/read`, `ecr/pull` |
| `jwall-engineering-<key>-ci-preview` | `pull_request` | `static-site/previews`, `ecr/pull` |
| `jwall-engineering-<key>-ci-apply` | `environment:prod` | `tfstate/write`, `static-site/read`, `static-site/deploy`, `ecr/pull` |

The zone itself is owned here; every other record is owned by the project repos. `terraform output projects` lists the bucket name and role ARNs per project.

## Bot projects registry

`local.bots` in `bots.tf` is the single list of bot and research projects. A
research project (a `dataset` or `task-runner` and no bot) is also in
`local.research_projects`; it gets `compute/*` instead of `container/*` and no
release role ([docs/research-projects.md](docs/research-projects.md)):

| Key | Repository |
| --- | --- |
| `braveheart` | `Braveheart-Chess/braveheart` |
| `braveheart-bot` | `Braveheart-Chess/braveheart-lichess-bot` |
| `braveheart-selfplay` | `Braveheart-Chess/braveheart-selfplay` |
| `braveheart-trainer` | `Braveheart-Chess/braveheart-trainer` |

An entry for a repository outside this account also carries `owner_id`, the
numeric ID of the organisation that owns it, because the release and task roles
trust GitHub's `repo:<owner>@<owner_id>/<name>@<repository_id>` subject.

`braveheart` was registered as `rusty-chess` until 2026-11-15. Its stack was
rebuilt under the new name and the old one destroyed; the old buckets
(`jwall-engineering-rusty-chess-nnue`, `-records`, `-tasks`) and the old Lichess
token parameter are no longer managed here and are the owner's to delete.

Each entry gets three roles (two for a research project), and a fourth when
the project lists `instance_types` under `projects` in `config.yaml` (a
`task-runner` component). Their state is `project=<key>/` in the shared
bucket, readable by the plan role and writable by the apply role:

| Role | Trusted for | Policies |
| --- | --- | --- |
| `jwall-engineering-<key>-ci-plan` | `pull_request` on this repository | `tfstate/read`, `container/read`, `task/read`, and `dataset/read` with datasets |
| `jwall-engineering-<key>-ci-apply` | `environment:prod` on this repository | `tfstate/write`, `container/read`, `container/manage`, `task/read`, `task/manage`, `container/schedule` (a research project gets `compute/*` and no `container/schedule`), and `dataset/read`, `dataset/manage` with datasets |
| `jwall-engineering-<key>-ci-release` | the bot repository's `v*` tags | `container/release` (which also lets `bot start` start the instance) |
| `jwall-engineering-<key>-ci-task` | the bot repository's `pull_request` and `main` (never forks) | `task/launch`: launch from the project's task template, run commands on and terminate its `Purpose=ci-task` instances |

The bot's infrastructure is planned and applied here; the bot repository
holds only the project file and a release workflow, and its release role can
ship images and roll them out, nothing else. It cannot read the Lichess
token. `terraform output bots` lists the role ARNs.

## CI roles for this repository

| Role | Trusted for | Permissions |
| --- | --- | --- |
| `jwall-engineering-infra-ci-plan` | `pull_request` | `tfstate/read` (this stack's state key, write of its `.tflock` only), `foundation/read` |
| `jwall-engineering-infra-ci-apply` | `environment:prod` | `tfstate/write`, `foundation/read`, `foundation/manage`: everything needed to manage this stack, see below; `ecr/push` for the infra CLI image |

### Why the apply role is scoped the way it is

The policies come from the library's `ci-policies` catalog, whose README holds the full policy text and justification. In short, the apply role is the highest-privilege identity in the setup because it creates IAM roles, and it is constrained so that a compromised `prod` environment cannot reach beyond the `jwall-engineering-*` namespace:

- IAM actions are limited to roles and policies named `jwall-engineering-*`. It cannot touch any other principal, and it cannot modify the shared GitHub OIDC provider.
- `iam:AttachRolePolicy` only accepts a `jwall-engineering-*` customer-managed policy, so it cannot hand out `AdministratorAccess` to a role it creates. It can still edit the inline and customer-managed policies of `jwall-engineering-*` roles, itself included, so treat a compromise of `prod` as a compromise of the account.
- S3 access is limited to the state bucket's configuration (no `DeleteBucket`) and to the `jwall-engineering-*` buckets themselves, never their objects. The state bucket matches that pattern, so object access would have exposed every project's state; the role reaches only this stack's own state through `tfstate/write`.
- Route 53 access is limited to the `jwall.engineering` zone. It cannot create or delete zones.
- Neither role carries `ReadOnlyAccess`, which would grant `s3:GetObject` on every bucket, every project's state included. `foundation/read` grants the reads refresh and drift detection need for this stack.

Both roles trust only the `jwallace145/jaws` repository through the OIDC provider, with the audience pinned to `sts.amazonaws.com`.

## Bootstrap (one time, run locally by the owner with admin credentials)

The state bucket does not exist before the first apply, so the first apply uses local state and is then migrated into the bucket. An override file (gitignored) swaps the backend to `local` for step 1 only.

1. **Apply with local state.**

   ```sh
   cd foundation
   export AWS_PROFILE=jwall-admin       # after `aws sso login`, see docs/owner-access.md; us-east-1, account 650503560686
   printf 'terraform {\n  backend "local" {}\n}\n' > backend_override.tf
   terraform init
   terraform plan -out=bootstrap.tfplan
   ```

   Review the plan. It should create the state bucket, this repo's two CI roles, the CAA record, the three project buckets and nine project CI roles, and **import** the hosted zone. The only changes on the zone should be tags and its comment. The GitHub OIDC provider is read, not imported. Then:

   ```sh
   terraform apply bootstrap.tfplan
   ```

2. **Migrate state into the bucket.** `backend.tf` and `backend/management.hcl` are already in the repo.

   ```sh
   rm backend_override.tf
   terraform init -backend-config=backend/management.hcl -migrate-state
   rm -f terraform.tfstate terraform.tfstate.backup bootstrap.tfplan
   ```

3. **Commit and push the initial scaffold.** This is the only direct push to `main`; every later change goes through a pull request.

   ```sh
   gh repo create jwallace145/jaws --public --source=. --remote=origin --push
   ```

4. **Finish the hand-off** listed at the end of this file.

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
- `Bot plan (<project>)`: for each bot in `bots.tf`, assumes the bot's plan role and posts its plan as a sticky comment. Until the release that creates the bot's roles, it skips with a notice instead of failing.
- `Databricks plan (<project>)`: for each project in `foundation/databricks.tf`, while `databricks.enabled` is true, plans both stacks with the project's plan role and posts one sticky comment (the workspace plan is deferred until the workspace exists, and marked stale if the account plan replaces it).

Every `terraform init` goes through `.github/actions/terraform-init`, which retries the registry's few-minute lag after a library release.

**Releases, applies and the image** (`.github/workflows/release-please.yml`, on push to `main`):

Merges to `main` accumulate in a Release Please PR. Merging that PR creates a tag; the `apply` job checks out the tag, assumes the apply role in the `prod` GitHub environment and runs `terraform apply`; then the `image` job, also in `prod`, builds the CLI image and pushes it to each account's repository as `<repository>:<tag>` (`ecr.repository` in `config.yaml`: `jwall-engineering-sites` in management, `jaws-cli` in production). Nothing is applied to AWS without that human merge. The release bumps the package version in `src/jaws/__init__.py` and the image tag the composite action runs (`.github/actions/jaws/action.yml`); the reusable workflows carry no version, since they use the action from their own commit. `workflow_dispatch` with a `tag` re-publishes the image for an existing release.

No role ARN is a secret, and this repository needs none as a variable. The foundation's plan and apply jobs run once per bootstrapped account (`jaws config accounts` lists them: management, and production once `production.bootstrapped` is true), and each leg builds its role (`<organization>-infra-ci-plan` / `-ci-apply`), its state (`backend/<account>.hcl`) and its `-var account` from its own entry. Bot role ARNs need no variable either: the workflows build them from the account and organization `jaws config env` resolves from `config.yaml` and the bot's name.

**Bot projects** (`.github/workflows/bot-apply.yml`, by hand): applies or destroys one bot's stack in the `prod` environment with its apply role. `.github/workflows/container-release.yml` is the reusable workflow a bot repository calls on each release ([guide](docs/lichess-bot.md#the-caller-workflow)).

**Databricks projects** (`.github/workflows/databricks-apply.yml`, by hand): `workflow_dispatch` with the project name applies both stacks in the `prod` environment with the project's apply role (`action: apply`, the default); `action: destroy` empties the catalog bucket and destroys them; `action: doctor` runs the read-only checks and changes nothing. Re-running after a partial apply is safe ([guide](docs/databricks.md#what-apply-does)).

**Dataset access** (`.github/workflows/data-access.yml`): plans on every pull request, against the base branch's `datasets/` so that dropping a dataset a handshake still names fails, and sweeps every 15 minutes in the `prod` environment with `jwall-engineering-data-access-ci-apply`: each sweep plans and applies exactly what its plan found, so a failed apply is retried and drift undone by the next one; `workflow_dispatch` runs a sweep now. Its role ARNs are built from `config.yaml` like the bots' ([guide](docs/databricks.md#datasets-and-access)).

## Local development

```sh
npm ci                                   # commitlint
pre-commit install --hook-type commit-msg --hook-type pre-commit
terraform fmt -check -recursive          # from the repository root
cd foundation
terraform init -backend=false && terraform validate
tflint --init && tflint --config ../.tflint.hcl --recursive
```

A real plan needs AWS credentials and the remote backend, from `foundation/`: `terraform init -backend-config=backend/management.hcl && terraform plan`.

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
- In each site's repository, set its role ARNs and bucket name as repository variables (from `terraform output projects`). This repository needs none: its workflows derive the foundation's roles from `config.yaml`. (`AWS_PLAN_ROLE_ARN` and `AWS_APPLY_ROLE_ARN`, set here before v0.47, are no longer read and can be deleted.)
- Optional, for comments authored by the product rather than `github-actions[bot]`: create a GitHub App for the tool (the owner's is still named **JWall Engineering Infra**; the name shown beside a comment is the app's, and renaming it is the owner's; no webhook; permissions *Pull requests: read and write*; upload an avatar), generate a private key, and install it on this repo and every site repo. In each of those repos set the variable `JES_APP_CLIENT_ID` to the app's client ID and the secret `JES_APP_PRIVATE_KEY` to the full `.pem` contents, and pass them to the reusable workflows as shown above.
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
- For projects with `dataset` components (listed under `projects.<name>.datasets` in `config.yaml`), after the release that grants `dataset/*` to their roles: run the **Bot apply** workflow; it creates the buckets ([docs/datasets.md](docs/datasets.md)). A versioned bucket needs the foundation apply that grants `s3:PutBucketVersioning` first.
- For a new research project, follow the onboarding order in [docs/research-projects.md](docs/research-projects.md#onboarding-a-research-project).
- For Databricks workspace projects, follow [One-time setup](docs/databricks.md#one-time-setup): the service principal, the IDs and emails in `config.yaml`, `databricks credentials set`, deleting a pre-existing us-east-1 metastore (only with the owner's go-ahead), then `databricks.enabled: true`.
- Work through [docs/migration.md](docs/migration.md) to retire the legacy resources.

## License

[MIT](LICENSE)
