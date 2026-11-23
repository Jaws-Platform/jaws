# Contributing

This repo follows the owner's repository conventions. The short version: one-line Conventional Commits, every change through a pull request, squash or rebase merges only, and releases cut by Release Please.

## Workflow

1. Branch from `main`.
2. Make the change. Keep Terraform formatted (`terraform fmt`) and run the local checks below.
3. Open a PR from the template (see below) and fill in every section. The PR title must be a valid Conventional Commit.
4. Review the `Terraform plan` comment CI posts on the PR. It is updated on every push; its alert says whether merging changes, destroys or leaves AWS alone, and the resource table under it lists each action.
5. Merge with **squash** or **rebase**. Merge commits are disabled and history stays linear.

Direct pushes to `main` are not allowed. The only exception was the initial scaffold commit during bootstrap.

## Commit messages: one line, nothing else

Each commit message is a **single-line** Conventional Commit with a type and a scope:

```
type(scope): subject
```

- At most 100 characters, with an imperative, lowercase subject and no trailing period.
- Types: `feat`, `fix`, `perf`, `revert`, `docs`, `refactor`, `test`, `build`, `ci`, `style`, `chore`: the same set in every repository.
- The scope is required: exactly one of the scopes below. A change that spans two is two pull requests, or takes the scope it is mostly about.
- Breaking changes are marked with `!`, for example `feat(config)!: rename a project field`.
- The **only** content allowed after the header is a blank line followed by `Co-authored-by: Name <email>` trailers, in any letter case. No body text. Details belong in the pull request description.

commitlint enforces this: `@commitlint/config-conventional` plus three local rules in `tools/commitlint/`. `only-coauthor-trailers` fails on any line after the header that is not blank or a `Co-authored-by` trailer, `single-scope` fails on a list such as `feat(a,b)`, and `subject-lowercase` requires a lowercase subject except in Dependabot's fixed `chore(deps): Bump ...`. The fixtures in `tests/commitlint/` show accepted and rejected messages; CI checks them, and lints the pull request title through the same config. The standard behind it is the [repository conventions](https://github.com/jwallace145/repository-template/blob/main/repository-conventions.md).

### Scopes

Every commit names exactly one of this repository's scopes. They are `SCOPES` in `commitlint.config.mjs`; this table mirrors it, in the same order, and `npm run test:commitlint` fails if they drift. Adding, renaming or removing a scope goes through a pull request like any other change.

| Scope | Covers |
| --- | --- |
| `cli` | The `jaws` CLI in `src/jaws/`, its tests and its Docker image |
| `config` | `config/`: the accounts, the project registry and the central guardrails |
| `foundation` | The foundation stack in `foundation/` |
| `sites` | The site stack and the site workflows |
| `bots` | The bot stack, bot and research projects, and remote tasks |
| `databricks` | The Databricks account and workspace stacks |
| `access` | `owner-access/` and `data-access/` |
| `monitoring` | The `monitoring/` and `billing-export/` roots, `config/monitoring.yaml` and their docs |
| `datasets` | `datasets/`, the onboarded datasets |
| `workflows` | The reusable workflows and composite actions in `.github/` |
| `repo` | README, CONTRIBUTING, AGENTS, commitlint, the PR and issue templates, and repository tooling |
| `deps` | Dependency updates, mostly Dependabot's |
| `release` | Release Please's release pull requests and its config |

### Why the PR title matters

Squash merges use the PR title as the commit message on `main`, and Release Please reads those messages to decide the next version and to write `CHANGELOG.md`. CI lints the title through the same commitlint config as a commit, scope included. Release Please's own pull requests are titled `chore(release): release X.Y.Z`, and Dependabot's `chore(deps): Bump ...`; squash merge Dependabot's, which lands only the title on `main`.

## Pull request template

One template, `.github/pull_request_template.md`: Summary, Why, Changes, Verification and a checklist. `gh pr create` and the compare page both start from it. Fill in every section; write "n/a" rather than deleting one. For a fix, Why names the bug, its root cause and how to reproduce it.

## Issues

Open issues from the forms: **Bug**, **Feature** or **Task**. Blank issues are off.
## Local setup

