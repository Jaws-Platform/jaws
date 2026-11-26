# Jaws as a product, plan 05: workflows for the hub: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a hub run Jaws. The project-facing workflows take the hub image's repository and the platform's identity, and still run as today without them. Jaws ships the hub-facing workflows that check, plan, release, apply, sweep, roll back and upgrade a hub, with every run pinned to one image.

**Architecture:**
- **Two modes until cleanup.** With `platform-image`, `account-id` and `name-root`, a project-facing workflow:
  - derives every role ARN from the identity and the project;
  - resolves the hub image's `current` tag to one build at the job's start;
  - runs that build, either in the image or with `uv` from the pinned source, with the configuration copied out of the build.

  Without them it runs exactly as today, until plan 07 takes `config/` out of `jaws`.
- **Three new composite actions** carry the shared steps:
  - `platform-role` builds the role ARN from the identity;
  - `platform-image` gives a job one build, from the registry or from this run's artifact, cached per repository;
  - `platform-build` builds a hub's `Dockerfile`, with labels naming its Jaws base and its hub commit.

  The `jaws` action gains `image` and `github-token`.
- **The CLI runs the platform's own stacks inside the image.**
  - `jaws platform plan|apply <stack>` writes each backend from `state` (today's three keys), gives Terraform the configuration's paths and the Databricks credential, and writes the comment.
  - `jaws platform check` fails a hub whose pins or identity disagree.
  - `jaws config projects` lists the matrices.
  - The comment footer names the hub commit.
- **Seven `platform-*.yml` reusable workflows** are a hub's:
  - `ci`: a candidate image passed between jobs, never pushed, and every stack and project planned, sites included;
  - `release`: build `sha-<commit>`, apply the foundation and monitoring, then move `current`, then `live`;
  - `rollback`, `bot-apply`, `databricks-apply` and `sweep`;
  - `upgrade`: one PR bumps every pin.
- **Upstream,** jaws-lichess-bot's `ecr-repository` lets named tags move and keeps the image each one names. The foundation's hub image then keeps ten builds and lets only `current` move.

**Tech Stack:**
- GitHub Actions: reusable workflows, composite actions, `actions/cache`, artifacts, OIDC.
- Docker and BuildKit (`docker/build-push-action@v7`); the AWS CLI's `ecr` commands; `gh`, yq and jq.
- Python 3.13, uv, Typer, Pydantic v2, PyYAML, pytest.
- Terraform 1.14.7 (`terraform test` with mock providers); the AWS provider `>= 6.73`, for `image_tag_mutability_exclusion_filter`.

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md):
- 6.3, the hub image's tags;
- 6.4 and 6.5;
- 6.6, the trust these workflows rely on;
- 6.7: the check names, the comments App and the footer.

Roadmap: [row 05](2026-11-23-hub-split-00-roadmap.md). This plan builds on plans 02 (white-label), 03 (platform stacks) and 04 (images), which merge first.

**Where the work happens:**
- **Task 1** is in `Jaws-Platform/terraform-aws-jaws-lichess-bot` (`~/Projects/Jaws-Platform/terraform-aws-jaws-lichess-bot`), on a branch from its `main`, with its own PR. Task 2 waits for its release, 0.2.0.
- **Tasks 2–16** are in `jaws`, on `hub-split/05-workflows`, the branch of the draft PR that holds this plan. The work lands on that PR.
  - Rebase the branch onto `main` once plans 02 and 04 have merged. Plan 03 merged as #316.
  - Tasks 3–8 and 15 need nothing from Tasks 1–2, and can run while Task 1 is in review.

## Global Constraints

- **The repository rules (`AGENTS.md` in each repository):**
  - never push to `main`: one branch, one PR;
  - each commit is one line, `type(scope): subject`, at most 100 characters, with a lowercase subject and no trailing period;
  - only `Co-authored-by:` trailers may follow, after a blank line;
  - the PR title is a valid commit header, and the PR body fills every template section.
- **Scopes.**
  - In `jaws`, from `SCOPES`: `cli` (Tasks 3–7), `deps` and `foundation` (Task 2), `workflows` (Tasks 8 and 11–14), `sites` (Task 9), `bots` (Task 10), `databricks` (Task 15), `repo` (Task 16).
  - In jaws-lichess-bot, the module's name: `ecr-repository`.
- **Never touch real infrastructure.**
  - Never run `terraform apply`, a plan against real state, `jaws apply|publish|release|destroy`, `jaws platform plan|apply` with AWS credentials, `docker push`, an `aws ecr` command, or a `gh` command that writes anywhere but this PR.
  - Run only these: `terraform test` with mock providers, `terraform validate`, `tflint`, `scripts/test-stack-plans.sh`, pytest with the repository's fakes, and local `docker build` and `docker run --network none`.
- **Nothing in AWS changes when this plan merges.**
  - The one Terraform change is the hub image repository's inputs (Task 2). Nothing creates that repository before plan 07's enabling release, because the owner's `config/platform.yaml` names no hub.
  - The jaws-lichess-bot bump changes no resource where `mutable_tags` is empty.
  - CI's `Terraform plan` and `Bot plan` comments must say merging leaves AWS alone.
- **Old pins keep working.** The spec's anti-goal, verbatim (2): "A window where a project's CI is broken. Old pins keep working until that project switches."
  - Every project-facing workflow keeps today's steps when `platform-image` is empty (ruling 1).
  - The composite action keeps `IMAGE_TAG` and its `x-release-please-version` annotation.
- **The spec's rules, verbatim.**
  - 6.3: "A run resolves `current` to a digest once, at its start, and uses that digest for every step, so a merge mid-run can't mix two configurations. The comment footer names the digest's hub commit."
  - 6.4: "They take the hub image's repository and the platform's identity as inputs: the account ID and the name root, which a run needs to build its role ARN before it can pull anything." "They stop reading `config/` from a Jaws checkout." "Releases stay gated, as today." "Projects call the hub at `@live`, not `@main`." "The data-access sweep and the by-hand applies use `current`." "Comments fall back to `github-actions` when no App is configured, as today."
- **jaws's own workflows don't change.**
  - `ci.yml`, `release-please.yml`, `data-access.yml`, `bot-apply.yml` and `databricks-apply.yml` keep planning and applying from `jaws` until takeover. Plan 07 switches them off as the hub's start, so exactly one sweeper runs.
  - The one change to them is Task 15's: the steps that source `scripts/databricks-credentials.sh` pass it the name root (plan 02's pre-flight item G12).
  - No `jaws` workflow calls a `platform-*.yml`.
- **The owner's folders.** No workflow, action or CLI command names `owner-access`, `billing-export` or `release-infra`. `tests/test_owner_access.py`, `tests/test_billing_export.py` and `tests/test_release_infra.py` check the workflows.
- **The region** stays `us-east-1`, a product constant (spec 6.7). The ECR registry is `<account-id>.dkr.ecr.us-east-1.amazonaws.com`.
- **Owner values in files.**
  - Never write one outside `config/` and `tests/platform/`.
  - Only `tests/platform/` reads `PLATFORM_CONFIG_DIR`, and a failure there names the field, never the value.
  - New tests use these neutral values:
    - the fixture's identity: account `222222222222`, name root `jaws`, state bucket `jaws-terraform-state-222222222222`;
    - for workflow steps: account `123456789012`;
    - the hub `Example-Hub/platform`, owner ID `10000099`, repository ID `20000099`, and its image `jaws-platform`;
    - the hub commit `0123456789abcdef0123456789abcdef01234567`;
    - the public image `public.ecr.aws/example-alias/jaws`;
    - digests `sha256:` followed by 64 of one hex digit.
- **The privacy hook.** If a hook refuses a command because a file holds the owner's email, stop and ask the owner to run it (they can, with `!`). Never work around the hook. `tests/conftest.py` is imported, never edited.
- **Off limits:** `owner-access/`, `billing-export/` and `release-infra/`.
- **Releases land between 08:00 and 24:00 MT.** The monitoring node is stopped from 00:00 to 08:00, and a release in that window replaces it. That holds for this plan's releases and, later, the hub's.
- **Spending.**
  - Merging pays for nothing.
  - The hub's runs pull each build once per repository (ruling 4), and its candidates never reach ECR (ruling 5).
  - The hub image keeps at most ten builds (ruling 6).
- **Before each PR:**
  - in jaws-lichess-bot, `scripts/check.sh`;
  - in `jaws`, the `AGENTS.md` checklist (Task 16), plus `(cd foundation && terraform test)`.

## Review Focus

1. **`current` moves during a run.** A hub release lands between a job's `validate` and `plan`, or between a release's apply and its move. Expected: every step of the job, and every job of the run, runs the build resolved at its start. Tests:
   - Task 8, `test_the_build_is_resolved_once_and_run_by_its_id`;
   - Task 9, `test_a_site_job_resolves_the_platform_image_once`;
   - Task 12, `test_the_applies_run_the_release_s_build_by_digest`.
2. **A project still on Jaws's own pin, bumped by Dependabot.** `@v0.76.0` becomes this release, with no platform inputs. Expected: exactly today's steps, with `jaws-cli:<tag>`, the role inputs and `config/` from the checkout. Tests:
   - Task 9, `test_without_a_platform_image_a_site_job_runs_as_today`;
   - Task 10, `test_without_a_platform_image_a_task_runs_as_today`.
3. **Half an identity, or a role in another account.** Examples: `platform-image` without `account-id`, the account `12345678901`, or an override role in another account. Expected:
   - the job stops before any AWS call, naming the input;
   - credentials in another account stop before the pull.

   Task 8, `test_half_an_identity_stops_the_job_before_aws` and `test_a_role_in_another_account_stops_the_pull`.
4. **The sweep in an image without its datasets.** Expected: nothing is rendered or applied, and the message names the registry's path. Task 5, `test_render_refuses_a_registry_without_its_readme`.
5. **A hub whose pins or identity drift.** Examples: one caller's pin bumped by hand, a `Dockerfile` digest of another release, an identity input written as an expression. Expected: the hub's CI fails the PR, naming the file and both values. Task 7:
   - `test_a_pin_that_disagrees_fails_the_check`;
   - `test_an_image_of_another_release_fails_the_check`;
   - `test_an_identity_that_disagrees_fails_the_check`.

## Rulings

Calls this plan makes where the spec leaves them open. Those marked **to confirm** are the owner's decisions, and the PR lists them.

1. **Two modes until cleanup.**
   - A project-facing workflow runs the hub's way when `platform-image` is set, and today's way when it isn't. Old pins never change, and a Dependabot bump of one must still run.
   - `account-id` or `name-root` without `platform-image` is half an identity, and stops the job.
   - Plan 07 removes today's mode when `config/` leaves `jaws`.
2. **The hub's way derives every role ARN:** `arn:aws:iam::<account-id>:role/<name-root>-<project>-ci-<role>`. A site's project comes from its `jaws.yaml`.
   - The role inputs become optional overrides, which must be in `account-id`.
   - A switched project then needs no role variable (spec 6.11), and plan 07's switch PRs delete them.
3. **One build per run.**
   - The first job resolves `current`, or a release's digest, to a manifest digest and an image ID, with `aws ecr batch-get-image`. `ecr/pull` grants that call, but not `DescribeImages`.
   - Every later step runs the image ID, and later jobs take the digest from job outputs.
4. **Each repository pulls a build once.**
   - `platform-image` keeps `docker save` of the build in the Actions cache, keyed by its image ID, and checks the loaded image's ID.
   - Without the cache, the hub's 15-minute sweep would pull about 283 MiB 96 times a day. That is about 875 GB a month from private ECR to GitHub's runners: about $70 at $0.09 per GB past the free 100 GB.
   - With it, the sweep pulls once per hub release. The cache is free, up to 10 GB a repository.
5. **The candidate is passed between jobs, never pushed** (spec 8). An ECR push grant can't be limited by tag, so a pull request role that could push a candidate could also move `current`.
6. **The hub image's tags** (spec 6.3; plan 03's ruling 6 hands them to this plan):
   - each release build is tagged `sha-<hub commit>`, and that tag never moves;
   - `current` is the one tag that moves, by an immutability exclusion added upstream in Task 1;
   - the lifecycle keeps the newest ten `sha-` builds, never expires the build `current` names, and expires untagged images after 7 days.

   Ten builds are at most about 2.8 GB, about $0.28 a month, and less where builds share their Jaws base. **To confirm:** ten, so a rollback reaches the last ten hub releases.
7. **`current` and `live` move after the foundation's apply, without waiting for monitoring's.**
   - The spec gives the reason for the timing: "at the moment the foundation has created any roles the new configuration names".
   - A failed monitoring apply holds nothing else back, as it holds back nothing of `jaws`'s release today.
   - `current` moves first, then `live`. In the seconds between, a project runs the new build with the old workflow files, never the reverse.

   **To confirm:** the spec lists monitoring's apply before the move.
