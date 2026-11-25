# Guidance for coding agents

This repository is Terraform for the jaws foundation stack (state bucket, GitHub OIDC provider, `jwall.engineering` hosted zone, per-project buckets and CI roles). Read [README.md](README.md) for the layout and [CONTRIBUTING.md](CONTRIBUTING.md) for the full rules. The rules below are the ones you MUST follow.

## Rules

- **Never push to `main`.** Every change goes through a pull request on a branch. There are no exceptions after the initial scaffold.
- **Commits are a single line**: `type(scope): subject`, at most 100 characters, with a lowercase imperative subject and no trailing period. Types: `feat`, `fix`, `perf`, `revert`, `docs`, `refactor`, `test`, `build`, `ci`, `style`, `chore`; never invent another. Scope: exactly one of `SCOPES` in `commitlint.config.mjs` (the Scopes table in CONTRIBUTING.md); never invent one, and if none fits, ask. The only thing allowed after the header is a blank line and `Co-authored-by: Name <email>` trailers. No body text. Put details in the PR description.
- **PR titles are valid commit headers**, scope included; squash merges use the title as the commit message.
- **PR bodies use the template's sections, in order, every one filled in**; write "n/a" rather than deleting one:

  ```sh
  gh pr create --title "type(scope): subject" --body-file <file>
  ```
