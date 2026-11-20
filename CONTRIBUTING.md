# Contributing

This repo follows the jwall-engineering conventions. The short version: one-line Conventional Commits, every change through a pull request, squash or rebase merges only, and releases cut by Release Please.

## Workflow

1. Branch from `main`.
2. Make the change. Keep Terraform formatted (`terraform fmt`) and run the local checks below.
3. Open a PR with a typed template (see below). The PR title must be a valid Conventional Commit.
4. Review the `Terraform plan` comment CI posts on the PR. It is updated on every push; its alert says whether merging changes, destroys or leaves AWS alone, and the resource table under it lists each action.
5. Merge with **squash** or **rebase**. Merge commits are disabled and history stays linear.

Direct pushes to `main` are not allowed. The only exception was the initial scaffold commit during bootstrap.

## Commit messages: one line, nothing else

Every commit message is a single line:

```
type(scope)?: subject
```

- At most 100 characters.
- `type` is one of `feat`, `fix`, `docs`, `chore`, `refactor`, `ci`, `build`, `perf`, `style`, `test`, `revert`.
- Breaking changes are marked with `!`, for example `feat!: move state key`.
- The only content allowed after the header is a blank line followed by `Co-authored-by: Name <email>` trailers.
- No body text. Details belong in the PR description.

commitlint enforces this with `@commitlint/config-conventional` plus a local rule, `only-coauthor-trailers` (`tools/commitlint/only-coauthor-trailers.mjs`), which fails on any line after the header that is not blank or a `Co-authored-by` trailer. CI runs it over every commit in the PR range, so a rebase merge never lands a non-conforming commit on `main`.

### Why the PR title matters

Squash merges use the PR title as the commit message on `main`, and Release Please reads those messages to decide the next version and to write `CHANGELOG.md`. A `feat` bumps the minor version, a `fix` bumps the patch, and `!` bumps the major. CI lints the title with the same rules.

### Dependabot PRs

Dependabot cannot write one-line, lowercase commit messages, so its PRs skip the commit message check and the title check. Merge them with **squash** and a lowercase Conventional Commit subject, for example:

```sh
gh pr merge <n> --squash --subject "ci: bump actions/checkout from 6 to 7"
```

The CI plan comment still has to show no changes.

Pick the type with the release in mind. Release Please only cuts a release when a commit of a type that appears in `CHANGELOG.md` lands on `main`: `feat`, `fix`, `perf`, `revert` or `docs`. `chore`, `ci`, `build`, `refactor`, `style` and `test` are hidden from the changelog and never release on their own, and a `Release-As` footer cannot help because squash commits carry only the PR title. A bump that should ship, such as a Terraform provider in `foundation/` or anything that goes into the CLI image, is a `fix(deps):`. Bumps that only touch tooling stay `chore` or `ci` and ride along with the next release. If hidden-type bumps have piled up and you want them applied now, merge a PR of a visible type (a `docs:` change is enough) and Release Please will open the release PR for them.

## Pull request templates

Templates live in `.github/PULL_REQUEST_TEMPLATE/`, one per type: `feat.md`, `fix.md`, `docs.md`, `chore.md`, `refactor.md`, `ci.md`. Pick one with

```sh
gh pr create --template fix.md
```

or by appending `?template=fix.md` to the compare URL. Every template has Summary, Motivation and context, What changed, How it was verified, and a Checklist. `fix.md` adds Bug, Root cause, and Reproduction. Fill in every section.

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

Every module comes from one of the seven Jaws module families on the public Terraform Registry, `jaws-platform/jaws-<family>/aws`: [`ci`](https://registry.terraform.io/modules/jaws-platform/jaws-ci/aws), [`databricks`](https://registry.terraform.io/modules/jaws-platform/jaws-databricks/aws), [`foundation`](https://registry.terraform.io/modules/jaws-platform/jaws-foundation/aws), [`lichess-bot`](https://registry.terraform.io/modules/jaws-platform/jaws-lichess-bot/aws), [`network`](https://registry.terraform.io/modules/jaws-platform/jaws-network/aws), [`research`](https://registry.terraform.io/modules/jaws-platform/jaws-research/aws) and [`static-site`](https://registry.terraform.io/modules/jaws-platform/jaws-static-site/aws). Each family has its own version. To move to a new release of one, bump every `version` pin of that family together (all of `foundation/`, every stack under `stacks/`, `owner-access/` and `data-access/`) and its entry under `library.families` in `config.yaml` (`tests/test_versions.py` checks that every pin matches `config.yaml`), run `terraform init -upgrade` locally, and open a `chore(deps)` PR. Dependabot opens the same PR for the directories it watches; finish the other pins of that family in it. Review the family's changelog entry alongside the CI plan comment before merging. A change to a module's inputs or outputs belongs in the family's repository, `jaws-platform/terraform-aws-jaws-<family>`, not here.

## Releases

Release Please opens and maintains a release PR as changes land on `main`. Merging that PR:

1. tags a new version (starting at `v0.1.0`), updates `CHANGELOG.md`, and bumps the infra CLI version in `src/jaws/__init__.py` and the image tag in `.github/actions/jaws/action.yml` (the `x-release-please-version` annotations; keep them, and never add one under `.github/workflows/`, which the release bot cannot commit to);
2. triggers the `apply` job, which checks out the tag, assumes the apply role in the `prod` environment, and runs `terraform apply`;
3. triggers the `image` job, which builds the CLI image and pushes `jwall-engineering-sites:<tag>` to ECR. Site repositories then receive a Dependabot PR bumping their reusable workflow refs to the new tag.

Merging the release PR is the deliberate act that changes AWS. Merge it when the accumulated plan is what you want applied. Release PRs are authored by `jwallace145-release-bot[bot]` so that CI runs on them.

## Project layout

See the Layout table in [README.md](README.md).
