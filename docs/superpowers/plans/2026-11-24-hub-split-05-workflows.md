# Jaws as a product, plan 05: workflows for the hub: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a hub run Jaws. The project-facing workflows take the hub image's repository and the platform's identity, and still run as today without them. Jaws ships the hub-facing workflows that check, plan, release, apply, sweep, roll back and upgrade a hub, with every run pinned to one image.

**Architecture:**
- **Two modes until cleanup.** With `platform-image`, `account-id` and `name-root`, a project-facing workflow:
  - derives every role ARN from the identity and the project;
  - resolves the hub image's `current` tag to one build at the job's start;
  - runs that build, either in the image or with `uv` from the pinned source, with the configuration copied out of the build.

  Without them it runs exactly as today, until plan 07 takes `config/` out of `jaws`.
- **New composite actions** carry the shared steps:
  - `platform-role` builds the role ARN from the identity;
  - `platform-image` gives a job one build, from the registry or from this run's artifact, cached per repository;
  - `platform-base` reads the `Dockerfile`'s pinned Jaws base, and `platform-build` builds the `Dockerfile`, with labels naming that base and its hub commit;
  - `platform-project-file` checks out a project's file and checks the project it names;
  - `platform-move` moves `current` and `live`.

  The `jaws` action gains `image`, the build's labels, and `github-token`.
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
- Terraform 1.14.7 (`terraform test` with mock providers); the AWS provider `>= 6.8`, which added `image_tag_mutability_exclusion_filter`.

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md):
- 6.3, the hub image's tags;
- 6.4 and 6.5, with 4.8 for the comments App;
- 6.6, the trust these workflows rely on;
- 6.7: the check names and the footer.

Roadmap: [row 05](2026-11-23-hub-split-00-roadmap.md). This plan builds on plans 02 (white-label), 03 (platform stacks) and 04 (images), merged as #324 and #317.

**Where the work happens:**
- **Task 1** is in `Jaws-Platform/terraform-aws-jaws-lichess-bot` (`~/Projects/Jaws-Platform/terraform-aws-jaws-lichess-bot`), on a branch from its `main`, with its own PR. Task 2 waits for its release, 0.2.0.
- **Tasks 2–16** are in `jaws`, on `hub-split/05-workflows`, the branch of the draft PR that holds this plan. The work lands on that PR.
  - The branch is rebased onto `main` at f191af8 (v0.81.0), after plans 02 and 04 merged. Plan 03 merged as #316.
  - Tasks 3–8 and 15 need nothing from Tasks 1–2, and can run while Task 1 is in review.

## Global Constraints

- **The repository rules (`AGENTS.md` in each repository):**
  - never push to `main`: one branch, one PR;
  - each commit is one line, `type(scope): subject`, at most 100 characters, with a lowercase subject and no trailing period;
  - only `Co-authored-by:` trailers may follow, after a blank line;
  - the PR title is a valid commit header, and the PR body fills every template section.
- **Scopes.**
  - In `jaws`, from `SCOPES`: `cli` (Tasks 3–7), `deps` and `foundation` (Task 2), `workflows` (Tasks 8 and 11–15), `sites` (Task 9), `bots` (Task 10), `repo` (Task 16).
  - In jaws-lichess-bot, the module's name: `ecr-repository`.
- **Never touch real infrastructure.** Never run:
  - `terraform apply`, or a plan against real state;
  - `jaws apply|publish|release|destroy`, or `jaws platform plan|apply` with AWS credentials;
  - `docker push`, any `aws` command, or `docker run` of a build without `--network none`;
  - a `gh` command that writes anywhere but this PR and Task 1's PR in jaws-lichess-bot. Reads, such as `gh api`, are fine.
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
- **The owner's folders.** No `platform-*` workflow or action, and no CLI command, names `owner-access`, `billing-export` or `release-infra`. Of `jaws`'s workflows, only `ci.yml` does, in the jobs that validate and test them, as `tests/test_owner_access.py`, `tests/test_billing_export.py` and `tests/test_release_infra.py` require.
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
  - Not counted, and probably a few dollars a month or less: each hub release still pulls its build, about 283 MiB, once in each repository that runs it, and once per pull request branch until `main`'s cache holds it. Each push to a hub pull request pulls the Jaws base from ECR Public, with no build cache.
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
3. **Half an identity, or a role in another account.** Examples: `platform-image` without `account-id`, `account-id` and `name-root` without `platform-image`, the account `12345678901`, or an override role in another account. Expected:
   - the job stops before any AWS call, naming the input;
   - credentials in another account stop before the pull.

   Task 8, `test_half_an_identity_stops_the_job_before_aws` and `test_a_role_in_another_account_stops_the_pull`.
4. **The sweep in an image without its datasets.** Expected: nothing is rendered or applied, and the message names the registry's path. Task 5, `test_render_refuses_a_registry_without_its_readme`.
5. **A hub whose pins or identity drift.** Examples: one caller's pin bumped by hand, a `Dockerfile` digest of another release, an identity input written as an expression. Expected: the hub's CI fails the PR, naming the file and both values. Task 7:
   - `test_a_pin_that_disagrees_fails_the_check`;
   - `test_an_image_of_another_release_fails_the_check`;
   - `test_an_identity_that_disagrees_fails_the_check`.

## Rulings

Calls this plan makes where the spec leaves them open, and the few where it departs from the spec. Those marked **to confirm** are the owner's decisions, each with the spec text it departs from or the gap it fills, and the PR lists them.

1. **Two modes until cleanup.**
   - A project-facing workflow runs the hub's way when `platform-image` is set, and today's way when it isn't. Old pins never change, and a Dependabot bump of one must still run.
   - `account-id` or `name-root` without `platform-image` is half an identity, and stops the job.
   - Plan 07 removes today's mode when `config/` leaves `jaws`.
2. **The hub's way derives every role ARN:** `arn:aws:iam::<account-id>:role/<name-root>-<project>-ci-<role>`. A site's project comes from its `jaws.yaml`.
   - The role inputs become optional overrides, which must be in `account-id`.
   - A switched project then needs no role variable (spec 6.11), and plan 07's switch PRs delete them.
3. **One build per run.**
   - The first job resolves `current`, or a release's digest, to a manifest digest with `aws ecr batch-get-image`. `ecr/pull` grants that call, but not `DescribeImages`.
   - Every later step runs the build by the image ID the runner reports, and later jobs take the digest from job outputs.
4. **Each repository pulls a build once.**
   - `platform-image` keeps `docker save` of the build in the Actions cache, keyed by the image ID the runner reports, and checks the loaded image's ID.
   - Docker's classic image store reports a build's config digest, and the containerd store, Docker 29's default on a fresh install, its manifest digest. The action accepts either and logs both.
   - Without the cache, the hub's 15-minute sweep would pull about 283 MiB 96 times a day. That is about 875 GB a month from private ECR to GitHub's runners: about $70 at $0.09 per GB past the free 100 GB.
   - With it, the sweep pulls once per hub release. The cache is free, up to 10 GB a repository.
5. **The candidate is passed between jobs, never pushed** (spec 8). An ECR push grant can't be limited by tag, so a pull request role that could push a candidate could also move `current`.
6. **The hub image's tags** (spec 6.3; plan 03's ruling 6 hands them to this plan):
   - each release build is tagged `sha-<hub commit>`, and that tag never moves;
   - `current` is the one tag that moves, by an immutability exclusion added upstream in Task 1;
   - the lifecycle keeps the newest ten `sha-` builds, never expires the build `current` names, and expires untagged images after 7 days.

   Ten builds are at most about 2.8 GB, about $0.28 a month, and less where builds share their Jaws base. **To confirm:** ten, so a rollback reaches the last ten hub releases. This fills a gap, not a departure: the spec sets no retention. Without Task 2, the module's default rule, which counts only `v` tags, would keep every build.
7. **`current` and `live` move after the foundation's apply, without waiting for monitoring's.**
   - The spec gives the reason for the timing: "at the moment the foundation has created any roles the new configuration names".
   - A failed monitoring apply holds nothing else back, as it holds back nothing of `jaws`'s release today.
   - `current` moves first, then `live`. In the seconds between, a project runs the new build with the old workflow files, never the reverse.

   **To confirm. This departs from spec 6.4,** whose release applies "the foundation, then monitoring" before it moves `current`, then `live`. The spec's own reason for the timing names only the foundation's roles.
8. **`live` is moved by a dedicated mover App that the hub supplies,** through the Git refs API (owner decision D6). A release only fast-forwards it, and the first release creates it. Only that App may update it, as the only bypass actor of `live`'s ruleset (plan 06). The release App no longer moves `live`, and holds no Workflows permission.
   - Jaws is a product other organizations use, so the workflows stay generic. `platform-release.yml` and `platform-rollback.yml` each take the input `live-app-client-id` and the required secret `LIVE_APP_PRIVATE_KEY`, a secret of the hub's `prod` environment passed under that same name (the owner's decision of 2026-11-27, ruling P5-R36), and mint the move's token from them with `create-github-app-token`.
   - For the owner's hub, the App is **JWall Engineering Deployments** (`jwall-engineering-deployments`): *Contents* and *Workflows* write and *Metadata* read, installed only on `platform`. Its key is a `platform` repository secret, and its client ID a literal in the callers. Plan 05 doesn't create it (owner hand-offs).
   - **This settles whether a branch move needs *Workflows*:** the mover App holds *Workflows: write*, so a move can't be refused for lack of it, including a move across commits that change `.github/workflows/`.
   - The release App stays **JWall Engineering Releases** (`jwall-engineering-releases`), as `organization-conventions.md` (lines 23 and 61) names it, for Release Please only. This departs from spec 7's `jwall-engineering-release-bot`, which predates that rule.
9. **A rollback moves `current` and `live` together,** to a kept build and its release commit, which must be on `main`. It applies nothing.
   - Moving `live` too keeps the workflow files and the image at one Jaws release (spec 6.4: "the hub's workflow files and its image change together").

   **To confirm. This departs from the spec twice:** 6.3 says rolling back is "pointing `current` at an earlier build", and 6.4 says only the release job may update `live`. The rollback job also moves `live`, by force, with the same mover App.
10. **The identity and the check prefix are literals in the hub's callers, checked by its CI.**
    - A project's run can read neither the hub's variables (a called workflow's `vars` are the calling repository's) nor its configuration before it has a role.
    - `jaws platform check` compares each literal with what `jaws config env` reports inside the candidate image.
    - This replaces plan 02's stated hand-off: "The hub's callers fill the input from `jaws config env --brand`, run in the hub image."

    **To confirm.** This fills a gap, not a departure: spec 6.4 says the callers "pass the hub's identity and image", but not how.
11. **One version, two pins** (spec 6.4). The same check fails a PR when any of these disagree:
    - the workflow pins;
    - the `Dockerfile`'s tag;
    - the candidate's own Jaws version.

    It also fails a `Dockerfile` that pins no digest.