8. **`live` is moved by the hub's release App,** through the Git refs API. A release only fast-forwards it, and the first release creates it. Only that App may update it, under a ruleset (plan 06).
9. **A rollback moves `current` and `live` together,** to a kept build and its release commit, which must be on `main`. It applies nothing.
   - The spec says rolling back is "pointing `current` at an earlier build".
   - Moving `live` too keeps the workflow files and the image at one Jaws release (spec 6.4: "the hub's workflow files and its image change together").

   **To confirm.**
10. **The identity and the check prefix are literals in the hub's callers, checked by its CI.**
    - A project's run can read neither the hub's variables (a called workflow's `vars` are the calling repository's) nor its configuration before it has a role.
    - `jaws platform check` compares each literal with what `jaws config env` reports inside the candidate image.
    - This is plan 02's "the hub's callers fill the input from `jaws config env --brand`, run in the hub image", made static.

    **To confirm.**
11. **One version, two pins** (spec 6.4). The same check fails a PR when any of these disagree:
    - the workflow pins;
    - the `Dockerfile`'s tag;
    - the candidate's own Jaws version.

    It also fails a `Dockerfile` that pins no digest.
12. **The upgrade PR.**
    - It reads the newest release from ECR Public's tags, anonymously. A GitHub release whose image isn't published yet is never picked.
    - It keeps one PR, on one branch, `jaws-upgrade`.
    - Changing `.github/workflows/` needs an App token with *Workflows: write*. `GITHUB_TOKEN` can't change those files, and its PRs run no CI.
    - Recommended: a dedicated App, **JWall Engineering Upgrades** (`jwall-engineering-upgrades`), installed only on `platform`. The alternative is adding Workflows to the release App, which is installed on every repository. **To confirm.**
    - Plan 06 schedules it hourly. ECR Public keeps ten versions, about two days of releases (plan 04, "For plan 06").
13. **The platform's own stacks run in the image, through the CLI** (plan 04's ruling 3).
    - `jaws platform plan|apply` replaces two scripts for a hub, since the image holds neither: `scripts/databricks-credentials.sh` and `scripts/data-access-sweep.sh`. They stay for `jaws`'s own workflows until takeover.
    - The backends come from `state` and give today's keys, with the foundation under `infra`. So no state moves (spec 6.10).
    - A hub's run never sources the credential script. The CLI reads `databricks.secret_parameter`, which plan 02 derives from the name root when it's unset, with `metastore_name` and `audit_bucket`. No hub workflow spells a name the root derives, such as `/<name_root>/databricks/` or `/<name_root>/monitoring/` (Task 8's guard).
    - `jaws`'s own workflows still source the script until takeover. They pass it the name root they already hold, rather than have it read `.context.name_root` with yq, which `tests/test_workflow_roles.py` forbids a workflow step (Task 15; plan 02's G12).
14. **Bot, research and Databricks plans and applies run in the image,** the Databricks stacks included (plan 04).
    - `remote-task` keeps `uv` from the pinned source, for the task's signal handling. `container-release` keeps it because it needs Docker on the runner.
    - Both take the configuration and datasets copied out of the build: spec 6.4's first option.