Requirements: Terraform `>= 1.11`, [tflint](https://github.com/terraform-linters/tflint), Node.js `>= 22`, and [pre-commit](https://pre-commit.com).

```sh
npm ci
pre-commit install   # the pre-commit, commit-msg and pre-push hooks
cd foundation && terraform init -backend=false
tflint --init
cd .. && uv sync                         # the infra CLI and its dev tools
```

The `commit-msg` hook runs commitlint on every commit; the `pre-commit` hook runs `terraform fmt`, `terraform validate`, `tflint` and ruff. The `pre-push` hook runs the slow checks CI runs: `mypy`, `pytest`, `terraform test` in `foundation/`, `data-access/` and `owner-access/`, and `scripts/test-stack-plans.sh`. Each runs only when the push changes what it covers; about 3 to 4 minutes when a push touches everything. CI is the authoritative check; the hooks exist so mistakes are caught before a pull request exists. Skip them once with `git commit --no-verify` or `git push --no-verify` if you must, and expect CI to object. An existing checkout gets the pre-push hook by running `pre-commit install` again.

### Checks that must pass

| Check | Runs |
| --- | --- |
| `Commit messages` | commitlint over `base..head` and the rule's unit tests (`npm test`) |
| `PR title` | Conventional Commit check on the title |
| `Terraform fmt, validate, tflint` | `terraform fmt -check`, `terraform validate`, `tflint --recursive` |
| `Terraform plan` | plan through the OIDC plan role, posted as a PR comment |

A plan that touches the imported hosted zone with anything other than tags needs a clear explanation in the PR.

## Updating the shared modules

Every module comes from one of the eight Jaws module families on the public Terraform Registry, `Jaws-Platform/jaws-<family>/aws`: [`ci`](https://registry.terraform.io/modules/Jaws-Platform/jaws-ci/aws), [`databricks`](https://registry.terraform.io/modules/Jaws-Platform/jaws-databricks/aws), [`foundation`](https://registry.terraform.io/modules/Jaws-Platform/jaws-foundation/aws), [`lichess-bot`](https://registry.terraform.io/modules/Jaws-Platform/jaws-lichess-bot/aws), [`monitoring`](https://registry.terraform.io/modules/Jaws-Platform/jaws-monitoring/aws), [`network`](https://registry.terraform.io/modules/Jaws-Platform/jaws-network/aws), [`research`](https://registry.terraform.io/modules/Jaws-Platform/jaws-research/aws) and [`static-site`](https://registry.terraform.io/modules/Jaws-Platform/jaws-static-site/aws). Each family has its own version. To move to a new release of one, bump every `version` pin of that family together (all of `foundation/`, every stack under `stacks/`, `owner-access/`, `data-access/`, `monitoring/` and `billing-export/`) and its entry in `src/jaws/product.yaml` (`tests/test_versions.py` checks that every pin matches it), run `terraform init -upgrade` locally, and open a `chore(deps)` PR. Dependabot opens the same PR for the directories it watches; finish the other pins of that family in it. Review the family's changelog entry alongside the CI plan comment before merging. A change to a module's inputs or outputs belongs in the family's repository, `Jaws-Platform/terraform-aws-jaws-<family>`, not here.

## Releases

Release Please opens and maintains a release PR as changes land on `main`. Merging that PR:

1. tags a new version (starting at `v0.1.0`), updates `CHANGELOG.md`, and bumps the infra CLI version in `src/jaws/__init__.py` and the image tag in `.github/actions/jaws/action.yml` (the `x-release-please-version` annotations; keep them, and never add one under `.github/workflows/`, which the release bot cannot commit to);
2. triggers the `apply` job, which checks out the tag, assumes the apply role in the `prod` environment, and runs `terraform apply`;
3. triggers the `image` job, which builds the CLI image and pushes `jaws-cli:<tag>` to ECR. Site repositories then receive a Dependabot PR bumping their reusable workflow refs to the new tag.

Merging the release PR is the deliberate act that changes AWS. Merge it when the accumulated plan is what you want applied. Release PRs are authored by `jwallace145-release-bot[bot]` so that CI runs on them.

## Project layout

See the Layout table in [README.md](README.md).