- **Merges are squash or rebase only.** Never create merge commits.
- **Do not modify or delete existing AWS resources** that this stack does not own.
- **Never run `terraform apply` yourself.** Applies happen only through the Release Please `apply` job. Local plans are fine with read-only credentials. The same goes for the infra CLI: never run `jaws apply`, `publish`, `release`, `destroy` or `bot push`, `bot deploy`, `bot reconcile` (without `--dry-run`) or `bot secrets set` against real resources, and never run `task run`, `task terminate` or `task sweep` against AWS (`task list` is read-only and fine); its role check refuses non-CI credentials unless `JAWS_SKIP_ROLE_CHECK=1` is set, and you do not set it.
- **Do not add `ignore_changes`, `-lock=false`, or widen an IAM policy** to make a plan pass. Explain the diff in the PR instead.
- **Shared modules come from the Terraform Registry.** Every resource in this stack comes from a module of one of the Jaws module families, `Jaws-Platform/jaws-<family>/aws` (`ci`, `databricks`, `foundation`, `lichess-bot`, `monitoring`, `network`, `research`, `static-site`), pinned to an exact `version` in each module block. Bump every pin of a family together (`foundation/`, every stack under `stacks/`, `owner-access/`, `data-access/`, `monitoring/`, `billing-export/`, `release-infra/` and the family's entry in `src/jaws/product.yaml`; `tests/test_versions.py` checks), never switch a module back to a git or local source, and fix module bugs upstream in the family's repository, `Jaws-Platform/terraform-aws-jaws-<family>`, rather than working around them here.
- **Version literals are Release Please's.** `__version__` in `src/jaws/__init__.py` and the image tag in `.github/actions/jaws/action.yml` carry `# x-release-please-version` and are bumped by releases; never edit them by hand and never put one under `.github/workflows/`. The reusable workflows use the action from their own commit (`github.job_workflow_sha`); `container-release.yml` runs the CLI with `uv` from that same commit, because its build needs Docker on the runner.
- **Keep secrets out of the repo and out of variables.** Role ARNs are repository variables; the release bot credentials are repository secrets managed by the owner.

## Before opening a PR

```sh
terraform fmt -recursive
(cd foundation && terraform init -backend=false && terraform validate)
(cd stacks/site && terraform init -backend=false && terraform validate)
(cd stacks/bot && terraform init -backend=false && terraform validate)
(cd stacks/databricks-account && terraform init -backend=false && terraform validate)
(cd stacks/databricks-workspace && terraform init -backend=false && terraform validate)
(cd monitoring && terraform init -backend=false && terraform validate && terraform test)
(cd billing-export && terraform init -backend=false && terraform validate && terraform test)
(cd release-infra && terraform init -backend=false && terraform validate && terraform test)
tflint --init && tflint --recursive
npm ci && npm test && npm run test:commitlint
uv sync && uv run ruff format --check && uv run ruff check && uv run mypy && uv run pytest
scripts/test-stack-plans.sh   # plans stacks/bot and the databricks stacks against mock providers; touches no AWS
```

- **The infra CLI lives in `src/jaws/`** with tests in `tests/`. Python 3.13, `uv`, Typer, Pydantic. `config/` at the root is the tool configuration, YAML files read as one document in which each top-level section lives in one file (the file for each section is in README.md, "The tool configuration"). It holds the central guardrails: `tasks.limits` and `tasks.max_run_cost_usd` in `config/bots.yaml`, and each project's entry in `config/projects.yaml` with its instance types, task profiles and dataset retention (`foundation/bots.tf` reads them into the IAM allow-lists). `config/projects.yaml` is where every project is onboarded, under its GitHub owner with its `type` (`site`, `bot`, `research` or `databricks`), repository and repository ID; the foundation derives its projects, roles and buckets from it, so onboarding needs no change to `foundation/*.tf` or to a workflow. `config/aws.yaml` is the account registry; jaws builds only in its `primary` account. `stacks/site/` and `stacks/bot/` are the Terraform the CLI renders per site and per bot or research project, and `stacks/databricks-account/` and `stacks/databricks-workspace/` (`stacks/databricks-*`) the two stacks it renders per Databricks workspace project; `kinds/lichess_bot/` holds the bot image's Dockerfile and entrypoint. A project is a `site`, a `bot` (`container-image` + `lichess-bot`), a `research` project (`dataset`/`task-runner` only) or a `databricks` workspace project (`databricks-workspace`). Bot projects are documented in `docs/lichess-bot.md`, research projects in `docs/research-projects.md` and Databricks projects in `docs/databricks.md`; keep them current with any change to the commands, stack or image. A guardrail change is a config PR, a release, then a consumer pin bump (see `docs/research-projects.md`). The product's tests read `tests/fixtures/platform/`, a neutral copy of `config/`'s shape. Checks of the owner's own configuration live in `tests/platform/`. After changing the fixture, regenerate the foundation's test fixtures with `uv run python -m tests.test_foundation_fixtures` (a test checks).

- **`owner-access/` is the owner's stack.** It holds the owner's Identity Center admin access ([docs/owner-access.md](docs/owner-access.md)). Never `terraform plan` against real state or `terraform apply` there, never run `aws sso login`, and never give a CI role Identity Center permissions or a state prefix named `owner-access` (`tests/test_owner_access.py` checks). **`billing-export/` is the owner's too:** the organization's AWS billing export in the management account. The same rules hold, with no CI role, workflow or state prefix naming it (`tests/test_billing_export.py` checks). **`release-infra/` is the owner's too:** Jaws's release infrastructure, the ECR Public repository `jaws` and the role that pushes the image to it and prunes it, in the production account. The same rules hold: no CI role, workflow or state prefix names it, and its role's name stays outside `jaws-*` (`tests/test_release_infra.py` checks). IAM keeps the CI roles out of its state; the bucket policy exempts the foundation's apply role, so only a reviewed foundation change could open it. Its repository is a plain `aws_ecrpublic_repository`, since no module family has one.

## Things that need the owner

Anything in the "Owner hand-off" section of README.md: AWS admin credentials (the owner's `jwall-admin` Identity Center session), applying `owner-access/` and `release-infra/`, the ECR Public registry alias, GitHub secrets, the `prod` and `publish` environments, the `v*` tag ruleset, repository variables, repository settings, and Billing tags. Setting `JAWS_PUBLIC_IMAGE_KEEP` to `all` at v1 is the owner's too. List them in the PR instead of attempting them.