15. **`access render` refuses a registry without its README** (plan 03's ruling 10). A sweep applies what it plans, so an image without its datasets would revoke every grant.
16. **The comments App.**
    - The interface stays `app-client-id` and the secret `app-private-key`, now on every workflow that posts, with the fallback to `github-actions` (spec 6.4).
    - The hub's callers pass the App's client ID as a literal, since it isn't secret, and the key from the caller's own secret. So each onboarded owner holds only the key.

## Owner hand-offs

Merging this plan changes nothing in AWS. The agent does none of these.

1. **Now, before this plan's releases: the old pins' image.** Every project's pin, `@v0.76.0`, pulls `jaws-cli:v0.76.0` in `site-plan`, `site-preview` and `site-deploy`.
   - Seven releases have followed it (v0.77.0 to v0.80.1, CHANGELOG.md), and `jaws-cli` keeps only the newest `ecr.keep_release_images` release images.
   - At about four releases a day, it expires before plan 07's switches, and those workflows then fail to pull.
   - Before then, do one of these: raise `ecr.keep_release_images` in `config/tool.yaml`, a config change still allowed before the freeze; or merge the projects' Dependabot bumps to a recent tag.
2. **Before Task 2:** merge Task 1's PR, then its Release Please PR, so that jaws-lichess-bot 0.2.0 is on the Registry.
3. **For the hub.** Plan 06 carries these out with the owner; nothing in this plan needs them.
   - **The comments App:** create **JWall Engineering Comments** (`jwall-engineering-comments`), owned by `JWall-Engineering`.
     - It has no webhook, only *Pull requests: read and write*, and the avatar from `jwall-engineering-branding`.
     - Install it on `platform` and on every onboarded owner: `jwallace145`, `Braveheart-Chess`, `Pi-Mathematical-Reasoning`, `Prog-Strength`.
     - Store its key where each owner's callers can read it: an organization secret in an organization, and repository secrets under `jwallace145`.
     - Give plan 06 its client ID, which the hub's callers spell.
   - **The upgrade App,** if ruling 12 is confirmed: **JWall Engineering Upgrades** (`jwall-engineering-upgrades`).
     - Its permissions are *Contents*, *Pull requests* and *Workflows*, each read and write.
     - Install it on `platform` only, with its client ID and key as organization secrets.
   - **The `live` ruleset on `platform`:** restrict updates and deletions, and block force pushes, with **JWall Engineering Releases** as the only bypass actor. A rollback force-moves `live` with that App.
   - **The `prod` environment on `platform`,** with deployments from `main` only. Spec 7 lists it with the `main` ruleset.
   - **Repository variables: none.** The hub's callers spell their identity, and a switched project needs no role variable (ruling 2).
   - **Secrets the hub's callers read:** the existing `RELEASE_BOT_CLIENT_ID` and `RELEASE_BOT_PRIVATE_KEY`, the comments App's key, and the upgrade App's client ID and key.

## For plans 06 and 07

- **The hub's callers.** Each is a few lines calling `Jaws-Platform/jaws/.github/workflows/<name>.yml@vX.Y.Z` (`docs/platform-workflows.md`, written by Tasks 8–14).
  - Project-facing callers: `site-plan`, `site-preview`, `site-deploy`, `site-release-please`, `remote-task` and `container-release`.
  - The hub's own: `ci`, `release`, `rollback`, `bot-apply`, `databricks-apply`, `sweep` and `upgrade`.
  - Each caller that runs the image spells `platform-image`, `account-id` and `name-root`. The site callers also spell `check-prefix`. Ruling 10 covers why.
  - Each caller job grants the permissions the next level needs: `contents: read`, `id-token: write`, and `pull-requests: write` where it comments (spec 6.4).
- **Check names gain a level.** A project calling the hub calling Jaws reports `<project job> / <hub job> / <prefix> plan`. Each switch PR (plan 07) updates that project's required checks.
- **The hub's required checks:** `Platform check`, `Terraform plan`, `Monitoring plan` and `Data access plan`.
- **The upgrade runs hourly** (ruling 12). That is plan 04's first remedy for the retention risk.
- **Cleanup (plan 07):**
  - remove today's mode from the project-facing workflows, and the `jaws` action's `config/` steps;
  - retire `scripts/projects.sh`, `scripts/databricks-credentials.sh` and `scripts/data-access-sweep.sh` with the workflows that use them.

---

### Task 1: jaws-lichess-bot: named tags that move, and the image each one names is kept

In `Jaws-Platform/terraform-aws-jaws-lichess-bot`, branch `mutable-tags`.

**Files:**
- Modify: `modules/ecr-repository/variables.tf` (add after `release_tag_prefixes`), `modules/ecr-repository/main.tf` (the repository's mutability and the lifecycle rules), `modules/ecr-repository/versions.tf`
- Modify: `modules/ecr-repository/README.md`: a bullet in the list, and the regenerated inputs table
- Test: `modules/ecr-repository/tests/ecr_repository.tftest.hcl`

**Interfaces:**
- Produces `variable "mutable_tags"`.
  - Type `list(string)`, default `[]`.
  - Description: "Tags that may move from image to image, such as `current` for the build that is live. Every other tag stays immutable, and the lifecycle never expires the image a mutable tag names."
  - Validations, each with its own message:
    - at most 5, ECR's limit on exclusion filters;
    - each matches `^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$`, so a tag and never a wildcard;
    - none starts with one of `release_tag_prefixes`.
- With `mutable_tags = []`, the repository and its lifecycle policy JSON are exactly 0.1.4's.
- With tags:
  - `image_tag_mutability = "IMMUTABLE_WITH_EXCLUSION"`, with one `image_tag_mutability_exclusion_filter { filter = <tag>, filter_type = "WILDCARD" }` per tag;
  - the lifecycle starts with one rule per mutable tag, at priorities 1 to k: `description = "Keep the image tagged <tag>"`, `selection = { tagStatus = "tagged", tagPatternList = [<tag>], countType = "imageCountMoreThan", countNumber = 1 }`, `action = { type = "expire" }`. A tag sits on one image, so that rule expires nothing, and no lower rule may expire an image it matches;
  - today's two rules follow, at k + 1 and k + 2.
- `versions.tf`: aws `>= 6.73, < 7.0`. 6.73.0, which every `jaws` lock file resolves, has the exclusion filter.

- [ ] **Step 1: Write the failing tests**

```hcl
run "a_mutable_tag_moves_and_its_image_is_kept" {
  command = plan

  variables {
    mutable_tags         = ["current"]
    release_tag_prefixes = ["sha-"]
    keep_release_images  = 10
  }

  assert {
    condition     = aws_ecr_repository.this.image_tag_mutability == "IMMUTABLE_WITH_EXCLUSION" && length(aws_ecr_repository.this.image_tag_mutability_exclusion_filter) == 1 && aws_ecr_repository.this.image_tag_mutability_exclusion_filter[0].filter == "current"
    error_message = "current may move, and every other tag stays where it was pushed"
  }

  assert {
    condition = jsonencode([for r in jsondecode(aws_ecr_lifecycle_policy.this.policy).rules : [r.rulePriority, r.selection]]) == jsonencode([
      [1, { tagStatus = "tagged", tagPatternList = ["current"], countType = "imageCountMoreThan", countNumber = 1 }],
      [2, { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }],
      [3, { tagStatus = "tagged", tagPrefixList = ["sha-"], countType = "imageCountMoreThan", countNumber = 10 }],
    ])
    error_message = "the image current names comes first, so no later rule can expire it"
  }
}
```

Then add these runs:
- `no_mutable_tags_keeps_the_policy_of_0_1_4`: the defaults give `IMMUTABLE`, no exclusion filter, and exactly two rules;
- `rejects_a_mutable_tag_that_is_a_release_tag`: `["v-latest"]`, with `expect_failures = [var.mutable_tags]`;
- `rejects_a_wildcard_mutable_tag`: `["cur*"]`, expecting the same failure.

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/check.sh modules/ecr-repository`
Expected: FAIL with `An argument named "mutable_tags" is not expected here`.

- [ ] **Step 3: Implement the variable, the filters and the rules.** Build the rule list with `concat`, and number the rules by their index. Add a bullet to the README: tags in `mutable_tags` may move, and the lifecycle keeps the image each one names. Regenerate the table with `terraform-docs --config .terraform-docs.yml modules/ecr-repository`.

- [ ] **Step 4: Run them and watch them pass**

Run: `scripts/check.sh`
Expected: PASS. Every existing run passes unchanged, which shows that a repository without mutable tags keeps its policy.

- [ ] **Step 5: Commit and open the PR**

```bash
git commit -m "feat(ecr-repository): let named tags move, and keep the image each one names"
gh pr create --template feat.md --title "feat(ecr-repository): let named tags move, and keep the image each one names"
```

The owner then merges it and the Release Please PR, which gives 0.2.0: the repository bumps the minor for a `feat` before 1.0.

---

### Task 2: the hub image keeps ten builds and lets only `current` move

Wait until `curl -s https://registry.terraform.io/v1/modules/Jaws-Platform/jaws-lichess-bot/aws/versions | jq -r '.modules[0].versions[].version'` lists `0.2.0`.

**Files:**
- Modify: the four `Jaws-Platform/jaws-lichess-bot/aws` pins: `foundation/ecr.tf` (`sites_image`, `hub_image`) and `stacks/bot/main.tf` (two)
- Modify: `src/jaws/product.yaml` (the family's entry), `foundation/ecr.tf` (`module "hub_image"`), `README.md` (the Layout table's `ecr.tf` row)
- Test: `tests/test_platform_stacks.py`, `tests/test_versions.py` (unchanged; it checks the pins)

**Interfaces:**
- Consumes: `mutable_tags` (Task 1).
- Produces: the hub image's tags, for Tasks 8, 12 and 13.
  - `sha-<40-hex hub commit>`: one per release build, never moved. The newest ten are kept.
  - `current`: moves to the build that is live, which never expires.

- [ ] **Step 1: Write the failing test** in `tests/test_platform_stacks.py`

```python
def test_the_hub_image_keeps_ten_builds_and_lets_only_current_move() -> None:
    """Each release pushes sha-<commit>; current names the live build (spec 6.3)."""
    block = _module_block(REPO_ROOT / "foundation" / "ecr.tf", "hub_image")
    assert 'mutable_tags         = ["current"]' in block
    assert 'release_tag_prefixes = ["sha-"]' in block
    assert "keep_release_images  = 10" in block
```

`_module_block(path: Path, name: str) -> str` returns the text from `module "<name>" {` to its closing brace at column 0.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_platform_stacks.py -v`
Expected: FAIL. The block has none of the three lines.

- [ ] **Step 3: Bump the family, then set the inputs**
  - Set the four pins and the `src/jaws/product.yaml` entry to `0.2.0`.
  - Install the modules without touching the providers: don't pass `-upgrade`. 6.73.0 already meets the new floor.
  - In `module "hub_image"`, set the three inputs. Their comment: each release build is `sha-<commit>`, `current` is the live one (it moves, and the lifecycle never expires it), and ten builds are kept for rollback.
  - The README's `ecr.tf` row gains "the hub image's builds (`sha-<commit>`, the newest ten kept) and `current`".

- [ ] **Step 4: Run them and watch them pass**

Run: `(cd foundation && terraform init -backend=false && terraform validate && terraform test) && (cd stacks/bot && terraform init -backend=false && terraform validate) && git diff --exit-code -- '*.terraform.lock.hcl' && scripts/test-stack-plans.sh && uv run pytest tests/test_platform_stacks.py tests/test_versions.py -q`
Expected: PASS. No lock file changes.

- [ ] **Step 5: Commit.** If Dependabot opened its own bump for `foundation/`, close it: it misses `stacks/bot/` and `src/jaws/product.yaml`.

```bash
git add foundation/ecr.tf stacks/bot/main.tf src/jaws/product.yaml
git commit -m "chore(deps): bump jaws-lichess-bot to 0.2.0 in the stacks and the release pins"
git add foundation/ecr.tf tests/test_platform_stacks.py README.md
git commit -m "feat(foundation): keep ten hub image builds and let only current move"
```

---

### Task 3: `jaws config projects` and `jaws config env --platform`

**Files:**
- Modify: `src/jaws/cli.py`: `config_env`, and a new `config_projects` beside it
- Create: `tests/test_config_projects.py`
- Modify: `tests/test_one_account.py`

**Interfaces:**
- Produces `jaws config projects TYPE...`.
  - `TYPE` is one of `site`, `bot`, `research` and `databricks`, at least once.
  - It prints one line: a compact JSON array of `{"project", "repository", "type"}`, in the registry's order (`settings.projects`, and `settings.repository(key)`). That is `scripts/projects.sh`'s output, without yq.
  - Any other type exits 2 with "unknown project type: {type} (site, bot, research or databricks)".
- Produces `jaws config env --platform`.
  - It appends `platform_image=<platform.hub.image>` and `platform_repository=<platform.hub.repository>`.
  - Without `platform.hub` it exits 2 with "platform.hub is not set (config/platform.yaml): a hub's workflows push and run its image".

- [ ] **Step 1: Write the failing tests**

```python
#: A hub in the fixture's configuration: neutral values no other file holds.
HUB = {"repository": "Example-Hub/platform", "image": "jaws-platform"}
HUB_REPOSITORY = {
    "repository": "Example-Hub/platform",
    "owner_id": "10000099",
    "repository_id": "20000099",
}


@needs_yq
@pytest.mark.parametrize("types", [["bot", "research"], ["databricks"], ["site"]])
def test_config_projects_lists_what_scripts_projects_sh_lists(types: list[str]) -> None:
    script = subprocess.run(
        [str(REPO_ROOT / "scripts" / "projects.sh"), "--config", str(CONFIG_DIR), *types],
        capture_output=True,
        text=True,
        check=True,
    )
    result = runner.invoke(cli.app, ["--config", str(CONFIG_DIR), "config", "projects", *types])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(script.stdout)


def test_config_projects_refuses_an_unknown_type() -> None:
    result = runner.invoke(cli.app, ["--config", str(CONFIG_DIR), "config", "projects", "app"])
    assert result.exit_code == 2
    assert "unknown project type: app" in result.output
```

`needs_yq` comes from `tests/test_databricks_workflows.py`. In `tests/test_one_account.py`, add:
- `test_config_env_prints_the_hub_s_image_and_repository`: `fixture_config()` with `HUB_REPOSITORY` appended to `platform.repositories` and `platform.hub = HUB`. The last two lines are `platform_image=jaws-platform` and `platform_repository=Example-Hub/platform`.
- `test_config_env_platform_needs_a_hub`: without a hub, exit 2, and the output names `platform.hub`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_config_projects.py tests/test_one_account.py -v`
Expected: FAIL. There's no command `projects` and no option `--platform`.

- [ ] **Step 3: Implement both.** The `--platform` help says the hub's image repository and its repository, for the hub's workflows. `config projects` prints with `json.dumps(..., separators=(",", ":"))`.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_config_projects.py tests/test_one_account.py -q && uv run mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jaws/cli.py tests/test_config_projects.py tests/test_one_account.py
git commit -m "feat(cli): list the projects and name the hub's image for the hub's workflows"
```

---

### Task 4: `jaws platform plan|apply`: the foundation and monitoring, inside the image

**Files:**
- Create: `src/jaws/platform.py`
- Modify: `src/jaws/cli.py`: a `platform_app` Typer, added as `platform`
- Create: `tests/test_platform_cli.py`, `tests/platform/test_platform_backends.py`
- Modify: `tests/workflow_steps.py` (`hcl_text_values`)

**Interfaces:**
- Consumes:
  - `stack.Terraform`, `stack.default_stack_dir` and `stack.default_plugin_dir`;
  - `_load_databricks_secret` and `databricks.redacting` (`src/jaws/cli.py`, `src/jaws/databricks.py`);
  - `databricks_auth.terraform_env`, `report.plan_comment` and `PLAN_COMMENT_MAX_BYTES`;
  - `access.infra_root()`, and `aws.check_role`.
- Produces, in `jaws.platform`:
  - `@dataclass(frozen=True) class PlatformStack`, with `name: str`, `state_project: str` and `databricks: bool`.
  - `PLATFORM_STACKS: Mapping[str, PlatformStack]`:
    - `foundation`: `infra`, with Databricks;
    - `monitoring`: `monitoring`, without;
    - `data-access`: `data-access`, with Databricks.
  - `def platform_stack(name: str) -> PlatformStack`. It raises `ConfigError` with "{name} is not one of the platform's stacks: foundation, monitoring, data-access".
  - `def platform_backend(settings: Settings, stack: PlatformStack) -> str`: `backend/prod.hcl`'s five lines, laid out the same way:
    - `bucket` is `state.bucket`;
    - `key` is `settings.state_key(stack.state_project, "prod")`;
    - `region` is `state.region`;
    - `use_lockfile = true` and `encrypt = true`.
  - `def platform_role(settings: Settings, stack: PlatformStack, role: Literal["plan", "apply"]) -> str`: `<name_root>-<state_project>-ci-<role>`.
  - `def stack_variables(stack: PlatformStack, config_path: Path, datasets_path: Path) -> dict[str, str]`. The foundation gets `TF_VAR_config_path` and `TF_VAR_datasets_path` (plan 03's variables), monitoring gets `TF_VAR_config_path`, and data access gets none.
- Produces `jaws platform plan STACK` and `jaws platform apply STACK`. Both:
  - check the role with `platform_role`;
  - work in a copy of `default_stack_dir(stack.name)`, which is the image's `/opt/jaws/stacks/<name>`;
  - write `backend.hcl`, then init against the plugin mirror;
  - give Terraform `stack_variables(...)`, with the CLI's configuration path, made absolute, and `infra_root() / "datasets"`;
  - give Terraform the Databricks credential, but only Terraform, when `stack.databricks` and `databricks.enabled`. The secret is read from `settings.databricks.secret_parameter`, which plan 02 derives from the name root when the platform leaves it out. No script is sourced, and nothing reads `.context.name_root`.

  `plan` then:
  - plans with `-detailed-exitcode` and writes `.jaws/plan.txt` and `.jaws/plan-comment.md`, whose subject is `<name_root>/<stack>`;
  - writes the outputs `result` and `changes`;
  - exits 0 for no changes or for changes, and 1 for a failed plan, after writing the comment.

  `apply` plans as `plan` does, with the apply role. Then it applies the saved plan only when the plan has changes: the sweep's rule, now every platform stack's. It writes `result=no-changes|applied` and a step summary, and exits 1 for a failed plan or apply.
- Implementation hint: subclass `stack.Terraform` for its working copy, init, plan and apply. Take a `PlatformStack` instead of a `Target`, and override `backend()`. The tfvars are `{}`, and Task 5 renders data access's.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_cli.py`

Use the `fake_terraform` fixture, and `JAWS_STACKS_ROOT` pointing at a temporary directory that holds `foundation/main.tf` and `monitoring/main.tf`. The tests take on a role the way `tests/test_cli.py`'s `_as_role` does.

```python
@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("foundation", "project=infra/env=prod/infra-prod.tfstate"),
        ("monitoring", "project=monitoring/env=prod/monitoring-prod.tfstate"),
        ("data-access", "project=data-access/env=prod/data-access-prod.tfstate"),
    ],
)
def test_the_backend_is_today_s_key_in_the_state_bucket(name: str, key: str) -> None:
    settings = load_settings(CONFIG_DIR, environ={})
    assert platform_backend(settings, platform_stack(name)).splitlines() == [
        'bucket       = "jaws-terraform-state-222222222222"',
        f'key          = "{key}"',
        'region       = "us-east-1"',
        "use_lockfile = true",
        "encrypt      = true",
    ]


@pytest.mark.parametrize("name", ["owner-access", "billing-export", "release-infra", "site"])
def test_only_the_platform_s_three_stacks_run(name: str) -> None:
    result = runner.invoke(cli.app, ["--config", str(CONFIG_DIR), "platform", "plan", name])
    assert result.exit_code == 2
    assert "foundation, monitoring, data-access" in result.output
```

Then add:
- `test_each_stack_runs_as_its_own_role`: `jaws-infra-ci-plan`, `jaws-infra-ci-apply`, `jaws-monitoring-ci-plan` and `jaws-data-access-ci-apply`.
- `test_plan_writes_the_comment_under_the_name_root`, with the fake's plan exiting 2:
  - exit 0, and the comment names `jaws/foundation`;
  - `GITHUB_OUTPUT` has `result=changes` and `changes=true`;
  - the fake's log has `init` with `-backend-config=backend.hcl`, and `plan` with `-detailed-exitcode`.
- `test_apply_applies_only_what_its_plan_found`, parametrized: plan exit 0 means no `apply` in the log and `result=no-changes`; plan exit 2 means `apply` of `tfplan` and `result=applied`.
- `test_the_stack_reads_the_cli_s_configuration`. The fake's environment log (`FAKE_TF_ENV`) has `TF_VAR_config_path`, the configuration's absolute path. For the foundation it also has `TF_VAR_datasets_path`, `<infra root>/datasets`.
- `test_the_databricks_credential_reaches_terraform_only`, with `databricks.enabled` true in a temporary copy of the fixture and `databricks_auth.load_secret` patched to return `"dbx-secret-value"`:
  - the fake's environment has `DATABRICKS_CLIENT_SECRET=dbx-secret-value`;
  - with `FAKE_TF_ECHO_SECRET=1`, the value is in none of `GITHUB_OUTPUT`, `.jaws/plan.txt`, `.jaws/plan-comment.md` and `.jaws/jaws.log`.

`tests/platform/test_platform_backends.py` holds the check against the owner's configuration:

```python
@pytest.mark.parametrize("name", ["foundation", "monitoring", "data-access"])
def test_the_hub_s_backends_are_the_stacks_own(name: str) -> None:
    """The hub applies the same roots against the same state (spec 6.10)."""
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    rendered = hcl_text_values(platform_backend(settings, platform_stack(name)))
    if rendered != hcl_values(REPO_ROOT / name / "backend" / "prod.hcl"):
        pytest.fail(
            f"{name}/backend/prod.hcl differs from the backend built from state", pytrace=False
        )
```

`hcl_text_values(text: str) -> dict[str, str]` joins `hcl_values` (plan 04) in `tests/workflow_steps.py`, and `hcl_values` reads its file through it. For data access, compare every key but `bucket`: today's sweep passes the bucket on the command line. Assert instead that the rendered `bucket` is `state.bucket`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_cli.py tests/platform/test_platform_backends.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jaws.platform'`.

- [ ] **Step 3: Implement `src/jaws/platform.py` and the two commands** per the Interfaces. The module docstring says these are the platform's own stacks, run from the image as a hub's workflows run them. It also says each backend is the stack's `backend/prod.hcl`, built from `state`.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_cli.py tests/platform -q && uv run mypy && uv run ruff check`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jaws/platform.py src/jaws/cli.py tests/test_platform_cli.py tests/platform/test_platform_backends.py tests/workflow_steps.py
git commit -m "feat(cli): plan and apply the platform's own stacks inside the image"
```

---

### Task 5: data access inside the image, and a render that refuses a missing registry

**Files:**
- Modify: `src/jaws/access.py`: a `render_access` function, from the body of `access_render` in `src/jaws/cli.py`
- Modify: `src/jaws/cli.py` (`access_render`, and the `data-access` path of `platform plan|apply`), `src/jaws/platform.py`
- Test: `tests/test_access_cli.py`, `tests/test_platform_cli.py`

**Interfaces:**
- Consumes: Task 4's commands.
- Produces `def render_access(settings: Settings, root: Path, base_registry: Path | None, logger: Logger) -> tuple[dict[str, Any], str]`, which returns the tfvars and the summary.
  - It raises `ConfigError` when `root / "datasets" / REGISTRY_README` isn't a file, with "no onboarded-dataset registry at {root}/datasets (no README.md there): rendered without it, every dataset's access would be revoked. In an image it is /etc/jaws/datasets, beside the configuration".
  - `access render` and data access's `platform` commands both call it.
- Produces `jaws platform plan data-access [--base-registry PATH]` and `jaws platform apply data-access`.
  - Unless `config env --databricks` would say `ready`, both log the notice "Databricks is {state}: nothing to reconcile", write `result=skipped`, write no comment and exit 0. They check this before the role, so a platform without Databricks never calls AWS.
  - Both render into the working copy, as `terraform.tfvars.json` and `access-summary.md`.
  - `plan`'s comment is the plan comment, a blank line, then the access summary, as `data-access.yml` builds it today.
  - `apply` is the sweep, and its step summary is the one `data-access.yml` writes today:
    - `**Sweep: <result>**`;
    - the access summary;
    - "Applied state", with the outputs `edges`, `awaiting_onboarding` and `missing_workspaces`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_access_cli.py`:

```python
def test_render_refuses_a_registry_without_its_readme(
    selfplay_workspace: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sweep applies what it renders: without its registry, every grant would go."""
    root = tmp_path / "image-without-datasets"
    root.mkdir()
    monkeypatch.setenv("JAWS_INFRA_ROOT", str(root))
    out = tmp_path / "rendered"
    result = runner.invoke(cli.app, ["access", "render", "--out", str(out)])
    assert result.exit_code == 2
    assert f"{root}/datasets" in result.output and "revoked" in result.output
    assert not out.exists()
```

In `tests/test_platform_cli.py`, add:
- `test_data_access_waits_for_databricks`: with `databricks.enabled` false, `plan data-access` exits 0, `GITHUB_OUTPUT` has `result=skipped`, there's no `.jaws/plan-comment.md`, and the fake terraform is never called.
- `test_the_data_access_plan_renders_against_the_base_registry`. With the registry fixture (`JAWS_INFRA_ROOT` at `tests/fixtures`) and Databricks ready:
  - the working copy's `terraform.tfvars.json` is the one `access render` writes;
  - the comment ends with the access summary;
  - a `--base-registry` that onboards a dataset the registry drops, while a handshake still names it, exits 2 before any plan.
- `test_the_sweep_summarizes_what_it_applied`: the fake's plan exits 2, and the step summary starts with `**Sweep: applied**`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_access_cli.py tests/test_platform_cli.py -v`
Expected: FAIL. The render goes ahead, and `data-access` has no render.

- [ ] **Step 3: Implement it.** Move the body of `access_render` into `render_access`, unchanged but for the README check. Wire data access into Task 4's commands.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest -q && uv run mypy`
Expected: PASS. Every existing access test passes, because the registry fixture has its README.

- [ ] **Step 5: Commit**

```bash
git add src/jaws/access.py src/jaws/cli.py src/jaws/platform.py tests/test_access_cli.py tests/test_platform_cli.py
git commit -m "feat(cli): sweep data access from the image, and refuse a render without its registry"
```

---

### Task 6: the comment footer names the platform's commit

**Files:**
- Modify: `src/jaws/report.py` (`Provenance`, `_footer`), `src/jaws/github.py` (`provenance`)
- Test: `tests/test_report.py`, `tests/test_github.py`

**Interfaces:**
- Consumes: plan 02's `_footer(provenance, brand, note=None)`.
- Produces, in `jaws.github`, `ENV_PLATFORM_COMMIT = "JAWS_PLATFORM_COMMIT"` and `ENV_PLATFORM_SOURCE = "JAWS_PLATFORM_SOURCE"`. The workflows set them from the build's labels (Task 8).
- Produces `Provenance.platform_sha: str | None = None` and `Provenance.platform_url: str | None = None`.
  - `provenance()` reads `JAWS_PLATFORM_COMMIT`, which must be 40 lowercase hex characters, else ignored.
  - It reads `JAWS_PLATFORM_SOURCE`, which must match `^https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9._-]+$`. The URL is `<source>/commit/<sha>`, and without a valid source the footer shows no link.
- With a platform commit, the footer's second part, after "Built with Jaws vX.Y.Z", is `Platform <a href="{platform_url}"><code>{sha[:7]}</code></a>`, or `Platform <code>{sha[:7]}</code>` without a URL. Without one, the footer is today's, byte for byte.

- [ ] **Step 1: Write the failing tests**

```python
HUB_COMMIT = "0123456789abcdef0123456789abcdef01234567"
HUB_URL = f"https://github.com/Example-Hub/platform/commit/{HUB_COMMIT}"


def test_the_footer_names_the_platform_s_commit() -> None:
    provenance = dataclasses.replace(PROVENANCE, platform_sha=HUB_COMMIT, platform_url=HUB_URL)
    comment = preview_removed_comment(3, "a.example", provenance, brand=ACME)
    parts = _footer(comment).split(" &nbsp;·&nbsp; ")
    assert parts[1] == f'Platform <a href="{HUB_URL}"><code>0123456</code></a>'
```

Plan 02's `test_the_plan_comment_s_footer_is_today_s_to_the_byte` must still pass unchanged.

In `tests/test_github.py`, add `test_provenance_reads_the_platform_s_commit`, parametrized:
- both variables set: both fields set;
- the commit `abc123`: `platform_sha is None`;
- the source `http://example.com/x`: the SHA is kept, and `platform_url is None`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_report.py tests/test_github.py -v`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'platform_sha'`.

- [ ] **Step 3: Implement it** per the Interfaces, with the HTML escaped as plan 02 escapes the brand.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_report.py tests/test_github.py -q && uv run mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jaws/report.py src/jaws/github.py tests/test_report.py tests/test_github.py
git commit -m "feat(cli): name the platform's commit in the comment footer"
```

---

### Task 7: `jaws platform check`: one version, one identity

**Files:**
- Modify: `src/jaws/platform.py` (the check), `src/jaws/cli.py` (`platform check`)
- Create: `tests/test_platform_check.py`

**Interfaces:**
- Consumes: plan 02's `brand.check_prefix`, plan 03's `platform.hub`, and `tool_version()`.
- Produces:
  - `IDENTITY_WORKFLOWS: frozenset[str]`: `site-plan.yml`, `site-preview.yml`, `site-deploy.yml`, `remote-task.yml`, `container-release.yml`, `platform-release.yml`, `platform-rollback.yml`, `platform-bot-apply.yml`, `platform-databricks-apply.yml` and `platform-sweep.yml`.
  - `CHECK_PREFIX_WORKFLOWS: frozenset[str]`: the three site workflows. Task 13 adds the test that keeps both in step with the workflows' inputs.
  - `@dataclass(frozen=True) class HubProblem`, with `path: str` and `message: str`.
  - `def check_hub(root: Path, settings: Settings, version: str, repository: str | None) -> list[HubProblem]`: nothing when the hub agrees.
- Produces `jaws platform check [--root PATH]`. `--root` defaults to `.`, and the repository is `GITHUB_REPOSITORY`.
  - It writes each problem as an error annotation, `{path}: {message}`.
  - It exits 1 if there are any, and otherwise prints "the hub's pins and identity agree: Jaws v{version}".
- The rules and their messages, verbatim. `{expected}` is the configuration's value:
  1. The `Dockerfile`'s one `FROM` is `<image>:v<X.Y.Z>@sha256:<64 hex>`, else: "FROM must pin the Jaws image by tag and digest (FROM public.ecr.aws/<alias>/jaws:vX.Y.Z@sha256:…), not {line!r}".
  2. The tag is `v{version}`, else: "the Dockerfile pins {tag}, but the image it built runs Jaws v{version}: its digest is another release's".
  3. Every job in `.github/workflows/*.yml` and `*.yaml` whose `uses` is `Jaws-Platform/jaws/.github/workflows/<file>@<ref>` has `ref == tag`, else: "job {job} calls Jaws-Platform/jaws at {ref}, but the Dockerfile pins {tag}: one pull request bumps every pin". With no such job: "no job calls a Jaws-Platform/jaws workflow".
  4. A call of a file in `IDENTITY_WORKFLOWS` passes `platform-image`, `account-id` and `name-root`. One in `CHECK_PREFIX_WORKFLOWS` also passes `check-prefix`. A key that is missing gives: "job {job} calls {file} without {key}: it would run as one of Jaws's own projects, not this platform's".
  5. Each key is a literal equal to the configuration's value:
     - `platform-image` is `platform.hub.image`;
     - `account-id` is `aws.account_id`;
     - `name-root` is `context.name_root`;
     - `check-prefix` is `brand.check_prefix`.

     A value with `${{` gives: "job {job} passes {key} as an expression: a project's run needs the platform's identity before it can read anything, so it is a literal". Any other value gives: "job {job} passes {key}: {value!r}, but the configuration says {expected!r}".
  6. `platform.hub` is set, else: "platform.hub is not set (config/platform.yaml)". When `repository` is given, `platform.hub.repository == repository`, else: "platform.hub.repository is {hub}, but this check runs in {repository}".

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_check.py`

```python
DIGEST = "sha256:" + "a" * 64
CALLER = """on: {workflow_call: {}}
jobs:
  plan:
    uses: Jaws-Platform/jaws/.github/workflows/site-plan.yml@%(ref)s
    with:
      platform-image: %(image)s
      account-id: "%(account)s"
      name-root: jaws
      check-prefix: jaws
"""


def _hub(tmp_path: Path, ref: str = "v0.81.0", **values: str) -> Path:
    """A hub checkout: a Dockerfile pinning v0.81.0 and one site-plan caller."""
    ...


def _settings() -> Settings:
    """The fixture's configuration, with Example-Hub/platform as its hub."""
    ...


def test_a_hub_whose_pins_and_identity_agree_passes(tmp_path: Path) -> None:
    assert check_hub(_hub(tmp_path), _settings(), "0.81.0", "Example-Hub/platform") == []


def test_a_pin_that_disagrees_fails_the_check(tmp_path: Path) -> None:
    (problem,) = check_hub(_hub(tmp_path, ref="v0.80.1"), _settings(), "0.81.0", None)
    assert problem.path == ".github/workflows/site-plan.yml"
    assert "v0.80.1" in problem.message and "v0.81.0" in problem.message


@pytest.mark.parametrize(
    ("values", "found"),
    [
        ({"image": "jaws-cli"}, "platform-image: 'jaws-cli'"),
        ({"account": "333333333333"}, "account-id: '333333333333'"),
        ({"image": "${{ vars.PLATFORM_IMAGE }}"}, "platform-image as an expression"),
    ],
)
def test_an_identity_that_disagrees_fails_the_check(
    tmp_path: Path, values: dict[str, str], found: str
) -> None:
    problems = check_hub(_hub(tmp_path, **values), _settings(), "0.81.0", None)
    assert [p.message for p in problems if found in p.message]
```

Then add:
- `test_a_dockerfile_without_a_digest_fails_the_check`;
- `test_an_image_of_another_release_fails_the_check`: version `0.80.1` against the tag `v0.81.0`;
- `test_a_caller_without_its_identity_fails_the_check`: the `name-root` line removed;
- `test_a_hub_configured_for_another_repository_fails_the_check`: the repository `Other-Org/platform`;
- `test_platform_check_exits_1_and_annotates_each_problem`, through the CLI with `GITHUB_ACTIONS=true`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_check.py -v`
Expected: FAIL with `ImportError: cannot import name 'check_hub'`.

- [ ] **Step 3: Implement it** per the Interfaces. Read the workflows with `yaml.safe_load`, and list each problem once, in file order.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_check.py -q && uv run mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jaws/platform.py src/jaws/cli.py tests/test_platform_check.py
git commit -m "feat(cli): check that a hub's pins and identity agree with its configuration"
```

---

### Task 8: the composite actions `platform-role` and `platform-image`, and the `jaws` action runs a given image

**Files:**
- Create: `.github/actions/platform-role/action.yml`, `.github/actions/platform-image/action.yml`
- Modify: `.github/actions/jaws/action.yml`
- Modify: `tests/workflow_steps.py`: `ACTIONS`, `action_step` and `run_action_step`
- Create: `tests/test_platform_actions.py`
- Modify: `tests/test_jaws_action.py`
- Create: `docs/platform-workflows.md` ("How a hub runs Jaws")

**Interfaces:**
- Consumes: the tags (Task 2), and plan 04's `run_step` pattern.
- Produces, in `tests/workflow_steps.py`:
  - `ACTIONS = REPO_ROOT / ".github" / "actions"`;
  - `def action_step(action: str, step_id: str) -> dict[str, Any]`;
  - `def run_action_step(action: str, step_id: str, *, cwd: Path, env: Mapping[str, str], fakes: Mapping[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], str]`. It is `run_step`'s mechanism for a composite action's step.
- Produces `.github/actions/platform-role`, which makes no AWS call.
  - Inputs: `account-id`, `name-root` and `role` (one of `plan`, `preview`, `apply`, `release` and `task`), all required; `project` (default `""`, read from `project-file` then); `project-file` (default `jaws.yaml`); `role-arn` (default `""`, an override).
  - Its one step, `id: arn`, takes the inputs as `ACCOUNT_ID`, `NAME_ROOT`, `ROLE`, `PROJECT`, `PROJECT_FILE` and `ROLE_ARN`.
    - It refuses, naming the input: an account that isn't 12 digits; a name root or project that isn't lowercase kebab-case; an unknown role; and an override that isn't `arn:aws:iam::<account-id>:role/…`.
    - It writes `arn=`: the override, else `arn:aws:iam::<account-id>:role/<name-root>-<project>-ci-<role>`.
  - Output: `arn`.
- Produces `.github/actions/platform-image`. The job has already assumed a role.
  - Inputs:
    - `account-id` and `repository`;
    - `tag` (default `current`) or `digest` (a manifest digest, from another job of the run);
    - or `artifact` with `image-id`: this run's candidate (Task 11);
    - and `extract` (default `""`: a directory to copy `/etc/jaws/config` and `/etc/jaws/datasets` into).
  - Its steps, by id:
    1. `ecr` (`amazon-ecr-login`) and `account`, which refuses a role outside `account-id`. Both are skipped for an artifact.
    2. `resolve`, `aws ecr batch-get-image --image-ids imageTag=<tag>`, or `imageDigest=<digest>`. It reads the digest, and the image ID from the manifest's `config.digest`.
       - With no image it stops with "{repository}:{tag} does not exist", adding ": the hub's first release tags its build current" for `current`.
       - With the image it writes `digest`, `image-id` and `reference` (`<registry>/<repository>@<digest>`).
    3. `artifact`: `download-artifact`, then `docker load`.
    4. `cache`, `actions/cache/restore`, keyed `platform-image-<image-id>`.
    5. `load`: a cache hit is `docker load`ed. Otherwise, or when the loaded image's ID isn't `image-id`, it runs `docker pull <reference>`, then `docker save` for the cache.
    6. `save`, `actions/cache/save`, on a miss.
    7. `extract`, with `docker create`, `docker cp` and `docker rm`.
    8. `labels`.

    Pin `actions/cache` at the major `gh api repos/actions/cache/releases/latest --jq .tag_name` names.
  - Outputs: `image-id`, `digest` and `reference`; `platform-commit` and `platform-source` (the labels `org.opencontainers.image.revision` and `.source`); `config` and `infra-root` (`<extract>/config` and `<extract>`).
- Produces in `.github/actions/jaws`:
  - `role-arn` becomes optional;
  - a new input `image`: an image ID the job resolved and pulled. With it the action assumes no role, logs in nowhere and reads no `config/`. Its three first steps take `if: inputs.image == ''`;
  - a new input `github-token`, passed to the CLI as `GH_TOKEN`;
  - with `image`, the run step reads the two labels and passes them as `JAWS_PLATFORM_COMMIT` and `JAWS_PLATFORM_SOURCE`;
  - without `role-arn` or `image`, the first step stops with "the jaws action needs role-arn, or an image the job already pulled".

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_actions.py`

```python
IDENTITY = {
    "ACCOUNT_ID": "123456789012",
    "NAME_ROOT": "jaws",
    "ROLE": "plan",
    "PROJECT": "",
    "PROJECT_FILE": "jaws.yaml",
    "ROLE_ARN": "",
}


def test_the_role_comes_from_the_identity_and_the_project_file(tmp_path: Path) -> None:
    (tmp_path / "jaws.yaml").write_text("version: 1\nproject: guitar-knowledge-base\n")
    result, output = run_action_step("platform-role", "arn", cwd=tmp_path, env=IDENTITY)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == [
        "arn=arn:aws:iam::123456789012:role/jaws-guitar-knowledge-base-ci-plan"
    ]


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"ACCOUNT_ID": ""}, "account-id"),
        ({"ACCOUNT_ID": "12345678901"}, "account-id"),
        ({"NAME_ROOT": "Jaws"}, "name-root"),
        ({"ROLE": "admin"}, "role"),
        ({"PROJECT": "Not_Kebab"}, "project"),
        ({"ROLE_ARN": "arn:aws:iam::111122223333:role/jaws-site-ci-plan"}, "role-arn"),
    ],
)
def test_half_an_identity_stops_the_job_before_aws(
    tmp_path: Path, change: dict[str, str], named: str
) -> None:
    (tmp_path / "jaws.yaml").write_text("version: 1\nproject: guitar-knowledge-base\n")
    result, output = run_action_step(
        "platform-role", "arn", cwd=tmp_path, env={**IDENTITY, **change}
    )
    assert result.returncode != 0 and f"::error::{named}" in result.stdout and output == ""
```

The `platform-image` step tests use `fakes` for `aws` and `docker`. Each fake logs its calls to `FAKE_LOG`, and the fake `aws` answers `batch-get-image` from `FAKE_IMAGES`:
- `test_current_is_resolved_to_one_build`. `resolve` writes `digest=sha256:bbb…`, `image-id=sha256:ccc…` (the fake manifest's `config.digest`) and `reference=123456789012.dkr.ecr.us-east-1.amazonaws.com/jaws-platform@sha256:bbb…`. The log has `--image-ids imageTag=current`.
- `test_a_digest_another_job_resolved_is_used_as_given`: the log has `imageDigest=sha256:bbb…` and no `imageTag`.
- `test_no_build_tagged_current_stops_the_job`: an empty `images`, with an `ImageNotFound` failure. The step stops, and its error says the first release tags it.
- `test_a_role_in_another_account_stops_the_pull`: `account` with the caller in `111122223333` stops with `::error::`, and nothing is pulled.
- `test_a_cached_build_is_loaded_and_checked` and `test_a_cached_build_with_another_id_is_pulled_again`: `load`, with `CACHE_HIT=true`, and the fake `docker`'s `image inspect` answering the right ID, then a wrong one.
- `test_the_configuration_is_copied_out_of_the_build`: `extract` copies `/etc/jaws/config` and `/etc/jaws/datasets` into `<extract>/config` and `<extract>/datasets`, then removes the container.
- `test_the_build_is_resolved_once_and_run_by_its_id`: the action's outputs map `image-id`, `digest` and `reference` to `steps.resolve`'s, and the `jaws` action's run step pulls nothing when `IMAGE` is set.
- `test_no_hub_workflow_or_action_spells_a_name_the_root_derives`. It reads every `.github/workflows/platform-*.yml` and `.github/actions/platform-*/action.yml`, including those later tasks add. None holds `.context.name_root`, `/jaws/databricks/`, `/jaws/monitoring/`, `jaws-infra-ci-`, `jaws-monitoring-ci-` or `jaws-data-access-ci-`. Each name comes from the configuration in the image, or from the identity inputs. The image's own paths, `/etc/jaws` and `/opt/jaws`, are Jaws's (spec 6.7).

In `tests/test_jaws_action.py`, add:
- `test_without_an_image_the_action_runs_as_today`: the three first steps are `if: inputs.image == ''`, and `IMAGE_TAG` keeps `# x-release-please-version`. The existing tests pass unchanged.
- `test_a_given_image_runs_with_the_platform_s_commit`: running the run step with a fake `docker` gives one `docker run … sha256:ccc…` with `--env JAWS_PLATFORM_COMMIT` and no `pull`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_actions.py tests/test_jaws_action.py -v`
Expected: FAIL. There's no `platform-role` or `platform-image`, and the `jaws` action has no `image` input.

- [ ] **Step 3: Write the two actions and change the `jaws` action** per the Interfaces. Each action's description says what it does, what it needs from the job, and which of the spec's rules it keeps (6.3 for `platform-image`).

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_actions.py tests/test_jaws_action.py tests/test_workflow_artifacts.py -q`
Expected: PASS

- [ ] **Step 5: Docs.** Create `docs/platform-workflows.md`, for whoever writes a hub's callers. It opens with "How a hub runs Jaws":
  - the identity a caller spells, and why it's a literal (rulings 2 and 10);
  - the image's tags, and one build per run (rulings 3 and 6);
  - the cache, and what it saves (ruling 4);
  - the labels, and the footer's commit.

  Later tasks add the other sections.

- [ ] **Step 6: Commit**

```bash
git add .github/actions tests/workflow_steps.py tests/test_platform_actions.py tests/test_jaws_action.py docs/platform-workflows.md
git commit -m "feat(workflows): resolve a hub's image once per run and run it by its id"
```

---

### Task 9: the site workflows take the platform's identity and a check-name prefix

**Files:**
- Modify: `.github/workflows/site-plan.yml`, `site-preview.yml`, `site-deploy.yml`, and `site-release-please.yml` (its comment only)
- Create: `tests/test_site_workflows.py`
- Modify: `tests/test_workflow_roles.py` (its docstring, and `test_no_workflow_addresses_an_account_of_its_own`'s)
- Modify: `README.md` ("Reusable workflows for site repositories", "The pull request comments"), `docs/platform-workflows.md` ("Project-facing workflows")

**Interfaces:**
- Consumes: `platform-role`, `platform-image` and the `jaws` action's `image` (Task 8).
- Produces, on each of the three workflows:
  - new inputs `platform-image`, `account-id` and `name-root` (string, default `""`), and `check-prefix` (string, default `jaws`);
  - `plan-role-arn`, `preview-role-arn` and `apply-role-arn` become `required: false` with default `""`. Each description says it's needed without `platform-image`, and with it is an override in `account-id`.
- The job names, per plan 02's decision: `${{ inputs.check-prefix }} plan`, `${{ inputs.check-prefix }} preview deploy`, `${{ inputs.check-prefix }} preview remove` and `${{ inputs.check-prefix }} release`.
- Each job's new steps, after the tool checkout's verify step:
  1. `id: role`, `uses: ./.jaws-tool/.github/actions/platform-role`.
     - `if: inputs.platform-image != '' || inputs.account-id != '' || inputs.name-root != ''`.
     - `role` is `plan`, `preview` or `apply`, and `role-arn` is the job's role input.
  2. `aws-actions/configure-aws-credentials@v6`, `if: steps.role.outputs.arn != ''`.
  3. `id: image`, `uses: ./.jaws-tool/.github/actions/platform-image`, under the same `if`, with `repository: ${{ inputs.platform-image }}`.
- Each `jaws` action step takes:
  - `role-arn: ${{ steps.role.outputs.arn == '' && inputs.<role input> || '' }}`;
  - `image: ${{ steps.image.outputs.image-id }}`.
- The descriptions of `app-client-id` and `app-private-key` say "the platform's comments App" in place of "the Jaws GitHub App".
- `site-release-please.yml` takes no new input, since it reaches no AWS. Its comment adds that a project calling a hub names its secrets at each level, because `secrets: inherit` stops at an organization.

- [ ] **Step 1: Write the failing tests** in `tests/test_site_workflows.py`

```python
#: (workflow, job) -> (the platform-role `role`, the role input, the check name's rest)
SITE_JOBS = {
    ("site-plan.yml", "plan"): ("plan", "plan-role-arn", "plan"),
    ("site-preview.yml", "deploy"): ("preview", "preview-role-arn", "preview deploy"),
    ("site-preview.yml", "remove"): ("preview", "preview-role-arn", "preview remove"),
    ("site-deploy.yml", "deploy"): ("apply", "apply-role-arn", "release"),
}
JOBS = list(SITE_JOBS)


@pytest.mark.parametrize(("workflow", "job_name"), JOBS)
def test_the_check_names_take_the_prefix_and_keep_today_s_by_default(
    workflow: str, job_name: str
) -> None:
    *_, rest = SITE_JOBS[(workflow, job_name)]
    assert job(workflow, job_name)["name"] == f"${{{{ inputs.check-prefix }}}} {rest}"
    inputs = yaml.safe_load((WORKFLOWS / workflow).read_text())[True]["workflow_call"]["inputs"]
    assert inputs["check-prefix"]["default"] == "jaws"


@pytest.mark.parametrize(("workflow", "job_name"), JOBS)
def test_a_site_job_resolves_the_platform_image_once(workflow: str, job_name: str) -> None:
    steps = job(workflow, job_name)["steps"]
    images = [s for s in steps if s.get("uses", "").endswith("/actions/platform-image")]
    runs = [s for s in steps if s.get("uses", "").endswith("/actions/jaws")]
    assert len(images) == 1 and runs
    assert steps.index(images[0]) < steps.index(runs[0])
    assert all(s["with"]["image"] == "${{ steps.image.outputs.image-id }}" for s in runs)
```

Then add:
- `test_each_site_workflow_takes_the_platform_s_identity`. The three inputs default to `""`, and each role input is `required: False` with default `""`.
- `test_in_a_hub_the_role_comes_from_the_identity`:
  - the `platform-role` step's `role` and `role-arn` are `SITE_JOBS`'s;
  - `configure-aws-credentials` and `platform-image` take `if: steps.role.outputs.arn != ''`;
  - the credentials use `steps.role.outputs.arn`.
- `test_without_a_platform_image_a_site_job_runs_as_today`:
  - `platform-role`'s `if` names all three inputs;
  - each `jaws` step's `role-arn` falls back to the job's role input;
  - the tool checkout and its verify step come first, unchanged (`tests/test_tool_checkout.py` already checks them).

In `tests/test_workflow_roles.py`, the module docstring becomes: every workflow builds its roles from the tool's reading of its configuration (`config/`), or, in a hub's run, from the platform's identity through `platform-role`. `jaws platform check` holds that identity to the configuration (Task 7).

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_site_workflows.py -v`
Expected: FAIL. The jobs are still named `jaws plan` and so on, and there's no `platform-image` input.

- [ ] **Step 3: Change the three workflows** per the Interfaces. Keep every existing step, with its `if`, as it is.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_site_workflows.py tests/test_tool_checkout.py tests/test_repository_name.py tests/test_workflow_roles.py tests/test_workflow_artifacts.py -q`
Expected: PASS

- [ ] **Step 5: Docs**
  - **`README.md`, "Reusable workflows for site repositories":**
    - the table's "Caller needs" column adds, for the three workflows, "or, in a hub, `platform-image`, `account-id`, `name-root` and `check-prefix`";
    - a paragraph, "In a hub": a project calls the hub's copy of each workflow at `@live` and names no version. The hub's caller spells the identity, and the run then:
      - derives every role ARN from it;
      - resolves `current` once;
      - names the hub commit in the comment's footer.

      It links `docs/platform-workflows.md`.
  - **`README.md`, "Who posts the comment":** a platform passes its own comments App the same way.
  - **`docs/platform-workflows.md`, "Project-facing workflows":** each workflow's inputs in a hub, a hub's caller for `site-plan` with placeholder values, and the extra level in the check names ("For plans 06 and 07").

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/site-*.yml tests/test_site_workflows.py tests/test_workflow_roles.py README.md docs/platform-workflows.md
git commit -m "feat(sites): run the site workflows from a hub's image, with its check-name prefix"
```

---

### Task 10: remote tasks and container releases run with the hub's configuration

**Files:**
- Modify: `.github/workflows/remote-task.yml`, `.github/workflows/container-release.yml`
- Modify: `tests/test_remote_task_workflow.py`
- Create: `tests/test_container_release_workflow.py`
- Modify: `docs/remote-tasks.md`, `docs/lichess-bot.md` (each one's caller section), `docs/platform-workflows.md`

**Interfaces:**
- Consumes: Task 8's actions.
- Produces, in both workflows:
  - new inputs `platform-image`, `account-id` and `name-root` (default `""`);
  - a job `env` entry, `JAWS_TOOL_CONFIG: ${{ inputs.platform-image != '' && '.jaws-platform/config' || '.jaws-tool/config' }}`;
  - every CLI call spells `--config "$JAWS_TOOL_CONFIG"` in place of `--config .jaws-tool/config`, the job's `CLI` included.
- `remote-task.yml`'s `role` step becomes:
  - `platform-role`, `id: platform`, under the identity `if` (Task 9's), with `role: task` and `project: ${{ inputs.project }}`;
  - then the existing step, which keeps `id: role`. Its `arn` is `steps.platform.outputs.arn` when set. Otherwise it builds the ARN from `jaws config env`, as today. It computes `duration` in both cases.
- In `container-release.yml`:
  - `platform-role` takes `role: release`, `project: ${{ inputs.project }}` and `role-arn: ${{ inputs.release-role-arn }}`;
  - the existing role step runs only when `steps.platform.outputs.arn` is empty.
- After the credentials step, both run `platform-image` with `extract: .jaws-platform`, under `if: steps.platform.outputs.arn != ''`.
- The steps that run the CLI get `JAWS_INFRA_ROOT`, `JAWS_PLATFORM_COMMIT` and `JAWS_PLATFORM_SOURCE` from its outputs. They're empty outside a hub, which changes nothing.
- `remote-task.yml` still names no `github.token` and no `secrets.`, and its checkouts still don't persist credentials.

- [ ] **Step 1: Write the failing tests**

In `tests/test_remote_task_workflow.py`:
- `test_it_is_reusable_with_the_planned_inputs`'s set gains `platform-image`, `account-id` and `name-root`.
- `test_runs_the_cli_from_this_workflow_commit` asserts these, in place of `--config .jaws-tool/config `:
  - `'--config "$JAWS_TOOL_CONFIG"'` appears in the text;
  - the job's `JAWS_TOOL_CONFIG` is the expression above.
- Add `test_in_a_hub_the_task_role_comes_from_the_platform_s_identity`:
  - `platform-role`'s `with` is `role: task` and `project: ${{ inputs.project }}`;
  - `role`'s script uses `$PLATFORM_ARN` when set, and calls `config env` only otherwise;
  - the credentials keep `role-duration-seconds`.
- Add `test_in_a_hub_the_cli_reads_the_platform_image_s_configuration`. `platform-image` comes between the credentials and `jaws task run`, with `extract: .jaws-platform`. The task step's `JAWS_INFRA_ROOT` is `${{ steps.image.outputs.infra-root }}`.
- Add `test_without_a_platform_image_a_task_runs_as_today`. Run the `role` step with `PLATFORM_ARN=""` and a fake `jaws` whose `config env` prints the fixture's lines. The result is `arn=arn:aws:iam::222222222222:role/jaws-braveheart-ci-task`, with a duration.

`tests/test_container_release_workflow.py` holds the same three tests for `container-release.yml`, with `role: release` and the `release-role-arn` override.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_remote_task_workflow.py tests/test_container_release_workflow.py -v`
Expected: FAIL

- [ ] **Step 3: Change both workflows** per the Interfaces. Keep the `exec` of the CLI, which `jaws task run`'s signal handling needs.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_remote_task_workflow.py tests/test_container_release_workflow.py tests/test_tool_checkout.py tests/test_workflow_roles.py -q`
Expected: PASS

- [ ] **Step 5: Docs.** Each caller section in `docs/remote-tasks.md` and `docs/lichess-bot.md` gains: in a hub, call the hub's copy at `@live`, which spells the identity. In `docs/platform-workflows.md`, "Project-facing workflows" adds both workflows and why they run from source (ruling 14).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/remote-task.yml .github/workflows/container-release.yml tests/test_remote_task_workflow.py tests/test_container_release_workflow.py docs
git commit -m "feat(bots): run remote tasks and bot releases with a hub's configuration"
```

---

### Task 11: `platform-ci.yml`: a hub's pull requests

**Files:**
- Create: `.github/actions/platform-build/action.yml`, `.github/workflows/platform-ci.yml`
- Create: `tests/test_platform_ci.py`
- Modify: `docs/platform-workflows.md` ("The hub's pull requests")

**Interfaces:**
- Consumes:
  - `config env --platform` and `config projects` (Task 3);
  - `platform plan` (Tasks 4–5) and `platform check` (Task 7);
  - Task 8's actions.
- Produces `.github/actions/platform-build`.
  - Inputs: `load` or `push` (`"true"` or `"false"`), `tags` (for a push), `revision` (the hub commit).
  - Step `id: base` reads the `Dockerfile`'s one `FROM` with `^FROM ([^ @]+):(v[0-9]+\.[0-9]+\.[0-9]+)@(sha256:[0-9a-f]{64})$`. It writes `name`, `tag` and `digest`, and refuses anything else with rule 1's message (Task 7).
  - Then `setup-buildx`, and `build-push-action` (`id: build`):
    - `context: .`, `platforms: linux/amd64`, `provenance: false`;
    - the labels `org.opencontainers.image.revision=<revision>`, `org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}`, `org.opencontainers.image.base.name=<name>:<tag>` and `org.opencontainers.image.base.digest=<digest>`.
  - Outputs: `image-id`, `digest` and `tag`.
- Produces `platform-ci.yml`, `on: workflow_call`.
  - Input: `app-client-id` (default `""`). Secret: `app-private-key` (optional).
  - Top-level `permissions: {}`.
  - Each job checks out the tool at its own commit and verifies it (`tests/test_tool_checkout.py`'s pattern).
  - Jobs:

| Job (`name`) | Does |
|---|---|
| `candidate` (`Platform check`) | builds the PR head (`load: "true"`, `revision: ${{ github.event.pull_request.head.sha }}`). Offline (`docker run --rm --network none`), it runs `config show`, `platform check` (the checkout mounted read-only, with `GITHUB_REPOSITORY`), `config env --monitoring --databricks --brand --platform` into `GITHUB_OUTPUT`, and `config projects site bot research databricks` as `projects`. It saves the image as the artifact `platform-image` (`retention-days: 1`) and outputs `image-id`, `account_id`, `name_root`, `monitoring`, `databricks`, `platform_image` and `projects` |
| `foundation` (`Terraform plan`) | `platform-role` (project `infra`, role `plan`), the credentials, `platform-image` with `artifact` and `image-id`, then `jaws` with `command: platform plan foundation`. Comment header `terraform-plan` |
| `monitoring` (`Monitoring plan`) | with `monitoring == 'configured'` and the PR from this repository: the same, with project `monitoring`. Until its role exists, the credentials step (`continue-on-error`) leads to a notice and a skip, as `ci.yml` does today. Header `monitoring-plan` |
| `data-access` (`Data access plan`) | not for Dependabot: checks out the base's `datasets` into `.base`, then runs `platform plan data-access --base-registry .base/datasets`. Header `data-access-plan` |
| `projects` (`${{ matrix.type == 'databricks' && 'Databricks' \|\| matrix.type == 'site' && 'Site' \|\| 'Bot' }} plan (${{ matrix.project }})`) | when `projects != '[]'`, over its matrix (`fail-fast: false`). It skips a Databricks project while `databricks == 'disabled'`. It checks out the project's `jaws.yaml` (and `lichess` for a bot), skips a file that names another project, and takes the project's plan role, skipping with a warning until it exists. It runs `--file .consumer/jaws.yaml plan` with `github-token: ${{ github.token }}`. Header `<databricks\|site\|bot>-plan-<project>` |

  - The jobs that need AWS have `id-token: write`, and the ones that comment have `pull-requests: write`.
  - Each comment step mints `inputs.app-client-id`'s token with `continue-on-error: true`, and posts with `steps.app-token.outputs.token || github.token`.
  - Each job uploads `.jaws/` with `include-hidden-files: true`.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_ci.py`

```python
CI = "platform-ci.yml"
PLAN_JOBS = ["foundation", "monitoring", "data-access", "projects"]


def test_the_candidate_is_built_once_and_passed_to_every_plan() -> None:
    upload = uses(job(CI, "candidate"), "actions/upload-artifact")
    assert upload["with"]["name"] == "platform-image" and upload["with"]["retention-days"] == 1
    for name in PLAN_JOBS:
        image = uses(job(CI, name), "./.jaws-tool/.github/actions/platform-image")
        assert job(CI, name)["needs"] == "candidate" or "candidate" in job(CI, name)["needs"]
        assert image["with"]["artifact"] == "platform-image"
        assert image["with"]["image-id"] == "${{ needs.candidate.outputs.image-id }}"


def test_no_pull_request_job_can_push_or_move_current() -> None:
    text = (WORKFLOWS / CI).read_text()
    for word in ("amazon-ecr-login", "put-image", "docker push", "push: true", "ci-apply"):
        assert word not in text, word
```

Then add:
- `test_the_hub_is_checked_inside_its_candidate`. The `candidate` job's run steps hold the four offline commands, each with `--network none`. `platform check` runs with the checkout mounted read-only.
- `test_every_platform_stack_and_project_is_planned`:
  - the names and commands of the table;
  - the `projects` job's matrix is `fromJSON(needs.candidate.outputs.projects)`, under `if: needs.candidate.outputs.projects != '[]'`.
- `test_each_plan_assumes_its_own_plan_role`. `platform-role`'s `project` is `infra`, `monitoring`, `data-access` or `${{ matrix.project }}`. Its `role` is `plan`, and its identity comes from `needs.candidate.outputs`.
- `test_the_comments_come_from_the_platform_s_app_or_github_actions`.
- On the `platform-build` action:
  - `test_the_build_records_its_jaws_release_and_hub_commit`: the four labels;
  - `test_the_base_must_be_pinned_by_tag_and_digest`: `base` run with `run_action_step`. It accepts `FROM public.ecr.aws/example-alias/jaws:v0.81.0@sha256:aaa…`, and refuses no digest, two `FROM`s and `:latest`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_ci.py -v`
Expected: FAIL with `FileNotFoundError` for `platform-ci.yml`.

- [ ] **Step 3: Write the action and the workflow** per the Interfaces. The workflow's header comment says:
  - what a hub's PR runs;
  - that the candidate is passed between jobs, never pushed (ruling 5);
  - that every plan runs with it (spec 6.3, 6.5);
  - what the caller passes.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_ci.py tests/test_tool_checkout.py tests/test_repository_name.py tests/test_workflow_artifacts.py tests/test_owner_access.py tests/test_billing_export.py -q`
Expected: PASS

- [ ] **Step 5: Docs.** `docs/platform-workflows.md`, "The hub's pull requests":
  - the jobs and their checks, which are the hub's required checks;
  - the candidate;
  - what the check holds (rulings 10 and 11);
  - the site plans, which the site plan roles trust the hub for (spec 6.5, 6.6);
  - the caller, with placeholders.

- [ ] **Step 6: Commit**

```bash
git add .github/actions/platform-build .github/workflows/platform-ci.yml tests/test_platform_ci.py docs/platform-workflows.md
git commit -m "feat(workflows): plan every stack and project of a hub with its candidate image"
```

---

### Task 12: `platform-release.yml` and `platform-rollback.yml`

**Files:**
- Create: `.github/workflows/platform-release.yml`, `.github/workflows/platform-rollback.yml`
- Create: `tests/test_platform_release.py`
- Modify: `docs/platform-workflows.md` ("Releases, current and live", "Rolling back")

**Interfaces:**
- Consumes: `platform apply` (Task 4); `platform-build`, `platform-role` and `platform-image` (Tasks 8 and 11); the tags (Task 2).
- Produces `platform-release.yml`, `on: workflow_call`, with inputs `platform-image`, `account-id` and `name-root` (required), and the required secrets `RELEASE_BOT_CLIENT_ID` and `RELEASE_BOT_PRIVATE_KEY`. Its jobs:

| Job (`name`) | Needs, condition | Does |
|---|---|---|
| `release-please` (`Release Please`) | `github.event_name == 'push'` | as `release-please.yml`'s, with the release App's token. Outputs `release_created` and `tag_name` |
| `image` (`Build the platform image (<tag>)`) | `release_created == 'true'`; `environment: prod` | checks out `refs/tags/<tag>`, and its step `id: commit` writes `commit=$(git rev-parse HEAD)`, a job output. It takes `platform-role` (project `infra`, role `apply`) and the credentials, then `amazon-ecr-login`. `platform-build` runs with `push: "true"`, `tags: <registry>/<platform-image>:sha-<commit>` and `revision: <commit>`. Outputs `digest`, and `monitoring` (`config env --monitoring`, run offline in the build) |
| `apply` (`Terraform apply (<tag>)`) | `image`; `prod` | `platform-image` with `digest: ${{ needs.image.outputs.digest }}`, then `platform apply foundation` |
| `monitoring-apply` (`Monitoring apply (<tag>)`) | `apply`; `monitoring == 'configured'`; `prod` | the same, with project `monitoring`, then `platform apply monitoring` |
| `current` (`Move current to <tag>`) | `image`, `apply`; `needs.apply.result == 'success'`; `prod` | step `id: move` |
| `live` (`Move live to <tag>`) | `image`, `current` | mints the release App's token, then step `id: move` |

- `current`'s `move`:
  - `aws ecr batch-get-image --image-ids imageDigest=$DIGEST` for the manifest and its media type;
  - then `aws ecr put-image --image-tag current --image-digest "$DIGEST" --image-manifest …`;
  - `ImageAlreadyExistsException` means `current` already names the build, which counts as a success;
  - the summary is "`current` is `<reference>` (`sha-<commit>`)".
- `live`'s `move`, with `GH_TOKEN` set to the App's token:
  - `gh api -X PATCH repos/$REPOSITORY/git/refs/heads/live -f sha=$COMMIT -F force=false`;
  - when the ref doesn't exist yet (`Reference does not exist`), `gh api -X POST repos/$REPOSITORY/git/refs -f ref=refs/heads/live -f sha=$COMMIT`;
  - any other failure stops the job, naming `live` and the commit.
- Produces `platform-rollback.yml`, `on: workflow_call`, with the identity, `commit` (required; 40 hex) and the release App's secrets. Job `rollback` (`Roll back to <commit>`), in `prod`, with `platform-role` (`infra`, `apply`):
  - step `id: check`:
    - refuses a `commit` that isn't 40 lowercase hex;
    - refuses one not on `main` (`gh api repos/$REPOSITORY/compare/$COMMIT...main --jq .status` must be `ahead` or `identical`): "{commit} is not on main";
    - refuses one whose build is gone (`batch-get-image imageTag=sha-$COMMIT` finds nothing): "no build of {commit} is kept: the newest ten are; roll back to one of them, or release a fix";
  - then `current`'s move, for that build;
  - then `live`'s move with `-F force=true`;
  - it applies nothing.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_release.py`

```python
RELEASE = "platform-release.yml"


def test_nothing_moves_without_a_release() -> None:
    for name in ("image", "apply", "monitoring-apply", "current", "live"):
        chain = " ".join(_conditions(RELEASE, name))
        assert "needs.release-please.outputs.release_created == 'true'" in chain, name


def test_current_moves_only_after_the_foundation_s_apply() -> None:
    current = job(RELEASE, "current")
    assert set(current["needs"]) == {"image", "apply"}
    assert "needs.apply.result == 'success'" in current["if"]
    assert job(RELEASE, "live")["needs"] == ["image", "current"]
```

`_conditions(workflow: str, name: str) -> list[str]` returns the job's `if` and the `if` of every job it needs, recursively.

Then add:
- `test_the_build_is_tagged_with_the_release_commit`: `platform-build` pushes `…:sha-${{ steps.commit.outputs.commit }}` with the `infra` apply role, in `prod`.
- `test_the_applies_run_the_release_s_build_by_digest`: `apply` and `monitoring-apply` run `platform-image` with `digest: ${{ needs.image.outputs.digest }}`, with no `tag`, and their commands.
- `test_moving_current_retags_the_build`: `move`, run with a fake `aws`, calls `batch-get-image` by digest, then `put-image` with `--image-tag current` and `--image-digest`. An `ImageAlreadyExistsException` from the fake exits 0.
- `test_live_is_fast_forwarded_by_the_release_app_and_created_once`: `move`, run with a fake `gh`, PATCHes with `force=false`. When the fake answers `Reference does not exist`, it POSTs. Any other error exits nonzero.
- On rollback:
  - `test_a_rollback_moves_current_and_live_to_a_kept_build`, with `force=true`;
  - `test_a_rollback_to_a_build_no_longer_kept_stops`;
  - `test_a_rollback_to_a_commit_not_on_main_stops`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_release.py -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write both workflows** per the Interfaces.
  - `concurrency: { group: platform-release, cancel-in-progress: false }`, and `platform-rollback` shares that group.
  - The header comment of `platform-release.yml` says:
    - the release is gated, as `jaws`'s is;
    - the order of the jobs, and why (rulings 7 and 8);
    - a failed job is re-run from the run's page.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_release.py tests/test_tool_checkout.py tests/test_owner_access.py tests/test_billing_export.py -q`
Expected: PASS

- [ ] **Step 5: Docs.** `docs/platform-workflows.md`:
  - "Releases, current and live": the jobs, the tags, the off-hours window, and the `live` ruleset;
  - "Rolling back": when, what it moves and what it doesn't apply.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/platform-release.yml .github/workflows/platform-rollback.yml tests/test_platform_release.py docs/platform-workflows.md
git commit -m "feat(workflows): release a hub's image, apply it, then move current and live"
```

---

### Task 13: the by-hand applies and the sweep

**Files:**
- Create: `.github/workflows/platform-bot-apply.yml`, `platform-databricks-apply.yml`, `platform-sweep.yml`
- Create: `tests/test_platform_applies.py`
- Modify: `docs/platform-workflows.md` ("By-hand applies and the sweep")

**Interfaces:**
- Consumes: `config projects` (Task 3), `platform apply data-access` (Task 5), `IDENTITY_WORKFLOWS` and `CHECK_PREFIX_WORKFLOWS` (Task 7), Task 8's actions.
- Produces three workflows, each `on: workflow_call` with the identity, each job in `environment: prod`, and each run on the build `current` names:
  - **`platform-bot-apply.yml`:**
    - inputs `project` (required), `destroy` (boolean, default false) and `consumer-ref` (default `""`);
    - job `apply` (`${{ inputs.destroy && 'Destroy' || 'Apply' }} ${{ inputs.project }}`), with job-level `concurrency: bot-apply-<project>`;
    - it takes `platform-role` (`role: apply`, `project: ${{ inputs.project }}`), the credentials and `platform-image`;
    - step `id: lookup` runs `config projects bot research` offline in the build, and refuses "{project} is not a bot or research project in the platform's configuration";
    - then the project file's checkout (`jaws.yaml` and `lichess`, at `consumer-ref`), and the refusal of a file that names another project, as `bot-apply.yml` does;
    - then `jaws` with `--file .consumer/jaws.yaml apply`, or `destroy --yes`, and `github-token: ${{ github.token }}`.
  - **`platform-databricks-apply.yml`:**
    - inputs `project`, and `action` (string, default `apply`);
    - step `id: action` refuses anything but `apply`, `destroy` or `doctor`;
    - the lookup is `config projects databricks`;
    - the commands are `databricks-apply.yml`'s.
  - **`platform-sweep.yml`:**
    - job `sweep` (`Data access apply`), `if: github.ref == 'refs/heads/main'`, with job-level `concurrency: { group: data-access-sweep, cancel-in-progress: false }`;
    - `platform-role` takes project `data-access`, role `apply`;
    - then `jaws` with `platform apply data-access`.

    The hub's caller holds the schedule and the dispatch.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_applies.py`

```python
def _call_inputs(path: Path) -> set[str]:
    """A reusable workflow's input names; none for a workflow nobody calls."""
    ...


def test_the_check_knows_every_workflow_that_takes_the_identity() -> None:
    """jaws platform check (Task 7) asks for exactly the inputs the workflows take."""
    takes = {path.name: _call_inputs(path) for path in sorted(WORKFLOWS.glob("*.yml"))}
    assert IDENTITY_WORKFLOWS == {name for name, i in takes.items() if "platform-image" in i}
    assert CHECK_PREFIX_WORKFLOWS == {name for name, i in takes.items() if "check-prefix" in i}


def test_the_sweep_applies_from_main_in_prod_and_never_overlaps() -> None:
    sweep = job("platform-sweep.yml", "sweep")
    assert (
        sweep["if"] == "github.ref == 'refs/heads/main'" and sweep["environment"]["name"] == "prod"
    )
    assert sweep["concurrency"] == {"group": "data-access-sweep", "cancel-in-progress": False}
```

Then add:
- `test_the_by_hand_applies_and_the_sweep_run_the_current_build`: each `platform-image` step has no `digest` and no `artifact`, so it takes `current` (spec 6.4).
- `test_a_bot_is_applied_with_its_apply_role`: `platform-role`'s `role` is `apply` and its `project` is `${{ inputs.project }}`.
- `test_a_project_that_is_not_a_bot_is_refused`: `lookup`, run with a fake `docker` printing a registry without it, stops naming the project.
- `test_the_project_file_must_name_the_project`.
- `test_a_databricks_action_is_one_of_three`: `action` with `apply`, `destroy` and `doctor` passes, and `deploy` stops.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_applies.py -v`
Expected: FAIL

- [ ] **Step 3: Write the three workflows** per the Interfaces. Their steps follow `bot-apply.yml`, `databricks-apply.yml` and `data-access.yml`'s `apply` job, which stay as they are.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_applies.py tests/test_tool_checkout.py tests/test_workflow_artifacts.py tests/test_owner_access.py tests/test_billing_export.py -q`
Expected: PASS

- [ ] **Step 5: Docs.** `docs/platform-workflows.md`, "By-hand applies and the sweep":
  - who runs each, and with which role;
  - that they use `current`;
  - that the hub's sweep starts when `jaws`'s stops (plan 07), so exactly one runs.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/platform-bot-apply.yml .github/workflows/platform-databricks-apply.yml .github/workflows/platform-sweep.yml tests/test_platform_applies.py docs/platform-workflows.md
git commit -m "feat(workflows): apply a hub's bots and databricks by hand, and sweep its data access"
```

---

### Task 14: `platform-upgrade.yml`: one pull request bumps every pin

**Files:**
- Create: `.github/workflows/platform-upgrade.yml`
- Create: `tests/test_platform_upgrade.py`
- Modify: `docs/platform-workflows.md` ("Upgrades")

**Interfaces:**
- Consumes: the `FROM` pattern of `platform-build`'s `base` step (Task 11).
- Produces `platform-upgrade.yml`, `on: workflow_call`, with the input `app-client-id` (required) and the secret `app-private-key` (required): an App with Contents, Pull requests and Workflows write (ruling 12).
- Job `upgrade` (`Upgrade Jaws`), with `permissions: { contents: read }`. The App's token does the writes. Its steps:
  1. **`app-token`:** `create-github-app-token`, with no `continue-on-error`. `GITHUB_TOKEN` can't do this job.
  2. **The checkout:** with that token.
  3. **`newest`:**
     - It reads the `Dockerfile`'s `FROM` with the pattern of Task 11's `base`, and refuses a base outside `public.ecr.aws/` with "the upgrade reads ECR Public; this Dockerfile builds FROM {name}".
     - It takes an anonymous token from `https://public.ecr.aws/token/?service=public.ecr.aws&scope=repository:<alias>/jaws:pull`.
     - It reads `https://public.ecr.aws/v2/<alias>/jaws/tags/list?n=1000`, keeps the tags matching `^v[0-9]+\.[0-9]+\.[0-9]+$`, and picks the newest by semver with jq.
     - When that isn't newer than the pin, it writes `newer=false` with a notice, "Jaws {pin} is the newest release".
     - Otherwise it writes `newer=true`, `tag`, `pin` and `digest`. The digest is the `docker-content-digest` header of a `HEAD` on `…/manifests/<tag>`, with plan 04's `MANIFEST_TYPES`.
     - A registry error stops the job.
  4. **`rewrite`,** when newer:
     - in `Dockerfile`, `sed -E` replaces `:<pin>@sha256:<64 hex>` on the `FROM` line with `:<tag>@<digest>`;
     - in each `.github/workflows/*.yml` and `*.yaml`, it replaces `(uses: Jaws-Platform/jaws/\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml)@v[0-9]+\.[0-9]+\.[0-9]+` with `\1@<tag>`;
     - it then fails unless `git diff --name-only` lists the `Dockerfile` and at least one workflow.
  5. **`pull-request`:**
     - it commits on `jaws-upgrade` (`git switch -C`) as `<app-slug>[bot]`, with the message `chore(deps): upgrade jaws to <tag>`, then runs `git push --force origin jaws-upgrade`;
     - with `gh pr list --head jaws-upgrade --state open`, it edits the open PR's title and body, or else creates one against `main`;
     - the title is the commit's. The body:
       - names both versions;
       - says one PR bumps the image and every workflow pin, and that its plans run with the candidate image for every stack and project;
       - links `https://github.com/Jaws-Platform/jaws/compare/<pin>...<tag>`.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_upgrade.py`

```python
OLD = "FROM public.ecr.aws/example-alias/jaws:v0.9.0@sha256:" + "a" * 64
NEW_DIGEST = "sha256:" + "b" * 64
CALLER = "jobs:\n  plan:\n    uses: Jaws-Platform/jaws/.github/workflows/site-plan.yml@v0.9.0\n"
OTHER = "jobs:\n  x:\n    uses: Example-Org/tools/.github/workflows/lint.yml@v0.9.0\n"


def test_a_newer_release_is_found_by_semver_not_text(tmp_path: Path) -> None:
    """v0.10.0 sorts before v0.9.0 as text."""
    (tmp_path / "Dockerfile").write_text(OLD + "\n")
    result, output = run_step(
        "platform-upgrade.yml",
        "upgrade",
        "newest",
        cwd=tmp_path,
        env={"FAKE_TAGS": "v0.8.0 v0.9.0 v0.10.0 latest v0.10.1-rc1", "FAKE_DIGEST": NEW_DIGEST},
        fakes={"curl": FAKE_CURL},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "tag=v0.10.0" in output.splitlines() and f"digest={NEW_DIGEST}" in output.splitlines()


def test_one_commit_bumps_the_dockerfile_and_every_jaws_pin(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text(OLD + "\n")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "site-plan.yml").write_text(CALLER)
    (workflows / "lint.yml").write_text(OTHER)
    _git_init(tmp_path)
    result, _ = run_step(
        "platform-upgrade.yml",
        "upgrade",
        "rewrite",
        cwd=tmp_path,
        env={"PIN": "v0.9.0", "TAG": "v0.10.0", "DIGEST": NEW_DIGEST},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "Dockerfile").read_text().strip().endswith(f":v0.10.0@{NEW_DIGEST}")
    assert "site-plan.yml@v0.10.0" in (workflows / "site-plan.yml").read_text()
    assert (workflows / "lint.yml").read_text() == OTHER
```

`FAKE_CURL` answers the token request, then the tag list from `FAKE_TAGS`, then the `HEAD` with a `docker-content-digest: $FAKE_DIGEST` header. `_git_init(path: Path) -> None` makes `path` a repository with one commit, using neutral author values as `tests/test_tool_checkout.py` does.

Then add:
- `test_nothing_happens_when_the_pin_is_the_newest`: `newer=false`, and the notice.
- `test_a_registry_error_stops_the_upgrade`: the fake `curl` exits 22, the step exits nonzero, and it writes no `tag`.
- `test_the_pull_request_is_opened_once_and_updated_after`: `pull-request`, run with fakes for `git` and `gh`, calls `gh pr create` when the list is empty and `gh pr edit` when it holds one.
- `test_the_upgrade_needs_an_app_that_may_change_workflows`: the token step has no `continue-on-error`. The workflow's comment names *Workflows: read and write*.
- `test_the_upgrade_and_the_build_read_the_same_from_line`: the `FROM` pattern in `newest` is the one in Task 11's `base`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_upgrade.py -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write the workflow** per the Interfaces. The header says:
  - why one PR bumps every pin (spec 6.4, "Dependabot would split the image and workflow bumps");
  - which App it needs;
  - that a hub schedules it hourly (ruling 12).

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_upgrade.py -q`
Expected: PASS

- [ ] **Step 5: Docs.** `docs/platform-workflows.md`, "Upgrades": what the PR changes, its App, its schedule, and what to do with a red upgrade PR. Reading its plans and the release notes, then fixing the configuration in the same PR, is one PR, as spec 6.5 asks.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/platform-upgrade.yml tests/test_platform_upgrade.py docs/platform-workflows.md
git commit -m "feat(workflows): open one pull request that bumps every jaws pin of a hub"
```

---

### Task 15: `jaws`'s own workflows pass the name root to the credential script

This is plan 02's pre-flight item G12.
- Plan 02's Task 5 has `scripts/databricks-credentials.sh` read `.context.name_root` from `tool.yaml` with yq when `databricks.secret_parameter` is unset.
- `tests/test_workflow_roles.py` forbids that in a workflow step, and the script gets past it only because it is sourced.
- The steps that source it already hold the root.

A hub's runs don't use the script (ruling 13).

**Files:**
- Modify: `scripts/databricks-credentials.sh`: its arguments, its fallback and its header comment
- Modify:
  - `.github/workflows/ci.yml`: `terraform-plan`'s `terraform plan` step;
  - `.github/workflows/release-please.yml`: `apply`'s `terraform plan` and `terraform apply` steps;
  - `.github/workflows/data-access.yml`: both jobs' `role` steps, `plan`'s `terraform plan` step and `apply`'s `Sweep` step.
- Test: `tests/test_databricks_workflows.py`, `tests/test_workflow_roles.py`

**Interfaces:**
- Consumes: plan 02's fallback to `/<name_root>/databricks/client-secret`, and its test helpers in `tests/test_databricks_workflows.py` (`_write_databricks`, `_source_credentials`).
- Produces: `source scripts/databricks-credentials.sh <config> <name_root>`.
  - When `databricks.secret_parameter` is unset, the parameter is `/<name_root>/databricks/client-secret`, built from the second argument.
  - With neither, the script returns 1 with `::error::databricks.secret_parameter is not set and no name root was passed: source databricks-credentials.sh <config> <name_root>`.
  - It no longer reads `tool.yaml`, or any `context`.
- Every sourcing step runs `source ../scripts/databricks-credentials.sh ../config "$NAME_ROOT"`, with the step env `NAME_ROOT`:
  - `${{ needs.account.outputs.name_root }}` in `ci.yml` and `release-please.yml`;
  - `${{ steps.role.outputs.name_root }}` in `data-access.yml`, which has no `account` job. Its two `role` steps also write `name_root=$name_root`.

- [ ] **Step 1: Write the failing tests**
  - In `tests/test_databricks_workflows.py`:
    - `_source_credentials` gains `name_root: str = ""`, passed as the script's second argument;
    - plan 02's `test_a_left_out_parameter_follows_the_name_root` passes `acme` that way, and writes no `context` section. It asserts the same `--name /acme/databricks/client-secret`;
    - add `test_without_a_parameter_or_a_root_the_credential_is_refused`: exit 1, the error, and no SSM call;
    - add `test_every_step_that_sources_the_credential_passes_the_name_root`. Across `.github/workflows/*.yml`, every `run` step that names `databricks-credentials.sh` sources it as above, and its `env.NAME_ROOT` is one of the two expressions.
  - In `tests/test_workflow_roles.py`, `test_no_workflow_reads_the_account_or_the_name_root_itself` also reads `scripts/databricks-credentials.sh`, which must hold no `.context.name_root`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_databricks_workflows.py tests/test_workflow_roles.py -v`
Expected: FAIL. The steps pass one argument, and the script reads `.context.name_root`.

- [ ] **Step 3: Change the script and the five steps** per the Interfaces. The header comment names both arguments.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_databricks_workflows.py tests/test_workflow_roles.py tests/test_foundation_workflows.py -q && shellcheck scripts/databricks-credentials.sh`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/databricks-credentials.sh .github/workflows/ci.yml .github/workflows/release-please.yml .github/workflows/data-access.yml tests/test_databricks_workflows.py tests/test_workflow_roles.py
git commit -m "refactor(databricks): pass the name root to the credential script instead of reading it"
```

---

### Task 16: open the pull request

- [ ] **Step 1: Bring the repository's own docs up to date**
  - **`AGENTS.md`:**
    - the CLI paragraph names `jaws platform` and `jaws config projects`;
    - a rule: the `platform-*.yml` workflows and the `platform-*` actions are a hub's. No workflow of `jaws` calls them, and no workflow, action or CLI command names `owner-access`, `billing-export` or `release-infra`.
  - **`README.md`, the Layout table:**
    - `.github/workflows/platform-*.yml`: "A hub's workflows: its pull requests, its release, rollback, by-hand applies, the data access sweep and the upgrade PR ([docs/platform-workflows.md](docs/platform-workflows.md))";
    - `.github/actions/platform-*`: "Shared steps of a hub's runs: the role, one build per run, and the build".
  - **The roadmap,** `docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md`:
    - row 05's status becomes "in its pull request";
    - rows 06 and 07 gain "For plans 06 and 07" above, in a few words each;
    - "Owner steps along the way" gains this plan's hand-offs 1 and 3.

```bash
git add AGENTS.md README.md docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md
git commit -m "docs(repo): describe the hub's workflows and add plan 05's rulings to the roadmap"
```

- [ ] **Step 2: Run the full `AGENTS.md` checklist,** verbatim. If plan 04 has merged, its `release-infra/` line follows `billing-export`'s.

```sh
terraform fmt -recursive
(cd foundation && terraform init -backend=false && terraform validate)
(cd stacks/site && terraform init -backend=false && terraform validate)
(cd stacks/bot && terraform init -backend=false && terraform validate)
(cd stacks/databricks-account && terraform init -backend=false && terraform validate)
(cd stacks/databricks-workspace && terraform init -backend=false && terraform validate)
(cd monitoring && terraform init -backend=false && terraform validate && terraform test)
(cd billing-export && terraform init -backend=false && terraform validate && terraform test)
tflint --init && tflint --recursive
npm ci && npm test && npm run test:commitlint
uv sync && uv run ruff format --check && uv run ruff check && uv run mypy && uv run pytest
scripts/test-stack-plans.sh   # plans stacks/bot and the databricks stacks against mock providers; touches no AWS
```

Then run `(cd foundation && terraform test)`.
Expected: every command passes.

- [ ] **Step 3: Push the branch and ready its PR**
  - Push with `--force-with-lease`, because the branch was rebased before Task 2.
  - Title: `feat(workflows): run project workflows from a hub's image, and add the hub's workflows`.
  - Body: `.github/pull_request_template.md`, with every section filled in.
    - It links the spec, this plan and Task 1's PR.
    - It says merging changes nothing in AWS, and that every project's pin runs as before.
    - "Why" lists the rulings marked **to confirm**, and owner hand-off 1.
    - "Verification" lists Step 2's commands and the CI plan comments.

```bash
git push --force-with-lease
gh pr edit <this PR> --title "feat(workflows): run project workflows from a hub's image, and add the hub's workflows" --body-file <file>
gh pr ready <this PR>
```

Expected:
- CI passes;
- the `Terraform plan` and every `Bot plan` comment say merging leaves AWS alone;
- the `Data access plan` shows no changes.