12. **The upgrade PR.**
    - It reads the newest release from ECR Public's tags, anonymously. A GitHub release whose image isn't published yet is never picked.
    - It keeps one PR, on one branch, `jaws-upgrade`.
    - Changing `.github/workflows/` needs an App token with *Workflows: write*. `GITHUB_TOKEN` can't change those files, and its PRs run no CI.
    - Recommended: a dedicated App, **JWall Engineering Upgrades** (`jwall-engineering-upgrades`), installed only on `platform`. The alternative is adding Workflows to an App installed on every repository.
    - **To confirm. This is an addition to the spec,** which names only the release bot and the comments App (6.4, 7) and leaves the upgrade mechanism to the builder (8). The conventions ask for one App per purpose. It adds an owner hand-off spec 7 doesn't list.
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
    - This departs from spec 7, "set its client ID and key where each owner's callers can read them": the owners hold only the key. Spec 6.4 still holds.

## Owner hand-offs

Merging this plan changes nothing in AWS. The agent does none of these.

1. **Now, before this plan's releases: the old pins' image.** Every project's pin, `@v0.76.0`, pulls `jaws-cli:v0.76.0` in `site-plan`, `site-preview` and `site-deploy`.
   - Eight releases have followed it (v0.77.0 to v0.81.0, CHANGELOG.md), and `jaws-cli` keeps only the newest `ecr.keep_release_images` release images.
   - At about four releases a day, it expires before plan 07's switches, and those workflows then fail to pull.
   - Before then, do one of these: raise `ecr.keep_release_images` in `config/tool.yaml`, a config change still allowed before the freeze; or merge the projects' Dependabot bumps to a recent tag.
2. **Before Task 2:** merge Task 1's PR, then its Release Please PR, so that jaws-lichess-bot 0.2.0 is on the Registry. If Dependabot then opens its own bump for `foundation/`, close it: it misses `stacks/bot/` and `src/jaws/product.yaml`, which Task 2 bumps too.
3. **For the hub.** Plan 06 carries these out with the owner; nothing in this plan needs them.
   - **The comments App:** create **JWall Engineering Comments** (`jwall-engineering-comments`), owned by `JWall-Engineering`.
     - It has no webhook, only *Pull requests: read and write*, and the avatar from `jwall-engineering-branding`.
     - Install it on `platform` and on every onboarded owner: `jwallace145`, `Braveheart-Chess`, `Pi-Mathematical-Reasoning`, `Prog-Strength`.
     - Store its key where each owner's callers can read it: an organization secret in an organization, and repository secrets under `jwallace145`.
     - Give plan 06 its client ID, which the hub's callers spell.
   - **The upgrade App,** if ruling 12 is confirmed: **JWall Engineering Upgrades** (`jwall-engineering-upgrades`).
     - Its permissions are *Contents*, *Pull requests* and *Workflows*, each read and write.
     - Install it on `platform` only. Its key is an organization secret. Give plan 06 its client ID, which the hub's caller spells as a literal or a `vars.` value, since a call's `with:` can't read `secrets`.
   - **The mover App,** which the hub supplies: **JWall Engineering Deployments** (`jwall-engineering-deployments`), a mover App with *Contents* and *Workflows* write and *Metadata* read, installed only on `platform`, and `live`'s only ruleset bypass actor.
     - Its key is `LIVE_APP_PRIVATE_KEY`, a secret of `platform`'s `prod` environment, never a repository secret, so only `main`'s release and rollback can read it (the owner's decision of 2026-11-27). Give plan 06 its client ID, which the hub's callers spell as the literal `live-app-client-id`.
   - **The `live` ruleset on `platform`:** restrict updates and deletions, and block force pushes, with the mover App as the only bypass actor. The release App is not one. A rollback force-moves `live` with the mover App.
   - **The `prod` environment on `platform`,** with deployments from `main` only, holding the mover App's key. Spec 7 lists it with the `main` ruleset.
   - **Repository variables: none.** The hub's callers spell their identity, and a switched project needs no role variable (ruling 2).
   - **Secrets the hub's callers read:** the existing `RELEASE_BOT_CLIENT_ID` and `RELEASE_BOT_PRIVATE_KEY` (release only), the mover App's key (`LIVE_APP_PRIVATE_KEY`, from `prod`, release and rollback), the comments App's key, and the upgrade App's key.

## For plans 06 and 07

- **The hub's callers.** Each is a few lines calling `Jaws-Platform/jaws/.github/workflows/<name>.yml@vX.Y.Z` (`docs/platform-workflows.md`, written by Tasks 8–14).
  - Project-facing callers: `site-plan`, `site-preview`, `site-deploy`, `site-release-please`, `remote-task` and `container-release`.
  - The hub's own: `ci`, `release`, `rollback`, `bot-apply`, `databricks-apply`, `sweep` and `upgrade`.
  - Each caller that runs the image spells `platform-image`, `account-id` and `name-root`. The site callers also spell `check-prefix`. Ruling 10 covers why.
  - Each caller job grants the permissions the next level needs: `contents: read`, `id-token: write`, and `pull-requests: write` where it comments (spec 6.4). `docs/platform-workflows.md` lists each workflow's.
  - The release and rollback callers spell `live-app-client-id` as a literal (it isn't secret) and pass `LIVE_APP_PRIVATE_KEY` under that same name, from `prod`. The release caller also passes the release App's `RELEASE_BOT_*`, which the rollback doesn't take.
  - The mover App is the hub's, "a mover App with *Contents* and *Workflows* write, installed only on the hub, and `live`'s only ruleset bypass actor" (owner hand-offs).
  - No caller sets a concurrency group named `platform-release`. The release's jobs hold it (Task 12), and a caller holding it too would be cancelled as a deadlock.
- **Check names gain a level.** A project calling the hub calling Jaws reports `<project job> / <hub job> / <prefix> plan`. Each switch PR (plan 07) updates that project's required checks.
- **The hub's required checks,** as its caller reports them: `<caller job> / Platform check`, `<caller job> / Terraform plan`, `<caller job> / Monitoring plan` and `<caller job> / Data access plan`.
- **The upgrade runs hourly** (ruling 12). That is plan 04's first remedy for the retention risk.
- **Cleanup (plan 07):**
  - remove today's mode from the project-facing workflows, and the `jaws` action's `config/` steps;
  - retire `scripts/projects.sh`, `scripts/databricks-credentials.sh` and `scripts/data-access-sweep.sh` with the workflows that use them.

---

### Task 1: jaws-lichess-bot: named tags that move, and the image each one names is kept

In `Jaws-Platform/terraform-aws-jaws-lichess-bot`, branch `mutable-tags`.

**Files:**
- Modify: `modules/ecr-repository/variables.tf` (add after `release_tag_prefixes`), `modules/ecr-repository/main.tf` (the repository's mutability and the lifecycle rules), `modules/ecr-repository/versions.tf`
- Modify: `modules/ecr-repository/README.md`: its first bullet, and the regenerated inputs table
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
- `versions.tf`: aws `>= 6.8, < 7.0`. 6.8.0 added the exclusion filter and `IMMUTABLE_WITH_EXCLUSION`, and every `jaws` lock file resolves 6.73.0 or later (`release-infra/`, which calls no jaws-lichess-bot module, 6.74.0).

- [ ] **Step 1: Write the failing tests,** each a `command = plan` run:
  - `a_mutable_tag_moves_and_its_image_is_kept`, with `mutable_tags = ["current"]`, `release_tag_prefixes = ["sha-"]` and `keep_release_images = 10`:
    - the repository is `IMMUTABLE_WITH_EXCLUSION`, with one exclusion filter, `current`;
    - the policy's `[rulePriority, selection]` pairs are exactly `current` kept at 1 (`imageCountMoreThan` 1), untagged after 7 days at 2, and the newest 10 `sha-` builds at 3;
  - `no_mutable_tags_keeps_the_policy_of_0_1_4`: the defaults give `IMMUTABLE`, no exclusion filter, and exactly two rules;
  - `rejects_a_mutable_tag_that_is_a_release_tag`: `["v-latest"]`, with `expect_failures = [var.mutable_tags]`;
  - `rejects_a_wildcard_mutable_tag`: `["cur*"]`, expecting the same failure.

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/check.sh modules/ecr-repository`
Expected: FAIL. The runs fail, since the module has no `mutable_tags`.

- [ ] **Step 3: Implement the variable, the filters and the rules.** Build the rule list with `concat`, and number the rules by their index. Amend the README's first bullet: tags are `IMMUTABLE`, except those in `mutable_tags`, which may move, and the lifecycle keeps the image each one names. Regenerate the table with `terraform-docs --config .terraform-docs.yml modules/ecr-repository`.

- [ ] **Step 4: Run them and watch them pass**

Run: `scripts/check.sh`
Expected: PASS. Every existing run passes unchanged, which shows that a repository without mutable tags keeps its policy.

- [ ] **Step 5: Commit, push and open the PR,** its body `.github/pull_request_template.md`'s sections, every one filled in

```bash
git add modules/ecr-repository
git commit -m "feat(ecr-repository): let named tags move, and keep the image each one names"
git push -u origin mutable-tags
gh pr create --title "feat(ecr-repository): let named tags move, and keep the image each one names" --body-file <the filled template>
```

The owner then merges it and the Release Please PR, which gives 0.2.0: the repository bumps the minor for a `feat` before 1.0.

---

### Task 2: the hub image keeps ten builds and lets only `current` move

Wait until `curl -s https://registry.terraform.io/v1/modules/Jaws-Platform/jaws-lichess-bot/aws/versions | jq -r '.modules[0].versions[].version'` lists `0.2.0`.

**Files:**
- Modify: the four `Jaws-Platform/jaws-lichess-bot/aws` pins: `foundation/ecr.tf` (`sites_image`, `hub_image`) and `stacks/bot/main.tf` (two), with the two lock files' `constraints` lines
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
    block = _module("hub_image", REPO_ROOT / "foundation" / "ecr.tf")
    assert 'mutable_tags         = ["current"]' in block
    assert 'release_tag_prefixes = ["sha-"]' in block
    assert "keep_release_images  = 10" in block
```

Use `tests/test_bots_registry.py`'s `_module("hub_image", REPO_ROOT / "foundation" / "ecr.tf")`, which returns the block's body, rather than a new `_module_block`.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_platform_stacks.py -v`
Expected: FAIL. The block has none of the three lines.

- [ ] **Step 3: Bump the family, and commit it alone**
  - Set the four pins and the `src/jaws/product.yaml` entry to `0.2.0`.
  - Run `terraform init -backend=false` in `foundation/` and `stacks/bot/`, without `-upgrade`: 6.73.0 already meets the new floor. Each lock file's `constraints` line may change, but no provider version may: `git diff -U0 -- '*.terraform.lock.hcl' | grep -E '^[-+] +version'` prints nothing.
  - A Dependabot bump of `foundation/` alone is the owner's to close (hand-off 2).

```bash
git add foundation/ecr.tf foundation/.terraform.lock.hcl stacks/bot/main.tf stacks/bot/.terraform.lock.hcl src/jaws/product.yaml
git commit -m "chore(deps): bump jaws-lichess-bot to 0.2.0 in the stacks and the release pins"
```

- [ ] **Step 4: Set the inputs**
  - In `module "hub_image"`, set the three inputs. Their comment: each release build is `sha-<commit>`, `current` is the live one (it moves, and the lifecycle never expires it), and ten builds are kept for rollback.
  - The README's `ecr.tf` row gains "the hub image's builds (`sha-<commit>`, the newest ten kept) and `current`".

- [ ] **Step 5: Run them and watch them pass**

Run: `(cd foundation && terraform validate && terraform test) && (cd stacks/bot && terraform validate) && scripts/test-stack-plans.sh && uv run pytest tests/test_platform_stacks.py tests/test_versions.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
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
  - `HUB` and `HUB_REPOSITORY` already exist, with these values, in `tests/test_foundation_fixtures.py` (plan 03). `tests/test_one_account.py` and Task 7's tests import them from there.
  - In `tests/test_config_projects.py`:
    - `test_config_projects_lists_what_scripts_projects_sh_lists`, `@needs_yq` (from `tests/test_databricks_workflows.py`), parametrized over `["bot", "research"]`, `["databricks"]` and `["site"]`: the command's JSON equals that of `scripts/projects.sh --config <the fixture> <types>`;
    - `test_config_projects_refuses_an_unknown_type`: `app` exits 2 with "unknown project type: app".
  - In `tests/test_one_account.py`:
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
- Implementation hint: subclass `stack.Terraform` for its working copy, init, plan and apply. Take a `PlatformStack` instead of a `Target`, and override `backend()` and `_environment()` (it reads `self.site.region`). Set what `Terraform.__init__` sets (`stack_name`, `stack_dir`, `plugin_dir`, `binary`, `workdir`, `_extra_env`, `tfvars_override={}`) without calling it: it reads `site.state_key` and picks `stacks/site` for a non-`Project`. The tfvars are `{}`, and Task 5 renders data access's.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_cli.py`

Use the `fake_terraform` fixture, and `JAWS_STACKS_ROOT` pointing at a temporary directory with a `main.tf` for each of the three stacks. The tests take on a role the way `tests/test_cli.py`'s `_as_role` does.

The fixture's Databricks is ready, so every foundation and data access run reads its credential. An autouse fixture, `_no_aws`, patches `databricks_auth.load_secret` to return `"dbx-secret-value"`, unsets `AWS_PROFILE` and the AWS key variables, and points `AWS_CONFIG_FILE` and `AWS_SHARED_CREDENTIALS_FILE` at `/dev/null`. So no unit test can read a production secret.

- `test_the_backend_is_today_s_key_in_the_state_bucket`, over the three stacks: `platform_backend(load_settings(CONFIG_DIR, environ={}), platform_stack(name))` is the Interfaces' five lines, aligned as `backend/prod.hcl` is. The bucket is `jaws-terraform-state-222222222222`, and the keys are `project=infra/env=prod/infra-prod.tfstate`, `project=monitoring/env=prod/monitoring-prod.tfstate` and `project=data-access/env=prod/data-access-prod.tfstate`.
- `test_only_the_platform_s_three_stacks_run`, over `owner-access`, `billing-export`, `release-infra` and `site`: `platform plan <name>` exits 2, and the output names `foundation, monitoring, data-access`.
- `test_each_stack_runs_as_its_own_role`: `jaws-infra-ci-plan`, `jaws-infra-ci-apply`, `jaws-monitoring-ci-plan` and `jaws-data-access-ci-apply`.
- `test_plan_writes_the_comment_under_the_name_root`, with the fake's plan exiting 2:
  - exit 0, and the comment names `jaws/foundation`;
  - `GITHUB_OUTPUT` has `result=changes` and `changes=true`;
  - the fake's log has `init` with `-backend-config=backend.hcl`, and `plan` with `-detailed-exitcode`.
- `test_apply_applies_only_what_its_plan_found`, parametrized: plan exit 0 means no `apply` in the log and `result=no-changes`; plan exit 2 means `apply` of `tfplan` and `result=applied`.
- `test_the_stack_reads_the_cli_s_configuration`. The fake's environment log (`FAKE_TF_ENV`) has `TF_VAR_config_path`, the configuration's absolute path. For the foundation it also has `TF_VAR_datasets_path`, `<infra root>/datasets`.
- `test_the_databricks_credential_reaches_terraform_only`, with the fixture's Databricks and `_no_aws`'s secret:
  - the fake's environment has `DATABRICKS_CLIENT_SECRET=dbx-secret-value`;
  - with `FAKE_TF_ECHO_SECRET=1`, the value is in none of `GITHUB_OUTPUT`, `.jaws/plan.txt`, `.jaws/plan-comment.md` and `.jaws/jaws.log`.

`tests/platform/test_platform_backends.py` holds the check against the owner's configuration, `test_the_hub_s_backends_are_the_stacks_own` (spec 6.10), over `monitoring` and `data-access`:
- `hcl_text_values(platform_backend(...))` equals the values of the stack's `backend/prod.hcl`;
- for data access, today's effective backend: those values, with `bucket` the one `data-access.yml` passes as `-backend-config=bucket=`, the `state_bucket` line of `jaws config env`;
- a failure names the file, never a value. `tests/platform/test_foundation_backend.py` already checks the foundation's.

`hcl_text_values(text: str) -> dict[str, str]` joins `hcl_values` (plan 04) in `tests/workflow_steps.py`, and `hcl_values` reads its file through it.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_cli.py tests/platform/test_platform_backends.py -q`
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
- Modify: `src/jaws/access.py`: a `render_access` function, from the body of `access_render` in `src/jaws/cli.py`, and `infra_root`
- Modify: `src/jaws/cli.py` (`access_render`, and the `data-access` path of `platform plan|apply`), `src/jaws/platform.py`
- Test: `tests/test_access_cli.py`, `tests/test_platform_cli.py`, `tests/test_access_registry.py`

**Interfaces:**
- Consumes: Task 4's commands.
- `access.infra_root()` reads an empty `JAWS_INFRA_ROOT` as unset, and falls back to the configuration's directory as it does today. Task 10's workflows pass it empty outside a hub.
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

In `tests/test_access_cli.py`, `test_render_refuses_a_registry_without_its_readme`, with `selfplay_workspace` and `JAWS_INFRA_ROOT` at an empty directory: `access render --out <dir>` exits 2, its output names `<root>/datasets` and "revoked", and `<dir>` doesn't exist.

In `tests/test_access_registry.py`, `test_an_empty_infra_root_is_unset`: with `JAWS_INFRA_ROOT=""`, `infra_root()` is the configuration's parent directory.

In `tests/test_platform_cli.py`, add:
- `test_data_access_waits_for_databricks`: with `databricks.enabled` false, `plan data-access` exits 0, `GITHUB_OUTPUT` has `result=skipped`, there's no `.jaws/plan-comment.md`, and the fake terraform is never called.
- `test_the_data_access_plan_renders_against_the_base_registry`. With the registry fixture (`JAWS_INFRA_ROOT` at `tests/fixtures`) and Databricks ready:
  - the working copy's `terraform.tfvars.json` is the one `access render` writes;
  - the comment ends with the access summary;
  - a `--base-registry` that onboards a dataset the registry drops, while a handshake still names it, exits 2 before any plan.
- `test_the_sweep_summarizes_what_it_applied`: the fake's plan exits 2, and the step summary starts with `**Sweep: applied**`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_access_cli.py tests/test_platform_cli.py tests/test_access_registry.py -v`
Expected: FAIL. The render goes ahead, `data-access` has no render, and an empty root is the current directory.

- [ ] **Step 3: Implement it.** Move the body of `access_render` into `render_access`, unchanged but for the README check. Wire data access into Task 4's commands, and read an empty root as unset.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest -q && uv run mypy`
Expected: PASS. Every existing access test passes, because the registry fixture has its README.

- [ ] **Step 5: Commit**

```bash
git add src/jaws/access.py src/jaws/cli.py src/jaws/platform.py tests/test_access_cli.py tests/test_platform_cli.py tests/test_access_registry.py
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

In `tests/test_report.py`, `test_the_footer_names_the_platform_s_commit`: `PROVENANCE` with the hub commit and `HUB_URL = f"https://github.com/Example-Hub/platform/commit/{HUB_COMMIT}"` gives `preview_removed_comment(3, "a.example", provenance, brand=ACME)` a footer whose second part (split on `" &nbsp;·&nbsp; "`) is `Platform <a href="{HUB_URL}"><code>0123456</code></a>`. Plan 02's `test_the_plan_comment_s_footer_is_today_s_to_the_byte` must still pass unchanged.

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
- Modify: `src/jaws/platform.py` (the check), `src/jaws/cli.py` (`platform check`, and `config env --brand`'s help), `src/jaws/settings.py` (`BrandSection.check_prefix`'s comment)
- Create: `tests/test_platform_check.py`

**Interfaces:**
- Consumes: plan 02's `brand.check_prefix`, plan 03's `platform.hub`, and `tool_version()`.
- Produces:
  - `IDENTITY_WORKFLOWS: frozenset[str]`: `site-plan.yml`, `site-preview.yml`, `site-deploy.yml`, `remote-task.yml`, `container-release.yml`, `platform-release.yml`, `platform-rollback.yml`, `platform-bot-apply.yml`, `platform-databricks-apply.yml` and `platform-sweep.yml`.
  - `CHECK_PREFIX_WORKFLOWS: frozenset[str]`: the three site workflows. Task 13 adds the test that keeps both in step with the workflows' inputs.
  - `@dataclass(frozen=True) class HubProblem`, with `path: str` and `message: str`.
  - `FROM_PATTERN = r"^FROM ([^ @]+):(v[0-9]+\.[0-9]+\.[0-9]+)@(sha256:[0-9a-f]{64})$"`, rule 1's. `platform-base` holds it verbatim (Task 11), so the check and the build read one `FROM` alike.
  - `def check_hub(root: Path, settings: Settings, version: str, repository: str | None) -> list[HubProblem]`: nothing when the hub agrees.
- Produces `jaws platform check [--root PATH]`. `--root` defaults to `.`, and the repository is `GITHUB_REPOSITORY`.
  - It writes each problem with `annotate_error(f"{path}: {message}", title=settings.brand.name)`.
  - It exits 1 if there are any, and otherwise prints "the hub's pins and identity agree: Jaws v{version}".
- The rules and their messages, verbatim. `{expected}` is the configuration's value:
  1. The `Dockerfile`'s one `FROM` matches `FROM_PATTERN`, `<image>:v<X.Y.Z>@sha256:<64 hex>`, else: "FROM must pin the Jaws image by tag and digest (FROM public.ecr.aws/<alias>/jaws:vX.Y.Z@sha256:…), not {line!r}".
  2. The tag is `v{version}`, else: "the Dockerfile pins {tag}, but the image it built runs Jaws v{version}: its digest is another release's".
  3. Every job in `.github/workflows/*.yml` and `*.yaml` whose `uses` is `Jaws-Platform/jaws/.github/workflows/<file>@<ref>` has `ref == tag`, else: "job {job} calls Jaws-Platform/jaws at {ref}, but the Dockerfile pins {tag}: one pull request bumps every pin". With no such job: "no job calls a Jaws-Platform/jaws workflow".
  4. A call of a file in `IDENTITY_WORKFLOWS` passes `platform-image`, `account-id` and `name-root`. One in `CHECK_PREFIX_WORKFLOWS` also passes `check-prefix`. A key that is missing gives: "job {job} calls {file} without {key}: it would run as one of Jaws's own projects, not this platform's".
  5. Each key is a literal equal to the configuration's value:
     - `platform-image` is `platform.hub.image`;
     - `account-id` is `aws.account_id`;
     - `name-root` is `context.name_root`;
     - `check-prefix` is `brand.check_prefix`.

     A value that isn't a string, such as an unquoted account ID, which YAML reads as a number, gives: "job {job} passes {key} as {value!r}: pass {key} as a quoted string". A value with `${{` gives: "job {job} passes {key} as an expression: a project's run needs the platform's identity before it can read anything, so it is a literal". Any other value gives: "job {job} passes {key}: {value!r}, but the configuration says {expected!r}".
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
```

- `_hub(tmp_path: Path, ref: str = "v0.81.0", **values: str) -> Path` writes a hub checkout: a `Dockerfile` with `FROM public.ecr.aws/example-alias/jaws:v0.81.0@<DIGEST>`, and `.github/workflows/site-plan.yml` from `CALLER`, whose `image` and `account` default to `jaws-platform` and `222222222222`. `_settings() -> Settings` is the fixture's configuration with `HUB_REPOSITORY` and `HUB` (`tests/test_foundation_fixtures.py`).
- `test_a_hub_whose_pins_and_identity_agree_passes`: `check_hub(_hub(tmp_path), _settings(), "0.81.0", "Example-Hub/platform") == []`.
- `test_a_pin_that_disagrees_fails_the_check`: `ref="v0.80.1"` gives exactly one problem, at `.github/workflows/site-plan.yml`, naming `v0.80.1` and `v0.81.0`.
- `test_an_identity_that_disagrees_fails_the_check`, parametrized: `image="jaws-cli"` gives a message holding `platform-image: 'jaws-cli'`, `account="333333333333"` one holding `account-id: '333333333333'`, and `image="${{ vars.PLATFORM_IMAGE }}"` one holding `platform-image as an expression`.
- `test_an_unquoted_identity_fails_the_check`: the caller's `account-id` without its quotes gives "pass account-id as a quoted string".
- `test_a_dockerfile_without_a_digest_fails_the_check`;
- `test_an_image_of_another_release_fails_the_check`: version `0.80.1` against the tag `v0.81.0`;
- `test_a_caller_without_its_identity_fails_the_check`: the `name-root` line removed;
- `test_a_hub_configured_for_another_repository_fails_the_check`: the repository `Other-Org/platform`;
- `test_platform_check_exits_1_and_annotates_each_problem`, through the CLI with `GITHUB_ACTIONS=true`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_check.py -v`
Expected: FAIL with `ImportError: cannot import name 'check_hub'`.

- [ ] **Step 3: Implement it** per the Interfaces. Read the workflows with `yaml.safe_load`, and list each problem once, in file order.
  - Both `BrandSection.check_prefix`'s comment and `config env --brand`'s help say nothing reads the prefix yet. Now `jaws platform check` holds each hub caller's `check-prefix` to it, and the site workflows take it as their `check-prefix` input; say that instead.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_check.py -q && uv run mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jaws/platform.py src/jaws/cli.py src/jaws/settings.py tests/test_platform_check.py
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
  - `def run_action_step(action: str, step_id: str, *, cwd: Path, env: Mapping[str, str], fakes: Mapping[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], str]`. It is `run_step`'s mechanism for a composite action's step. It runs the step as Actions runs a composite `shell: bash` step, `bash --noprofile --norc -eo pipefail -c`, not `run_step`'s `bash -e -c`.
- Produces `.github/actions/platform-role`, which makes no AWS call.
  - Inputs: `platform-image`, `account-id`, `name-root` and `role` (one of `plan`, `preview`, `apply`, `release` and `task`), all required; `project` (default `""`, read from `project-file` then); `project-file` (default `jaws.yaml`); `role-arn` (default `""`, an override).
  - Its one step, `id: arn`, takes the inputs as `PLATFORM_IMAGE`, `ACCOUNT_ID`, `NAME_ROOT`, `ROLE`, `PROJECT`, `PROJECT_FILE` and `ROLE_ARN`.
    - It refuses, naming the input: an empty platform image, so half an identity never reaches AWS; an account that isn't 12 digits; a name root or project that isn't lowercase kebab-case; an unknown role; and an override that isn't `arn:aws:iam::<account-id>:role/…`.
    - It writes `arn=`: the override, else `arn:aws:iam::<account-id>:role/<name-root>-<project>-ci-<role>`.
  - Output: `arn`.
- Produces `.github/actions/platform-image`. The job has already assumed a role.
  - Inputs: `account-id` and `repository`; `tag` (default `current`) or `digest` (a manifest digest, from another job of the run); or `artifact` with `image-id`, this run's candidate (Task 11); and `extract` (default `""`: a directory to copy `/etc/jaws/config` and `/etc/jaws/datasets` into).
  - A build's image ID is the one the runner reports, `docker image inspect --format '{{.Id}}'`: its config digest with Docker's classic store, its manifest digest with the containerd store.
  - Its steps, by id. For an artifact, only `artifact`, `extract` and `labels` run.
    1. `ecr` (`amazon-ecr-login`), and `account`, which refuses a role outside `account-id`.
    2. `resolve`, `aws ecr batch-get-image` by `imageTag=<tag>` or `imageDigest=<digest>`. It writes `digest`, `config-digest` (the manifest's `config.digest`) and `reference` (`<registry>/<repository>@<digest>`). With no image it stops with "{repository}:{tag} does not exist", adding ": the hub's first release tags its build current" for `current`.
    3. `artifact`, for an artifact only: `download-artifact` of `platform-image`, the file `platform-image.tar`, then `docker load`. A loaded ID other than `image-id` stops with "the platform-image artifact holds {loaded}, not the candidate {image-id}".
    4. `cache`, `actions/cache/restore`, keyed `platform-image-<config-digest>`, with the restore key `platform-image-<digest>`.
    5. `load`: a restored build is `docker load`ed, and kept when its ID is `config-digest` or `digest`. Otherwise it runs `docker pull <reference>`, then `docker save`. It writes `image-id`, and logs it with both digests, so the first real run shows which store the runner has.
    6. `save`, `actions/cache/save` keyed `platform-image-<image-id>`, after a pull.
    7. `extract`, with `docker create`, `docker cp` and `docker rm`; then `labels`.

    Pin `actions/cache` at the major `gh api repos/actions/cache/releases/latest --jq .tag_name` names.
  - Outputs: `image-id` (`steps.load.outputs.image-id || inputs.image-id`); `digest` and `reference`, empty for an artifact; `platform-commit` and `platform-source` (the labels `org.opencontainers.image.revision` and `.source`); `config` and `infra-root` (`<extract>/config` and `<extract>`).
- Produces in `.github/actions/jaws`:
  - `role-arn` becomes optional;
  - new inputs: `image`, an image ID the job resolved and pulled; `platform-commit` and `platform-source`, passed as `JAWS_PLATFORM_COMMIT` and `JAWS_PLATFORM_SOURCE`; and `github-token`, passed to the CLI as `GH_TOKEN`. A job that passes `image` passes the two labels from the same `platform-image` step (Tasks 9 and 11–13);
  - a new first step, `id: check`, with no `if`: without `role-arn` or `image` it stops with "the jaws action needs role-arn, or an image the job already pulled";
  - today's three steps, the credentials (given `id: credentials`), `ecr` and `image`, take `if: inputs.image == ''`. With `image`, the action assumes no role, logs in nowhere, reads no `config/` and pulls nothing.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_actions.py`

The `platform-role` tests run `arn` with `run_action_step`, beside a `jaws.yaml` naming `guitar-knowledge-base`, with `PLATFORM_IMAGE=jaws-platform`, `ACCOUNT_ID=123456789012`, `NAME_ROOT=jaws`, `ROLE=plan`, `PROJECT=""`, `PROJECT_FILE=jaws.yaml` and `ROLE_ARN=""`:
- `test_the_role_comes_from_the_identity_and_the_project_file`: the output is exactly `arn=arn:aws:iam::123456789012:role/jaws-guitar-knowledge-base-ci-plan`.
- `test_half_an_identity_stops_the_job_before_aws`, parametrized over an empty `PLATFORM_IMAGE`, an empty `ACCOUNT_ID`, `ACCOUNT_ID=12345678901`, `NAME_ROOT=Jaws`, `ROLE=admin`, `PROJECT=Not_Kebab` and `ROLE_ARN=arn:aws:iam::111122223333:role/jaws-site-ci-plan`: each exits nonzero, with `::error::<the input's name>` and no output.

The `platform-image` step tests use `fakes` for `aws` and `docker`. Each fake logs its calls to `FAKE_LOG`, and the fake `aws` answers `batch-get-image` from `FAKE_IMAGES`:
- `test_current_is_resolved_to_one_build`. `resolve` writes `digest=sha256:bbb…`, `config-digest=sha256:ccc…` (the fake manifest's `config.digest`) and `reference=123456789012.dkr.ecr.us-east-1.amazonaws.com/jaws-platform@sha256:bbb…`. The log has `--image-ids imageTag=current`.
- `test_a_digest_another_job_resolved_is_used_as_given`: the log has `imageDigest=sha256:bbb…` and no `imageTag`.
- `test_no_build_tagged_current_stops_the_job`: an empty `images`, with an `ImageNotFound` failure. The step stops, and its error says the first release tags it.
- `test_a_role_in_another_account_stops_the_pull`: `account` with the caller in `111122223333` stops with `::error::`, and nothing is pulled.
- `test_a_cached_build_is_loaded_in_either_image_store`, parametrized over the fake `docker image inspect` answering `sha256:ccc…` (classic) and `sha256:bbb…` (containerd): `load`, with a restored tar, pulls nothing and writes that `image-id`.
- `test_a_cached_build_with_another_id_is_pulled_again`: with any other ID, `load` runs `docker pull <reference>` and `docker save`.
- `test_the_candidate_is_loaded_from_this_run_s_artifact`: `artifact` passes when the loaded ID is `image-id`, and otherwise stops with its message.
- `test_the_configuration_is_copied_out_of_the_build`: `extract` copies `/etc/jaws/config` and `/etc/jaws/datasets` into `<extract>/config` and `<extract>/datasets`, then removes the container.
- `test_the_build_is_resolved_once_and_run_by_its_id`, in both modes: the outputs are `steps.load.outputs.image-id || inputs.image-id` and `steps.resolve`'s `digest` and `reference`; with an artifact, every step but `artifact`, `extract` and `labels` is skipped; and the `jaws` action's run step pulls nothing when `IMAGE` is set.
- `test_no_hub_workflow_or_action_spells_a_name_the_root_derives`. It reads every `.github/workflows/platform-*.yml` and `.github/actions/platform-*/action.yml`, including those later tasks add. None holds `.context.name_root`, `/jaws/databricks/`, `/jaws/monitoring/`, `jaws-infra-ci-`, `jaws-monitoring-ci-` or `jaws-data-access-ci-`. Each name comes from the configuration in the image, or from the identity inputs. The image's own paths, `/etc/jaws` and `/opt/jaws`, are Jaws's (spec 6.7).

In `tests/test_jaws_action.py`, add:
- `test_without_an_image_the_action_runs_as_today`: `credentials`, `ecr` and `image` take `if: inputs.image == ''`, `check` takes no `if`, and `IMAGE_TAG` keeps `# x-release-please-version`. The existing tests pass unchanged.
- `test_the_action_needs_a_role_or_an_image`: `check`, with neither, stops with its message.
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

  Later tasks add the other sections, each with its workflows' inputs and the permissions their callers grant.

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
- Consumes: `platform-role`, `platform-image`, and the `jaws` action's `image`, `platform-commit` and `platform-source` (Task 8).
- Produces, on each of the three workflows:
  - new inputs `platform-image`, `account-id` and `name-root` (string, default `""`), and `check-prefix` (string, default `jaws`);
  - `plan-role-arn`, `preview-role-arn` and `apply-role-arn` become `required: false` with default `""`. Each description says it's needed without `platform-image`, and with it is an override in `account-id`.
- The job names, per plan 02's decision: `${{ inputs.check-prefix }} plan`, `${{ inputs.check-prefix }} preview deploy`, `${{ inputs.check-prefix }} preview remove` and `${{ inputs.check-prefix }} release`.
- Each job's new steps, after the tool checkout's verify step:
  1. `id: role`, `uses: ./.jaws-tool/.github/actions/platform-role`.
     - `if: inputs.platform-image != '' || inputs.account-id != '' || inputs.name-root != ''`.
     - It takes the three identity inputs, so half an identity stops here. `role` is `plan`, `preview` or `apply`, and `role-arn` is the job's role input.
  2. `aws-actions/configure-aws-credentials@v6`, `if: steps.role.outputs.arn != ''`.
  3. `id: image`, `uses: ./.jaws-tool/.github/actions/platform-image`, under the same `if`, with `repository: ${{ inputs.platform-image }}`.
- Each `jaws` action step takes:
  - `role-arn: ${{ steps.role.outputs.arn == '' && inputs.<role input> || '' }}`;
  - `image`, `platform-commit` and `platform-source`, from `steps.image.outputs`.
- The descriptions of `app-client-id` and `app-private-key` say "the platform's comments App" in place of "the Jaws GitHub App".
- The step `Mint a comment token for the Jaws app`, in all three jobs that post, becomes `Mint a comment token for the comments App`, and site-plan.yml's header comment says the platform's comments App.
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
```

Each test is parametrized over `JOBS`:
- `test_the_check_names_take_the_prefix_and_keep_today_s_by_default`: the job's `name` is `${{ inputs.check-prefix }} <rest>`, and `check-prefix` defaults to `jaws`.
- `test_a_site_job_resolves_the_platform_image_once`: one `platform-image` step, before every `jaws` step, and each `jaws` step takes `image`, `platform-commit` and `platform-source` from `steps.image.outputs`.
- `test_each_site_workflow_takes_the_platform_s_identity`. The three inputs default to `""`, and each role input is `required: False` with default `""`.
- `test_in_a_hub_the_role_comes_from_the_identity`:
  - the `platform-role` step takes the three identity inputs, and its `role` and `role-arn` are `SITE_JOBS`'s;
  - `configure-aws-credentials` and `platform-image` take `if: steps.role.outputs.arn != ''`;
  - the credentials use `steps.role.outputs.arn`.
- `test_without_a_platform_image_a_site_job_runs_as_today`:
  - `platform-role`'s `if` names all three inputs;
  - each `jaws` step's `role-arn` falls back to the job's role input;
  - the tool checkout and its verify step come first, unchanged (`tests/test_tool_checkout.py` already checks them).

In `tests/test_workflow_roles.py`, the module docstring becomes: every workflow builds its roles from the tool's reading of its configuration (`config/`), or, in a hub's run, from the platform's identity through `platform-role`. `jaws platform check` holds that identity to the configuration (Task 7). It keeps plan 04's last sentence: the one exception is the public image job's `vars.JAWS_PUBLISH_ROLE_ARN` (spec 6.8).

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
- Modify: `tests/test_bots_registry.py` (`test_container_release_runs_this_commit_and_pins_nothing`: assert `'--config "$JAWS_TOOL_CONFIG"'` in place of `"--config .jaws-tool/config "`, and its input set gains `platform-image`, `account-id` and `name-root`)
- Create: `tests/test_container_release_workflow.py`
- Modify: `docs/remote-tasks.md`, `docs/lichess-bot.md` (each one's caller section), `docs/platform-workflows.md`

**Interfaces:**
- Consumes: Task 8's actions, and Task 5's `infra_root()`.
- Produces, in both workflows:
  - new inputs `platform-image`, `account-id` and `name-root` (default `""`);
  - a job `env` entry, `JAWS_TOOL_CONFIG: ${{ inputs.platform-image != '' && '.jaws-platform/config' || '.jaws-tool/config' }}`;
  - every CLI call spells `--config "$JAWS_TOOL_CONFIG"` in place of `--config .jaws-tool/config`.
- `remote-task.yml`'s `role` step becomes:
  - `platform-role`, `id: platform`, under the identity `if` (Task 9's), with the identity, `role: task` and `project: ${{ inputs.project }}`;
  - then the existing step, which keeps `id: role`. Its `arn` is `$PLATFORM_ARN` (`steps.platform.outputs.arn`) when set. Otherwise it builds the ARN from `jaws config env`, as today. It computes `duration` in both cases.
- `remote-task.yml`'s job `CLI` goes. The cleanup step, given `id: terminate`, runs `.jaws-tool/.venv/bin/jaws --config "$JAWS_TOOL_CONFIG" task terminate …` itself. A job's `env` can't read `env`, and an unquoted `$CLI` holding `"$JAWS_TOOL_CONFIG"` would pass that text, quotes and all, so the backstop would never terminate.
- In `container-release.yml`:
  - `platform-role`, `id: platform`, takes the identity, `role: release`, `project: ${{ inputs.project }}` and `role-arn: ${{ inputs.release-role-arn }}`;
  - the existing `role` step runs only when `steps.platform.outputs.arn` is empty;
  - the credentials assume `${{ steps.platform.outputs.arn || steps.role.outputs.arn }}`.
- After the credentials step, both run `platform-image` (`id: image`) with `extract: .jaws-platform`, under `if: steps.platform.outputs.arn != ''`.
- The steps that run the CLI get `JAWS_INFRA_ROOT`, `JAWS_PLATFORM_COMMIT` and `JAWS_PLATFORM_SOURCE` from its outputs. Outside a hub they're empty, which `infra_root()` (Task 5) and `provenance()` (Task 6) read as unset.
- `remote-task.yml` still names no `github.token` and no `secrets.`, and its checkouts still don't persist credentials.

- [ ] **Step 1: Write the failing tests**

In `tests/test_remote_task_workflow.py`:
- `test_it_is_reusable_with_the_planned_inputs`'s set gains `platform-image`, `account-id` and `name-root`.
- `test_runs_the_cli_from_this_workflow_commit` asserts these, in place of `--config .jaws-tool/config `:
  - `'--config "$JAWS_TOOL_CONFIG"'` appears in the text, and `--config .jaws-tool/config` doesn't;
  - the job's `JAWS_TOOL_CONFIG` is the expression above, and the job has no `CLI`.
- Add `test_the_cleanup_terminates_with_the_job_s_configuration`: `terminate`, run with `JAWS_TOOL_CONFIG=.jaws-platform/config` and a fake `.jaws-tool/.venv/bin/jaws` that logs its arguments, passes it `--config .jaws-platform/config task terminate`.
- Add `test_in_a_hub_the_task_role_comes_from_the_platform_s_identity`:
  - `platform-role`'s `with` is the identity, `role: task` and `project: ${{ inputs.project }}`;
  - `role`'s script uses `$PLATFORM_ARN` when set, and calls `config env` only otherwise;
  - the credentials keep `role-duration-seconds`.
- Add `test_in_a_hub_the_cli_reads_the_platform_image_s_configuration`. `platform-image` comes between the credentials and `jaws task run`, with `extract: .jaws-platform`. The task step's `JAWS_INFRA_ROOT` is `${{ steps.image.outputs.infra-root }}`.
- Add `test_without_a_platform_image_a_task_runs_as_today`. Run the `role` step with `PLATFORM_ARN=""` and a fake `uv` whose `run --no-dev --project .jaws-tool jaws --config … config env` prints the fixture's lines, with `MAX_HOURS=1`, or a `jaws.yaml` and `@needs_yq`. The result is `arn=arn:aws:iam::222222222222:role/jaws-braveheart-ci-task`, with a duration.

`tests/test_container_release_workflow.py` tests `container-release.yml`'s own design:
- `test_it_takes_the_platform_s_identity`: the three inputs, each defaulting to `""`.
- `test_in_a_hub_the_release_role_comes_from_the_platform_s_identity`: `platform-role`'s `with` is the identity, `role: release`, `project: ${{ inputs.project }}` and `role-arn: ${{ inputs.release-role-arn }}`. `role` takes `if: steps.platform.outputs.arn == ''`, and the credentials assume `${{ steps.platform.outputs.arn || steps.role.outputs.arn }}`.
- `test_in_a_hub_the_cli_reads_the_platform_image_s_configuration`: `platform-image` comes between the credentials and `jaws bot reconcile`, with `extract: .jaws-platform`. The reconcile step spells `--config "$JAWS_TOOL_CONFIG"`, and its `JAWS_INFRA_ROOT` is `${{ steps.image.outputs.infra-root }}`.
- `test_without_a_platform_image_a_release_runs_as_today`: `role`, run with a fake `uv` whose `run --no-dev --project .jaws-tool jaws --config … config env` prints the fixture's lines, gives `arn=arn:aws:iam::222222222222:role/jaws-braveheart-ci-release`, and the override when `OVERRIDE` is set.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_remote_task_workflow.py tests/test_container_release_workflow.py -v`
Expected: FAIL

- [ ] **Step 3: Change both workflows** per the Interfaces. Keep the `exec` of the CLI, which `jaws task run`'s signal handling needs.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_remote_task_workflow.py tests/test_container_release_workflow.py tests/test_bots_registry.py tests/test_tool_checkout.py tests/test_workflow_roles.py -q`
Expected: PASS

- [ ] **Step 5: Docs.** Each caller section in `docs/remote-tasks.md` and `docs/lichess-bot.md` gains: in a hub, call the hub's copy at `@live`, which spells the identity. In `docs/platform-workflows.md`, "Project-facing workflows" adds both workflows and why they run from source (ruling 14).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/remote-task.yml .github/workflows/container-release.yml tests/test_remote_task_workflow.py tests/test_container_release_workflow.py tests/test_bots_registry.py docs
git commit -m "feat(bots): run remote tasks and bot releases with a hub's configuration"
```

---

### Task 11: `platform-ci.yml`: a hub's pull requests

**Files:**
- Create: `.github/actions/platform-base/action.yml`, `.github/actions/platform-build/action.yml`, `.github/actions/platform-project-file/action.yml`, `.github/workflows/platform-ci.yml`
- Create: `tests/test_platform_ci.py`
- Modify: `docs/platform-workflows.md` ("The hub's pull requests")

**Interfaces:**
- Consumes:
  - `config env --platform` and `config projects` (Task 3);
  - `platform plan` (Tasks 4–5), and `platform check`, `FROM_PATTERN` and rule 1's message (Task 7);
  - Task 8's actions.
- Produces `.github/actions/platform-base`. Its step, `id: base`, matches the `Dockerfile`'s one `FROM` with `FROM_PATTERN`, refuses anything else with rule 1's message, and writes the outputs `base-name`, `base-tag` and `base-digest`. A job that builds runs it first, and so does the upgrade (Task 14).
  - A second step, `id: present` (skipped by the upgrade), asks ECR Public anonymously whether the pinned digest still exists. It uses plan 04's token and `HEAD /v2/<repository>/manifests/<digest>` calls, with the same `Accept` types.
    - A 404 fails the job with the following message, naming the base by tag and digest: `::error::the Dockerfile's Jaws base <base-name>:<base-tag>@<base-digest> is no longer in ECR Public, which keeps only the newest versions until v1: merge the open upgrade PR, or move the FROM line to a recent Jaws release`.
    - Any other status than 200 or 404 fails with `::error::could not tell whether the Jaws base is still published (HTTP <code> from public.ecr.aws)`.
    - The owner confirmed (2026-11-24) that during development they bump the pin by hand when this fires, so the message must say exactly what to do.
  - Its tests, with a fake `curl`:
    - `test_a_pruned_base_fails_naming_the_fix`: a 404 exits nonzero, and the message names the tag, the digest and "merge the open upgrade PR".
    - `test_a_published_base_passes`: a 200 exits 0.
    - `test_a_registry_error_names_the_status`: a 503 exits nonzero naming `503`.
- Produces `.github/actions/platform-build`.
  - Inputs: `load` and `push` (each `"true"` or `"false"`, independent: buildx loads and pushes one build), `tags` (for a push), `revision` (the hub commit), and `base-name`, `base-tag` and `base-digest`.
  - Its steps: `setup-buildx`, then `build-push-action` (`id: build`):
    - `context: .`, `platforms: linux/amd64`, `provenance: false`;
    - the labels `org.opencontainers.image.revision=<revision>`, `org.opencontainers.image.source=${{ github.server_url }}/${{ github.repository }}`, `org.opencontainers.image.base.name=<base-name>:<base-tag>` and `org.opencontainers.image.base.digest=<base-digest>`.
  - Outputs: `image-id`, the loaded build's ID as the runner reports it (Task 8), and `digest`, the pushed manifest's (empty without a push).
- Produces `.github/actions/platform-project-file`, with the inputs `project`, `repository`, `ref` (default `""`) and `on-mismatch` (`skip` or `refuse`).
  - It checks out the project's `jaws.yaml` and `lichess` into `.consumer`, as `bot-apply.yml` does.
  - Its step `id: names` writes the output `matches`. When the file names another project, `refuse` stops with "the project file names '{named}', not '{project}'; pass consumer-ref for a ref whose file names {project}", and `skip` warns "the project file names '{named}', not '{project}'; the plan for {project} is skipped", with a step summary.
- Produces `platform-ci.yml`, `on: workflow_call`.
  - Input: `app-client-id` (default `""`). Secret: `app-private-key` (optional).
  - Top-level `permissions: {}`.
  - Each job checks out the tool at its own commit and verifies it (`tests/test_tool_checkout.py`'s pattern).
  - Jobs:

| Job (`name`) | Does |
|---|---|
| `candidate` (`Platform check`) | builds the PR head (`platform-base`, then `platform-build` with `load: "true"`, `push: "false"` and `revision: ${{ github.event.pull_request.head.sha }}`). Offline (`docker run --rm --network none`), it runs `config show > /dev/null`, a validation only, since the hub's logs are public; `platform check --root /hub` (the checkout mounted read-only at `/hub`, never at the image's working directory `/work`, which the CLI writes `.jaws/` into; with `GITHUB_REPOSITORY`); `config env --monitoring --databricks --brand --platform` into `GITHUB_OUTPUT`; and `config projects site bot research databricks` as `projects`. It saves the image as the artifact `platform-image`, the file `platform-image.tar` (`retention-days: 1`), and outputs `image-id`, `account_id`, `name_root`, `monitoring`, `databricks`, `platform_image` and `projects` |
| `foundation` (`Terraform plan`) | `platform-role` (project `infra`, role `plan`), the credentials, `platform-image` with `artifact` and `image-id`, then `jaws` with `command: platform plan foundation`. Comment header `terraform-plan` |
| `monitoring` (`Monitoring plan`) | with `monitoring == 'configured'` and the PR from this repository: the same, with project `monitoring`. Until its role exists, the credentials step (`continue-on-error`) leads to a notice and a skip, as `ci.yml` does today. Header `monitoring-plan` |
| `data-access` (`Data access plan`) | not for Dependabot: checks out the base's `datasets` into `.base`, then runs `platform plan data-access --base-registry .base/datasets`, with `github-token: ${{ github.token }}`. Header `data-access-plan` |
| `projects` (`${{ matrix.type == 'databricks' && 'Databricks' \|\| matrix.type == 'site' && 'Site' \|\| 'Bot' }} plan (${{ matrix.project }})`) | when `projects != '[]'`, over its matrix (`fail-fast: false`). It skips a Databricks project while `databricks == 'disabled'`. It takes the project's file with `platform-project-file` (`on-mismatch: skip`), then the project's plan role, skipping with a warning until it exists. It runs `--file .consumer/jaws.yaml plan` with `github-token: ${{ github.token }}`. Header `<databricks\|site\|bot>-plan-<project>` |

  - The jobs that need AWS have `id-token: write`, and the ones that comment have `pull-requests: write`.
  - Each comment step mints `inputs.app-client-id`'s token with `continue-on-error: true`, and posts with `steps.app-token.outputs.token || github.token`.
  - Each job uploads `.jaws/` with `include-hidden-files: true`.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_ci.py`, where the plan jobs are `foundation`, `monitoring`, `data-access` and `projects`:
- `test_the_candidate_is_built_once_and_passed_to_every_plan`: `candidate` uploads the artifact `platform-image` with `retention-days: 1`. Each plan job needs `candidate`, and runs `platform-image` with `artifact: platform-image` and `image-id: ${{ needs.candidate.outputs.image-id }}`.
- `test_no_pull_request_job_can_push_or_move_current`: the workflow's text holds none of `amazon-ecr-login`, `put-image`, `docker push`, `push: true`, `push: "true"` and `ci-apply`.
- `test_the_hub_is_checked_inside_its_candidate`. The `candidate` job's run steps hold the four offline commands, each with `--network none`. `config show` writes to `/dev/null`, and `platform check` runs with the checkout mounted `:ro` at a path other than `/work`, which its `--root` names.
- `test_every_platform_stack_and_project_is_planned`:
  - the names and commands of the table;
  - the `projects` job's matrix is `fromJSON(needs.candidate.outputs.projects)`, under `if: needs.candidate.outputs.projects != '[]'`.
- `test_each_plan_assumes_its_own_plan_role`. `platform-role`'s `project` is `infra`, `monitoring`, `data-access` or `${{ matrix.project }}`. Its `role` is `plan`, and its identity comes from `needs.candidate.outputs`.
- `test_the_project_file_reads_carry_a_token`: the `jaws` steps of `data-access` and `projects` take `github-token: ${{ github.token }}`.
- `test_the_comments_come_from_the_platform_s_app_or_github_actions`: each job that posts mints a token with `create-github-app-token` from `inputs.app-client-id` and `secrets.app-private-key`, under `continue-on-error: true`, and posts with `steps.app-token.outputs.token || github.token`.
- On the actions:
  - `test_the_build_records_its_jaws_release_and_hub_commit`: `platform-build`'s four labels;
  - `test_the_base_must_be_pinned_by_tag_and_digest`: `platform-base`'s `base`, run with `run_action_step`, accepts `FROM public.ecr.aws/example-alias/jaws:v0.81.0@sha256:aaa…`, and refuses no digest, two `FROM`s and `:latest`;
  - `test_the_base_is_read_as_the_check_reads_it`: `base` holds `FROM_PATTERN` verbatim;
  - `test_a_project_file_that_names_another_project_is_skipped_or_refused`: `names`, run with a `.consumer/jaws.yaml` naming `other`, warns and writes `matches=false` with `skip`, and exits 1 with `refuse`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_ci.py -v`
Expected: FAIL with `FileNotFoundError` for `platform-ci.yml`.

- [ ] **Step 3: Write the three actions and the workflow** per the Interfaces. The workflow's header comment says what a hub's PR runs, that the candidate is passed between jobs and never pushed (ruling 5), that every plan runs with it (spec 6.3, 6.5), and what the caller passes.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_ci.py tests/test_tool_checkout.py tests/test_repository_name.py tests/test_workflow_artifacts.py tests/test_owner_access.py tests/test_billing_export.py tests/test_release_infra.py -q`
Expected: PASS

- [ ] **Step 5: Docs.** `docs/platform-workflows.md`, "The hub's pull requests":
  - the jobs and their checks, which are the hub's required checks, as `<caller job> / <check>`;
  - the candidate;
  - what the check holds (rulings 10 and 11);
  - the site plans, which the site plan roles trust the hub for (spec 6.5, 6.6);
  - the caller, with placeholders.

- [ ] **Step 6: Commit**

```bash
git add .github/actions/platform-base .github/actions/platform-build .github/actions/platform-project-file .github/workflows/platform-ci.yml tests/test_platform_ci.py docs/platform-workflows.md
git commit -m "feat(workflows): plan every stack and project of a hub with its candidate image"
```

---

### Task 12: `platform-release.yml` and `platform-rollback.yml`

**Files:**
- Create: `.github/actions/platform-move/action.yml`, `.github/workflows/platform-release.yml`, `.github/workflows/platform-rollback.yml`
- Create: `tests/test_platform_release.py`
- Modify: `docs/platform-workflows.md` ("Releases, current and live", "Rolling back")

**Interfaces:**
- Consumes: `platform apply` (Task 4); `platform-role` and `platform-image` (Task 8); `platform-base` and `platform-build` (Task 11); the tags (Task 2).
- Produces `.github/actions/platform-move`, which both workflows use. Inputs: `move` (`current` or `live`); `repository` (the hub image's), `digest` and `commit`; `token` (the mover App's, for `live`; the step reads it from there, never from the release App); and `force` (default `"false"`).
  - Step `id: current`: `batch-get-image` by digest for the manifest, then `put-image --image-tag current` with it. `ImageAlreadyExistsException` means `current` already names the build, a success. Its summary: "`current` is `<repository>@<digest>` (`sha-<commit>`)".
  - Step `id: live`: a `PATCH` of `repos/$GITHUB_REPOSITORY/git/refs/heads/live` with `sha=$COMMIT` and `force=$FORCE`. When the ref doesn't exist yet (`Reference does not exist`), it POSTs `refs/heads/live`. Any other failure stops the job, naming `live` and the commit.
- Produces `platform-release.yml`, `on: workflow_call`, with inputs `platform-image`, `account-id` and `name-root` (required), the required input `live-app-client-id` (string), and the required secrets `RELEASE_BOT_CLIENT_ID` and `RELEASE_BOT_PRIVATE_KEY` (Release Please's) and `LIVE_APP_PRIVATE_KEY` (the mover App's: a secret of the hub's `prod` environment, passed under that same name). Its jobs, where `<tag_name>` is `${{ needs.release-please.outputs.tag_name }}`, and `<tag>`, after `image`, is `${{ needs.image.outputs.tag }}`, its copy:

| Job (`name`) | Needs, condition | Does |
|---|---|---|
| `release-please` (`Release Please`) | `github.event_name == 'push'` | as `release-please.yml`'s, with the release App's token, but with `permissions: { contents: read }`: the token does the writes, and a called job can't ask for more than its caller grants. Outputs `release_created` and `tag_name` |
| `image` (`Build the platform image (<tag_name>)`) | `release_created == 'true'`; `environment: prod` | checks out `refs/tags/<tag_name>`, and its step `id: commit` writes `commit=$(git rev-parse HEAD)`. It takes `platform-role` (project `infra`, role `apply`) and the credentials, then `amazon-ecr-login`. Step `id: built` looks up `sha-<commit>` first: a re-run finds its own build, skips the build and the push, and pulls it with `platform-image` (`digest`). Otherwise `platform-base`, then `platform-build` with `load: "true"`, `push: "true"`, `tags: <registry>/<platform-image>:sha-<commit>` and `revision: <commit>`. Outputs `tag`, `commit`, `digest` (the kept build's, or the push's), and `monitoring` (`config env --monitoring`, run offline in the build) |
| `apply` (`Terraform apply (<tag>)`) | `image`; `prod` | `platform-role` (`infra`, `apply`) and the credentials, `platform-image` with `digest: ${{ needs.image.outputs.digest }}`, then `platform apply foundation` |
| `monitoring-apply` (`Monitoring apply (<tag>)`) | `image`, `apply`; `needs.image.outputs.monitoring == 'configured'`; `prod` | the same, with project `monitoring`, then `platform apply monitoring` |
| `current` (`Move current to <tag>`) | `image`, `apply`; `needs.apply.result == 'success'`; `prod` | `platform-role` (`infra`, `apply`) and the credentials, then `platform-move` with `move: current` |
| `live` (`Move live to <tag>`) | `image`, `current` | in `prod`, for the mover App's key: step `id: live-key` stops on an empty key, then step `id: live-token` mints the mover App's token with `create-github-app-token` from `inputs.live-app-client-id` and `secrets.LIVE_APP_PRIVATE_KEY`, with no `continue-on-error`, then `platform-move` with `move: live` and `token: ${{ steps.live-token.outputs.token }}` |

- The jobs that change something, `image` to `live`, each hold `concurrency: { group: platform-release, cancel-in-progress: false }`, as the rollback's job does. Neither workflow sets a group at its top: GitHub keeps one pending run per group, and each push to `main` runs the release workflow for Release Please, so it could cancel a pending release or rollback.
- Produces `platform-rollback.yml`, `on: workflow_call`, with the identity, `commit` (required), the required input `live-app-client-id` and the required secret `LIVE_APP_PRIVATE_KEY`. It takes no release App secret. Job `rollback` (`Roll back to <commit>`), in `prod`, with `platform-role` (`infra`, `apply`). It applies nothing:
  - step `id: check` refuses a `commit` that isn't 40 lowercase hex; one not on `main` (`gh api repos/$GITHUB_REPOSITORY/compare/$COMMIT...main --jq .status` is neither `ahead` nor `identical`): "{commit} is not on main"; and one whose build is gone (`batch-get-image imageTag=sha-$COMMIT` finds nothing): "no build of {commit} is kept: the newest ten are; roll back to one of them, or release a fix". It writes that build's `digest`;
  - then `platform-move` with `move: current`; then, with the mover App's token (step `id: live-token`, as the release's `live` job mints it), `move: live` and `force: "true"`.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_release.py`. `_conditions(workflow: str, name: str) -> list[str]` returns the job's `if` and the `if` of every job it needs, recursively.
- `test_nothing_moves_without_a_release`: for `image`, `apply`, `monitoring-apply`, `current` and `live`, `_conditions` holds `needs.release-please.outputs.release_created == 'true'`.
- `test_current_moves_only_after_the_foundation_s_apply`: `current`'s needs are `{image, apply}` and its `if` holds `needs.apply.result == 'success'`; `live`'s needs are `[image, current]`.
- `test_both_workflows_require_the_movers_input_and_secret`: `platform-release.yml` and `platform-rollback.yml` each declare the input `live-app-client-id` (string) and the secret `LIVE_APP_PRIVATE_KEY`, both `required: true`.
- `test_the_live_move_mints_its_token_from_exactly_those`: the `live` job's token step in the release, and the rollback's, use `actions/create-github-app-token@v3`, the version every workflow pins, with `client-id: ${{ inputs.live-app-client-id }}` and `private-key: ${{ secrets.LIVE_APP_PRIVATE_KEY }}`, and `platform-move`'s `token` is that step's output.
- `test_no_step_that_moves_live_uses_the_release_app`: in both workflows, no step that runs `platform-move` with `move: live`, nor the step that mints its token, reads `RELEASE_BOT_CLIENT_ID` or `RELEASE_BOT_PRIVATE_KEY`. The rollback names neither secret.
- `test_every_job_needs_the_jobs_whose_outputs_it_reads`: in every `.github/workflows/platform-*.yml`, each `needs.<job>` in a job's text names a job in its `needs`.
- `test_the_build_is_tagged_with_the_release_commit`: `platform-build` pushes `…:sha-${{ steps.commit.outputs.commit }}`, with `load` and `push` both `"true"`, after the `infra` apply role, in `prod`.
- `test_a_re_run_reuses_the_release_s_build`: `built`, run with a fake `aws` that finds `sha-<commit>`, writes its digest, and `platform-build` takes `if: steps.built.outputs.digest == ''`.
- `test_the_applies_run_the_release_s_build_by_digest`: `apply` and `monitoring-apply` run `platform-image` with `digest: ${{ needs.image.outputs.digest }}`, with no `tag`, and their commands.
- `test_release_please_writes_with_the_app_s_token_only`: the `release-please` job's `permissions` are `{contents: read}`.
- `test_a_release_or_rollback_is_never_cancelled`: `image`, `apply`, `monitoring-apply`, `current`, `live` and `rollback` hold the group `platform-release` with `cancel-in-progress: false`, and neither workflow has a top-level `concurrency`.
- `test_moving_current_retags_the_build`: `platform-move`'s `current`, run with `run_action_step` and a fake `aws`, calls `batch-get-image` by digest, then `put-image` with `--image-tag current` and `--image-digest`. An `ImageAlreadyExistsException` from the fake exits 0.
- `test_live_is_fast_forwarded_by_the_mover_app_and_created_once`: `platform-move`'s `live`, with a fake `gh`, PATCHes with `force=false`. When the fake answers `Reference does not exist`, it POSTs. Any other error exits nonzero.
- On rollback:
  - `test_a_rollback_moves_current_and_live_to_a_kept_build`: `platform-move` with `move: current`, then with `move: live` and `force: "true"`;
  - `test_a_rollback_to_a_build_no_longer_kept_stops`;
  - `test_a_rollback_to_a_commit_not_on_main_stops`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_release.py -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write the action and both workflows** per the Interfaces. The header comment of `platform-release.yml` says the release is gated, as `jaws`'s is; the order of the jobs, and why (rulings 7 and 8); and that a failed job is re-run from the run's page.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_release.py tests/test_tool_checkout.py tests/test_owner_access.py tests/test_billing_export.py tests/test_release_infra.py -q`
Expected: PASS

- [ ] **Step 5: Docs.** `docs/platform-workflows.md`:
  - "Releases, current and live": the jobs, the tags, the off-hours window, and the `live` ruleset, whose only bypass actor is the hub's mover App. Its inputs, secrets and grants: `platform-image`, `account-id`, `name-root` and `live-app-client-id`; `RELEASE_BOT_CLIENT_ID`, `RELEASE_BOT_PRIVATE_KEY` and `LIVE_APP_PRIVATE_KEY`, passed from `prod` under that same name. The caller grants `contents: read` and `id-token: write`, and holds no `platform-release` group;
  - "Rolling back": when, what it moves and what it doesn't apply. Its inputs, secrets and grants: the identity, `commit` and `live-app-client-id`; `LIVE_APP_PRIVATE_KEY` only. The same grants.

- [ ] **Step 6: Commit**

```bash
git add .github/actions/platform-move .github/workflows/platform-release.yml .github/workflows/platform-rollback.yml tests/test_platform_release.py docs/platform-workflows.md
git commit -m "feat(workflows): release a hub's image, apply it, then move current and live"
```

---

### Task 13: the by-hand applies and the sweep

**Files:**
- Create: `.github/workflows/platform-bot-apply.yml`, `platform-databricks-apply.yml`, `platform-sweep.yml`
- Create: `tests/test_platform_applies.py`
- Modify: `docs/platform-workflows.md` ("By-hand applies and the sweep")

**Interfaces:**
- Consumes: `config projects` (Task 3), `platform apply data-access` (Task 5), `IDENTITY_WORKFLOWS` and `CHECK_PREFIX_WORKFLOWS` (Task 7), Task 8's actions, and `platform-project-file` (Task 11).
- Produces three workflows, each `on: workflow_call` with the identity, each job in `environment: prod`, and each run on the build `current` names. Each `jaws` step takes `github-token: ${{ github.token }}`, for the project files the CLI reads from GitHub.
  - **`platform-bot-apply.yml`:**
    - inputs `project` (required), `destroy` (boolean, default false) and `consumer-ref` (default `""`);
    - job `apply` (`${{ inputs.destroy && 'Destroy' || 'Apply' }} ${{ inputs.project }}`), with job-level `concurrency: { group: bot-apply-${{ inputs.project }}, cancel-in-progress: false }`;
    - its first step, `id: project`, refuses the platform's own stacks before any role is assumed: for `infra`, `monitoring` and `data-access`, "{project} is one of the platform's own stacks, not a bot or research project";
    - then `platform-role` (`role: apply`, `project: ${{ inputs.project }}`), the credentials and `platform-image`;
    - step `id: lookup` runs `config projects bot research` offline in the build, and refuses "{project} is not a bot or research project in the platform's configuration";
    - then `platform-project-file`, with `ref: ${{ inputs.consumer-ref }}` and `on-mismatch: refuse`;
    - then `jaws` with `--file .consumer/jaws.yaml apply`, or `destroy --yes`.
  - **`platform-databricks-apply.yml`:** the bot apply's steps, with:
    - inputs `project`, and `action` (string, default `apply`), and no `consumer-ref`;
    - job-level `concurrency: { group: databricks-apply-${{ inputs.project }}, cancel-in-progress: false }`, today's lock;
    - step `id: action`, which refuses anything but `apply`, `destroy` or `doctor`;
    - the lookup `config projects databricks`, and `databricks-apply.yml`'s commands.
  - **`platform-sweep.yml`:**
    - job `sweep` (`Data access apply`), `if: github.ref == 'refs/heads/main'`, with job-level `concurrency: { group: data-access-sweep, cancel-in-progress: false }`;
    - `platform-role` takes project `data-access`, role `apply`;
    - then `jaws` with `platform apply data-access`.

    The hub's caller holds the schedule and the dispatch.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_applies.py`
- `test_the_check_knows_every_workflow_that_takes_the_identity`: `IDENTITY_WORKFLOWS` is exactly the `.github/workflows/*.yml` whose `workflow_call` inputs hold `platform-image`, and `CHECK_PREFIX_WORKFLOWS` those holding `check-prefix`. So `jaws platform check` (Task 7) asks for exactly the inputs the workflows take.
- `test_the_sweep_applies_from_main_in_prod_and_never_overlaps`: `sweep`'s `if` is `github.ref == 'refs/heads/main'`, its environment `prod`, and its `concurrency` `{group: data-access-sweep, cancel-in-progress: false}`.
- `test_one_apply_per_project_at_a_time`: the bot apply's group is `bot-apply-${{ inputs.project }}` and the Databricks apply's `databricks-apply-${{ inputs.project }}`, each with `cancel-in-progress: false`.
- `test_the_by_hand_applies_and_the_sweep_run_the_current_build`: each `platform-image` step has no `digest` and no `artifact`, so it takes `current` (spec 6.4).
- `test_the_project_file_reads_carry_a_token`: every `jaws` step of the three workflows takes `github-token: ${{ github.token }}`.
- `test_a_bot_is_applied_with_its_apply_role`: `platform-role`'s `role` is `apply` and its `project` is `${{ inputs.project }}`.
- `test_the_platform_s_own_stacks_are_refused_before_any_role`: `project`, run with `infra`, `monitoring` and `data-access`, stops naming the project, and comes before `platform-role` in both applies.
- `test_a_project_that_is_not_a_bot_is_refused`: `lookup`, run with a fake `docker` printing a registry without it, stops naming the project.
- `test_the_project_file_must_name_the_project`: both applies run `platform-project-file` with `on-mismatch: refuse`, after `lookup` and before `jaws`; the bot apply's takes `ref: ${{ inputs.consumer-ref }}`.
- `test_a_databricks_action_is_one_of_three`: `action` with `apply`, `destroy` and `doctor` passes, and `deploy` stops.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_applies.py -v`
Expected: FAIL

- [ ] **Step 3: Write the three workflows** per the Interfaces. Their steps follow `bot-apply.yml`, `databricks-apply.yml` and `data-access.yml`'s `apply` job, which stay as they are.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_platform_applies.py tests/test_tool_checkout.py tests/test_workflow_artifacts.py tests/test_owner_access.py tests/test_billing_export.py tests/test_release_infra.py -q`
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
- Consumes: `platform-base` (Task 11).
- Produces `platform-upgrade.yml`, `on: workflow_call`, with the input `app-client-id` (required) and the secret `app-private-key` (required): an App with Contents, Pull requests and Workflows write (ruling 12). The caller spells the client ID as a literal or a `vars.` value, since a call's `with:` can't read `secrets`.
- Job `upgrade` (`Upgrade Jaws`), with `permissions: { contents: read }`. The App's token does the writes. Its steps:
  1. **`app-token`:** `create-github-app-token`, with no `continue-on-error`, since `GITHUB_TOKEN` can't do this job. Then the checkout, with that token, and `platform-base` (`id: base`).
  2. **`newest`,** with `NAME` and `PIN` from `base`. It refuses a base outside `public.ecr.aws/` with "the upgrade reads ECR Public; this Dockerfile builds FROM {name}". With an anonymous token (`https://public.ecr.aws/token/?service=public.ecr.aws&scope=repository:<alias>/jaws:pull`), it reads `https://public.ecr.aws/v2/<alias>/jaws/tags/list?n=1000` and picks the newest `^v[0-9]+\.[0-9]+\.[0-9]+$` by semver with jq. Not newer than the pin: `newer=false`, and the notice "Jaws {pin} is the newest release". Newer: `newer=true`, `tag`, `pin` and `digest`, the `docker-content-digest` of a `HEAD` on `…/manifests/<tag>` with plan 04's `MANIFEST_TYPES`. A registry error stops the job.
  3. **`rewrite`,** when newer, edits through a temporary file, never `sed -i`: `run_step` also runs it on macOS, whose BSD `sed -i` differs from GNU's. The `FROM` line's `:<pin>@sha256:<64 hex>` becomes `:<tag>@<digest>`. In `.github/workflows/*.yml` and `*.yaml`, `(uses: Jaws-Platform/jaws/\.github/workflows/[A-Za-z0-9_.-]+\.ya?ml)@v[0-9]+\.[0-9]+\.[0-9]+` becomes `\1@<tag>`. It fails unless `git diff --name-only` lists the `Dockerfile` and a workflow.
  4. **`pull-request`:**
     - it commits on `jaws-upgrade` (`git switch -C`) as `<app-slug>[bot]`, with the message `chore(deps): upgrade jaws to <tag>`;
     - when `origin/jaws-upgrade` holds the same tree, or the open PR's title already names `<tag>`, it pushes nothing and edits nothing, with the notice "the upgrade to {tag} is open";
     - otherwise it runs `git push --force origin jaws-upgrade`, then edits the open PR (`gh pr list --head jaws-upgrade --state open`), or else creates one against `main`. Its title is the commit's. Its body names both versions, says one PR bumps the image and every workflow pin and its plans run with the candidate for every stack and project, and links `https://github.com/Jaws-Platform/jaws/compare/<pin>...<tag>`.

- [ ] **Step 1: Write the failing tests** in `tests/test_platform_upgrade.py`, with `run_step`, the pin `v0.9.0` of `public.ecr.aws/example-alias/jaws`, and the new digest `sha256:bbb…`
- `test_a_newer_release_is_found_by_semver_not_text`: `newest`, with the fake `curl` listing `v0.8.0 v0.9.0 v0.10.0 latest v0.10.1-rc1`, writes `tag=v0.10.0` and `digest=sha256:bbb…`, though v0.10.0 sorts before v0.9.0 as text.
- `test_one_commit_bumps_the_dockerfile_and_every_jaws_pin`: `rewrite`, with `PIN=v0.9.0`, `TAG=v0.10.0` and `DIGEST`, ends the `Dockerfile`'s `FROM …:v0.9.0@sha256:aaa…` with `:v0.10.0@sha256:bbb…` and makes `site-plan.yml`'s call `@v0.10.0`. It leaves byte for byte a `lint.yml` calling `Example-Org/tools/.github/workflows/lint.yml@v0.9.0`.
- `test_nothing_happens_when_the_pin_is_the_newest`: `newer=false`, and the notice.
- `test_a_registry_error_stops_the_upgrade`: the fake `curl` exits 22, the step exits nonzero, and it writes no `tag`.
- `test_the_pull_request_is_opened_once_and_updated_after`: `pull-request`, run with fakes for `git` and `gh`, calls `gh pr create` when the list is empty and `gh pr edit` when it holds one.
- `test_an_open_upgrade_to_the_same_release_is_left_alone`: with the open PR titled `chore(deps): upgrade jaws to v0.10.0`, or `origin/jaws-upgrade` at the same tree, `pull-request` neither pushes nor edits.
- `test_the_upgrade_needs_an_app_that_may_change_workflows`: the token step has no `continue-on-error`. The workflow's comment names *Workflows: read and write*.
- `test_the_upgrade_reads_the_from_line_with_platform_base`: the job runs `platform-base` before `newest`, which takes `NAME` and `PIN` from its outputs.

The fake `curl` answers the token request, then the tag list from `FAKE_TAGS`, then the `HEAD` with a `docker-content-digest: $FAKE_DIGEST` header. `_git_init(path: Path) -> None` makes `path` a repository with one commit, using neutral author values as `tests/test_tool_checkout.py` does.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_platform_upgrade.py -v`
Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Write the workflow** per the Interfaces. The header says why one PR bumps every pin (spec 6.4, "Dependabot would split the image and workflow bumps"), which App it needs, and that a hub schedules it hourly (ruling 12).

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
    - `_SOURCE` becomes `source ../scripts/databricks-credentials.sh ../config "$NAME_ROOT"`, and `test_only_the_terraform_steps_get_the_credential` takes all five steps: its parameters gain `data-access.yml`'s `plan` (`terraform plan`) and `apply` (`Sweep (plan, then apply what changed)`), and each job's `NAME_ROOT` expression. Each sourcing step's first line is `_SOURCE`, and its `env.NAME_ROOT` is the job's expression. The credentials come before each sourcing step, since data access's `apply` has no `terraform plan`.
  - In `tests/test_workflow_roles.py`, `test_no_workflow_reads_the_account_or_the_name_root_itself` also reads `scripts/databricks-credentials.sh`, which must hold no `.context.name_root`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_databricks_workflows.py tests/test_workflow_roles.py -v`
Expected: FAIL. The steps pass one argument, and the script reads `.context.name_root`.

- [ ] **Step 3: Change the script and the five steps** per the Interfaces. The header comment names both arguments.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_databricks_workflows.py tests/test_workflow_roles.py tests/test_foundation_workflows.py -q && shellcheck scripts/databricks-credentials.sh`
Expected: PASS

- [ ] **Step 5: Commit.** The scope is `workflows`, the closest in `SCOPES` by folder: the change is the sourcing steps in `.github/workflows/`, and the script only they source. `databricks` covers the Databricks account and workspace stacks.

```bash
git add scripts/databricks-credentials.sh .github/workflows/ci.yml .github/workflows/release-please.yml .github/workflows/data-access.yml tests/test_databricks_workflows.py tests/test_workflow_roles.py
git commit -m "refactor(workflows): pass the name root to the credential script instead of reading it"
```

---

### Task 16: open the pull request

- [ ] **Step 1: Bring the repository's own docs up to date**
  - **`AGENTS.md`:**
    - the CLI paragraph names `jaws platform` and `jaws config projects`;
    - a rule: the `platform-*.yml` workflows and the `platform-*` actions are a hub's. No workflow of `jaws` calls them, and no `platform-*` workflow or action, and no CLI command, names `owner-access`, `billing-export` or `release-infra`. Of `jaws`'s workflows, only `ci.yml` does, in the jobs that validate and test them, as `tests/test_owner_access.py`, `tests/test_billing_export.py` and `tests/test_release_infra.py` require.
  - **`README.md`, the Layout table:**
    - `.github/workflows/platform-*.yml`: "A hub's workflows: its pull requests, its release, rollback, by-hand applies, the data access sweep and the upgrade PR ([docs/platform-workflows.md](docs/platform-workflows.md))";
    - `.github/actions/platform-*`: "Shared steps of a hub's runs: the role, one build per run, the base and the build, the project file, and the moves of `current` and `live`".
  - **The roadmap,** `docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md`:
    - row 05's status becomes "in its pull request", and row 04's "merged in #317";
    - rows 06 and 07 gain "For plans 06 and 07" above, in a few words each;
    - "Owner steps along the way" gains this plan's hand-offs 1 and 3.

```bash
git add AGENTS.md README.md docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md
git commit -m "docs(repo): describe the hub's workflows and add plan 05's rulings to the roadmap"
```

- [ ] **Step 2: Run `AGENTS.md`'s "Before opening a PR" checklist,** every line, then `(cd foundation && terraform test)`.
Expected: every command passes.

- [ ] **Step 3: Push the branch and ready its PR**
  - Push with `--force-with-lease`, because the branch was rebased before Task 2.
  - Title: `feat(workflows): run project workflows from a hub's image, and add the hub's workflows`.
  - Body: `.github/pull_request_template.md`, with every section filled in.
    - It links the spec, this plan and Task 1's PR.
    - It says merging changes nothing in AWS, and that every project's pin runs as before.
    - "Why" lists the five owner decisions, the rulings marked **to confirm** (6, 7, 9, 10 and 12), each with the spec text it departs from or the gap it fills. It says ruling 10 replaces plan 02's hand-off, names the departures from spec 7 in rulings 8 and 16, and gives owner hand-off 1.
    - "Verification" lists Step 2's checklist and the CI plan comments.

```bash
git push --force-with-lease
gh pr edit <this PR> --title "feat(workflows): run project workflows from a hub's image, and add the hub's workflows" --body-file <file>
gh pr ready <this PR>
```

Expected:
- CI passes;
- the `Terraform plan` and every `Bot plan` comment say merging leaves AWS alone;
- the `Data access plan` shows no changes.
