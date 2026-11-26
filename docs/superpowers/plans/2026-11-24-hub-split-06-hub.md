# Jaws as a product, plan 06: the hub: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Before any review, read the Global Constraints' "Reviews".** Tasks 3–5 commit the owner's email and account IDs, and the skill's default review package would print them.

**Goal:** Create `JWall-Engineering/platform`, the hub, by the organization's conventions. It holds the owner's configuration and datasets, taken whole from `jaws`; an image built `FROM` a pinned public Jaws release; the callers of Jaws's workflows; the owner's folders with their guards; and the checks of the owner's configuration. It checks and plans beside `jaws`, and applies nothing until plan 07's takeover.

**Architecture:**
- **What the hub holds** (spec 6.1):

  | Path | What | From |
  |---|---|---|
  | `config/`, `datasets/` | the platform's configuration and the onboarded-dataset registry | `jaws` at the pinned release, whole, plus the hub's `brand` and identity (the owner's edit, H4) |
  | `Dockerfile`, `.dockerignore` | `FROM public.ecr.aws/<alias>/jaws:<tag>@<digest>`, then `config/` and `datasets/` | plan 04's `jaws-cli` stage, on the public image |
  | `.github/workflows/` | CI with the `platform-ci.yml` caller, the hourly upgrade, the six project-facing callers, Release Please | callers of plan 05's workflows |
  | `owner/` | `owner-access/` and `billing-export/`, unchanged, with their runbooks | `jaws` at the pinned release |
  | `tests/platform/` | checks of the owner's configuration, registry and folders, and of the callers | `jaws`'s `tests/platform/`, the checks of the configuration |
- **The line with plan 07.** The hub checks and plans; it applies nothing. Plan 07's enabling release makes the platform's roles trust it. Its takeover adds every workflow that applies, and switches `jaws`'s off.
- **Privacy by construction** (ruling 5): whole-directory copies checked by tree hash, the owner's edits for single configuration files, checks that fail on a file, a field or a count, and an account ID rendered into the callers without being printed.

**Tech Stack:** GitHub (rulesets, environments, GitHub Apps, reusable workflows, Dependabot), Release Please, commitlint on Node 24, Docker BuildKit, Terraform 1.14 with tflint, and Python 3.13 with uv. pytest and ruff run from the pinned Jaws release's own locked environment.

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md), sections 6.1, 6.9, 6.12 and 7, with 6.3–6.5 for what the hub consumes. Roadmap: [row 06](2026-11-23-hub-split-00-roadmap.md). It builds on three plans, which must be released first:
- plan 02, the `brand` section;
- plan 04, the public image (PR #317);
- plan 05, the workflows (draft PR #323, at abf3fa9, which holds the amendment for D6).

**Where the work happens:**
- Tasks 1–5 are in `JWall-Engineering/platform`, cloned to `~/Projects/JWall-Engineering/platform`. Each task's PR has its own branch, from an up-to-date `main`, named in the task.
- Task 6 is in `JWall-Engineering/.github` and `JWall-Engineering/jwall-engineering-branding`, both under `~/Projects/JWall-Engineering/`.
- Task 7 is in `jaws`, on `hub-split/06-hub`, the branch of draft PR #326 that holds this plan. The roadmap edit lands on that PR, as plan 05's lands on its own.
- `<tag>` is the Jaws release the hub starts on (H0), and `<alias>` its public registry alias. After a by-hand bump (ruling 1), `<tag>` is the new release.

## Global Constraints

- **The conventions** (`~/Projects/Common/Repository/repository-conventions.md` and `organization-conventions.md`):
  - the initial scaffold, `chore(repo): initial scaffold`, is the only direct push to `main`. Then come the conventions PR, the Release Please PR, `scripts/apply-repo-settings.sh` and the verification, in that order;
  - every other change is a PR, merged by squash or rebase;
  - each commit is one line, `type(scope): subject`, at most 100 characters, lowercase, with no trailing period. Only `Co-authored-by` trailers may follow, after a blank line;
  - the PR title is a valid commit header, and the body fills every section of the template;
  - every README opens with the header standard: the banner from `jwall-engineering-branding`'s `main`, then `# <repo>`, then the badges;
  - GitHub Apps are named `<Org Name> <Purpose>`, with slug `<org>-<purpose>`, never ending in "bot".
- **The hub's scopes, verbatim (6.12):** "**`platform`:** `config` (accounts, projects, guardrails, brand), `datasets`, `image` (the `Dockerfile`), `workflows`, `owner` (the `owner/` folders), `repo`, `deps` (which also covers Jaws upgrades), `release`." In `.github` the scope is `profile`. In the branding repository and in `jaws` it is `repo`.
- **Nothing in AWS changes, and the hub applies nothing.**
  - Never run an `aws` command, `aws sso login`, `terraform plan|apply` against real state, `jaws apply|publish|release|destroy`, or `docker push`. Run `docker run` only with `--network none`. `docker build` pulls only the public base.
  - Plan 06 creates no AWS resource, role or trust. Until plan 07's enabling release, the hub's plan jobs fail or skip at their credentials, and none of them is a required check. So `platform / Terraform plan` and `platform / Data access plan` are red on every hub PR until then, by design (Task 5).
- **This plan changes nothing in `jaws`** but its roadmap (Task 7). Its `config/`, `datasets/`, owner folders and `tests/platform/` stay until plan 07's cleanup. `jaws`'s own family bumps still edit its copies of the owner's folders, which nobody applies after Task 4 (ruling 6).
- **Privacy, in every task:**
  - never print a value from `config/`, and never name an individual `config/` file in a command. Copy whole directories, and verify with tree hashes and with checks that name a file, a field or a count;
  - an edit to one configuration file is the owner's (H4);
  - never display `owner/`, the runbooks, or the callers' `account-id` lines. They hold account IDs, and `owner/owner-access/` holds the owner's email. Use `git diff --stat`, never a full diff, `git show` or `cat` of them, and read a caller through Task 5's mask;
  - a check that compares owner values fails with `pytest.fail(<a file, field or count>, pytrace=False)`, never a bare `assert`, whose report prints both sides;
  - run pytest with `-q`, never `-v`: test IDs can carry values;
  - silence `terraform validate` and tflint, and keep only `terraform test`'s last line: their errors and findings quote the source;
  - send the stderr of a `docker run` that reads the configuration nowhere: a configuration error can quote values;
  - never open or list a folder that holds an App's key. The keys are the owner's (H3);
  - in `jaws`, never run `git diff`, `git show` or `git log -p` across 9f73517 or earlier, 3d81dad or b05f4c0;
  - never write the owner's email anywhere;
  - if the privacy hook refuses a command, stop and hand that step to the owner. Never work around it.
- **Reviews: a hard privacy rule for whoever runs this plan.** superpowers:subagent-driven-development's reviews read whole diffs. Its `scripts/review-package` writes `git diff -U10` of the range; its task reviewer and re-reviewer run `git diff` themselves when they have no package; and the final reviewer's template, requesting-code-review's `code-reviewer.md`, runs `git diff`. Over Tasks 3–5 that prints the owner's email and the account IDs. So, at every review (each task's, each fix round's, and the final whole-branch review):
  - **a sealed commit** is one that touches `config/`, `datasets/`, `owner/` or a project-facing caller. Tasks 3, 4 and 5 make them, H4's included, and keep every other file in commits of its own, as their commit steps show;
  - nobody runs `git diff`, `git show`, `git log -p` or `review-package` over a range that holds a sealed commit, and nobody displays a sealed path, but a caller through Task 5's mask;
  - **the controller writes that range's package itself,** to the file `review-package` would have written: `git log --oneline` and `git diff --stat` of the range; `git diff -U10 <commit>^ <commit>` of each commit that isn't sealed; and, for each sealed commit, the evidence its task prints: the tree-hash lines, the substitution counts, the callers through Task 5's mask, and the tests' summary line. It never dispatches a reviewer of that range without the package;
  - every implementer and reviewer prompt carries the Privacy rules above and this one, verbatim, and tells the reviewer that the package is its whole view of the range: never `git diff` or `git show` it, whatever its template says;
  - the owner reads the sealed commits in each PR.
- **One Jaws version** (plan 05 ruling 11). The `Dockerfile`'s tag and digest and every `Jaws-Platform/jaws/.github/workflows/<file>@<ref>` name the same release. They move together, in one commit: the upgrade PR's, or the owner's by-hand bump (ruling 1). Never bump one pin alone. The hub's tests run on that release.
- **Least privilege:**
  - every workflow has top-level `permissions: {}`;
  - each job asks for the least it needs, and a caller job grants exactly what its Jaws workflow's jobs declare;
  - no `pull_request_target`, and no `secrets: inherit`;
  - each App holds only what it does and is installed only where it acts. Its key is a secret of each repository that reads it (ruling 10).
- **Spending** (the owner's rule: nothing new without approval):
  - **Plan 06 adds no cost.**
    - Nothing is created in AWS.
    - The hub is public on GitHub Free, where Actions minutes on standard runners, artifacts, caches, environments, rulesets and Apps cost nothing.
    - Its pull requests pull the public base anonymously, about 283 MiB a push. At ten pushes a day that is about 90 GB a month, inside ECR Public's 500 GB a month of free anonymous transfer. Beyond its free tier, ECR Public bills transfer to the account that downloads, never to the publisher.
  - **Approved already:**
    - the ECR Public free tier (plan 04);
    - about $0.10 a month for `jaws-cli` storage until cleanup (plan 04);
    - the bigger `jaws-cli` pulls (accepted 2026-11-24).
  - **New from plan 07's enabling release, for the owner to approve:** the hub image's storage and its pulls (D5).
- **The region** stays `us-east-1` (spec 6.7).
- **Before each PR in the hub:**
  - `npm ci && npm test`;
  - from Task 2, `uv run --project .jaws-tool --locked ruff format --check tests`, then `ruff check tests` and `pytest` the same way;
  - from Task 4, in each owner root, Task 4's Step 6 commands, which report only exit codes and summary lines.

## Review Focus

1. **A configuration change during the freeze, in either repository:** a hub PR that edits a frozen section, or a Jaws release whose `config/` or `datasets/` changed. Expected: the hub's `tests` check fails, naming the section or a count, never a value. Task 3, `test_the_configuration_is_jaws_s_but_the_hub_s_own_sections` and `test_the_datasets_are_jaws_s`.
2. **A Jaws pin bumped alone,** by Dependabot's `github-actions` or `docker` ecosystem. Expected: Dependabot never opens it, since the pin check would fail it. The spec says why (6.4): "Dependabot would split the image and workflow bumps into separate PRs". Task 2, `test_dependabot_never_bumps_a_jaws_pin`.
3. **A failing check, in a public log or an agent's transcript:** a configuration that doesn't load, or an identity literal that disagrees. Expected: the failure names a file, a field or a count, never a value. Task 3, `test_a_configuration_that_does_not_load_is_reported_without_its_values`; Task 5, `test_a_wrong_identity_is_reported_without_its_values`.
4. **A Jaws release that changes a project-facing workflow's interface.** Expected:
   - a new optional input leaves the upgrade PR green, and the hub offers it when it chooses to;
   - a new required input, or one the hub offers or passes that Jaws dropped, fails the check, naming the workflow and the input;
   - a new or dropped secret or output fails the check, naming the workflow. A caller that dropped an output would let a site's release skip its deploy and stay green.

   Task 5, `test_each_project_facing_caller_offers_what_jaws_takes_but_the_platform_s`, `test_each_caller_passes_its_inputs_and_secrets_through_by_name` and `test_each_caller_passes_its_outputs_through`. The fix goes on a branch cut from `jaws-upgrade` (ruling 1).
5. **A workflow that reaches AWS or the owner's folders from the wrong trigger:** `pull_request_target`, `secrets: inherit`, or a job that names `owner-access` and holds `id-token`. Expected: the hub's CI fails, naming the workflow and the job. Task 4, `test_ci_only_checks_the_owner_s_folders`; Task 5, `test_no_workflow_runs_on_pull_request_target_or_inherits_secrets`.

## Rulings

Calls this plan makes. The owner's decisions they rest on are in the next section.

1. **The base image's retention: the hourly upgrade PR, keep-10 and no mirror, with the owner's by-hand bump during development. Decided (D1).**
   - **The risk.** ECR Public keeps the newest ten Jaws releases until v1 (`JAWS_PUBLIC_IMAGE_KEEP`). At the average pace, about six releases a day, a pin lasts about two days, but a busy day can prune it within a day: `jaws` shipped 12 to 13 releases on each of 11-16, 11-17 and 11-21. A hub whose base is gone can't build: every candidate and every release fails to pull it. The running build keeps working, since the hub's own ECR repository holds its layers.
   - **The error says what to do.** Plan 05's `platform-base` checks the pinned digest before a build, in its step `present` (9e58ffe). A pruned base fails the job with "the Dockerfile's Jaws base <base-name>:<base-tag>@<base-digest> is no longer in ECR Public, which keeps only the newest versions until v1: merge the open upgrade PR, or move the FROM line to a recent Jaws release".
   - **Remedy 1, chosen: an upgrade PR on every Jaws release.** `upgrade.yml` runs plan 05's `platform-upgrade.yml` hourly (plan 05 ruling 12), so the hub trails only by the upgrades it hasn't merged.
     - Cost: no money (a public repository and anonymous reads), and the owner's attention: an upgrade merged within about two days at the average pace, and within a day on a busy one, with the hub's pace tied to Jaws's until v1.
     - **The owner's by-hand bump, during development.** When needed, the owner bumps the pin by hand, in its own PR. A by-hand bump moves the `FROM` tag and digest and every `Jaws-Platform/jaws/.github/workflows/<file>@` pin together, in one commit; before Task 5 the `FROM` line is the only pin. "Never bump one pin by hand" becomes "never bump one pin alone": once the callers exist, moving the `FROM` line alone fails `platform check` rule 3. The `tests` job then re-runs the freeze check at the new tag (ruling 4). A task branch still open rebases onto the bump, clones `.jaws-tool` again at the new tag, and pins anything it adds to it. Automating the bump comes later.
     - **The escape hatch:** raise `JAWS_PUBLIC_IMAGE_KEEP` in `Jaws-Platform/jaws` before the pin is ten releases behind, to hold the hub back on purpose or to keep a pin through a busy day. ECR Public's free 50 GB holds about 170 releases.
     - **During the freeze** (ruling 4), no PR fixes the configuration for a release: a release that needs a configuration change is held back by keeping the pin, with the escape hatch if it would be pruned. A workflow fix for an upgrade goes on a branch cut from `jaws-upgrade`, in its own PR, which the hourly run doesn't touch; once it merges, close the upgrade PR. The run force-pushes `jaws-upgrade` whenever a newer release appears (plan 05, Task 14), so a fix pushed there would vanish.
   - **Remedy 2, not chosen: mirror the pinned base into the hub's own ECR repository,** and build from the mirror.
     - Cost: about $0.03 a month per mirrored base, or nothing where it shares the hub builds' layers.
     - It also changes plan 05, and the changes outlast the risk:
       - `platform-build` builds from the mirror once the public tag is gone;
       - the release pushes each new base with the release role, a new tag kind under the hub image's lifecycle;
       - pull request candidates need a registry login and a role, which plan 05's ruling 5 keeps them out of;
       - the upgrade's and the check's rule that the base comes from ECR Public must bend.
     - All of that is for a risk that ends at v1, when `JAWS_PUBLIC_IMAGE_KEEP` becomes `all`.
2. **The hub applies nothing before plan 07's takeover** (spec 6.10, steps 2 and 5).
   - Plan 06's workflows:
     - CI, which checks and plans (`platform-ci.yml`);
     - the hourly upgrade;
     - the six project-facing callers, which nothing calls until plan 07's `release.yml` creates `live`. H7's v0.1.0 creates nothing;
     - the conventions' Release Please, which tags versions and ships nothing.
   - Plan 07's takeover adds `release.yml`, `rollback.yml`, `bot-apply.yml`, `databricks-apply.yml` and `sweep.yml`.
     - `release.yml` replaces `release-please.yml`, with the same config and manifest.
     - They arrive as `jaws`'s same workflows are switched off, so exactly one applier and one sweeper run.
3. **The configuration is `jaws`'s at `<tag>`, whole, plus the hub's own** (spec 6.2). Plan 01 already took the release's values out of `config/`. The hub adds:
   - `brand` in `tool.yaml`, plan 02's hand-off (ruling 9);
   - its identity in `platform.yaml`: `JWall-Engineering/platform` second in `platform.repositories` (plan 03 ruling 2), and `platform.hub`. Plan 05's check and `config env --platform` need both. Plan 07's enabling release adds the same lines to `jaws`'s copy;
   - the `brand` row of `config/README.md`.

   `name_root: jaws` and `ManagedBy: JAWS` stay (spec 6.7), and so does `context.organization` (D3). `ecr` stays too: the foundation manages `jaws-cli` until cleanup.
4. **The freeze is checked from the hub's side.**
   - It starts when Task 3 merges. The spec, verbatim (6.10): "No change goes into `config/` or `datasets/` in either repository during that window."
   - On every PR, upgrade PRs and by-hand bumps included, the hub's `tests` compares its copy with `jaws`'s at the pinned release. A change to the hub's copy fails its own PR. A change to `jaws`'s fails the next upgrade PR, within the hour of its release, and `jaws` applies it meanwhile.
   - Plan 07 removes the check at takeover.
5. **Nothing the agent runs prints a value.** Copies are `git archive` of whole directories at `<tag>`, checked by tree hash. The account ID is rendered into the callers from `jaws config env` in the hub's image, and never typed or shown (Global Constraints, "Privacy").
6. **The owner's folders move unchanged** (spec 6.9), under `owner/`.
   - Both roots read `${path.module}/../config`, so `owner/config` is a link to `../config`, and no Terraform file in either root changes. `admin_role_arn` stays in `aws`, for their hardened bucket policies.
   - Their runbooks move beside them as `owner/owner-access.md` and `owner/billing-export.md`. They are `jaws`'s `docs/owner-access.md` and `docs/billing-export.md`, and they hold account IDs, so counted substitutions rewrite their paths.
   - CI validates, lints and tests both roots, and never plans or applies them.
   - Dependabot keeps their providers and modules current, outside the release's family pins (`jaws`'s `tests/test_versions.py`), so an upgrade PR never waits on them.
   - From Task 4's merge, the owner applies them only from the hub, and nobody applies `jaws`'s copies, which leave at cleanup. Until then those copies still change: `jaws`'s `tests/test_versions.py` holds every module pin in `owner-access/` and `billing-export/` to `src/jaws/product.yaml`, so each family bump edits them, while the hub's Dependabot moves the hub's on their own. That is harmless, since only the hub's copies are applied.
7. **What moves from `tests/platform/`, and what stays.**
   - **Moves, adapted to the hub:**
     - `test_config_layout.py`, with `brand`, and without `test_the_fixture_has_every_section_the_owner_uses`, which needs `jaws`'s fixture;
     - `test_owner_registry.py`'s engine check;
     - `test_owner_rules.py`, with its constants copied, since `jaws`'s tests aren't importable;
     - `test_owner_image_labels.py`;
     - the owner half of `test_state_backends.py`.
   - **Stays in `jaws`,** since each checks a `jaws` folder:
     - `test_release_infra.py` (plan 04);
     - `test_platform_stacks.py`, `test_foundation_backend.py` and `test_platform_backends.py` (plan 05);
     - `test_no_owner_values.py` and `test_isolation.py`;
     - the monitoring half of `test_state_backends.py`, and `test_owner_registry.py`'s action check.
   - The guards of spec 6.9 split the same way. The hub checks its workflows and its folders' state. That no CI role holds Identity Center permissions stays the product's rule, checked where the roles are defined.
   - `jaws` keeps its copies of the moved checks until plan 07 removes `config/`.
8. **The hub's tests run on the pinned release, from source.** The `tests` job checks out `Jaws-Platform/jaws` at the `Dockerfile`'s tag, and runs pytest and ruff in that checkout's locked environment. That adds no third pin and no second pull of the image, and it runs each upgrade PR's checks on its new release.
9. **The brand:**
   - `name: JWall Engineering`;
   - `mark`: the logo the branding repository publishes for "Anywhere that supplies its own background, light or dark";
   - `check_prefix: jwall` (D2).
10. **The Apps.**
    - **JWall Engineering Comments** (`jwall-engineering-comments`):
      - *Pull requests: read and write*, no webhook, installable on any account;
      - installed on `platform` and on the three site repositories under `jwallace145` only, since only the site workflows and the hub's CI post comments (D4).
    - **JWall Engineering Upgrades** (`jwall-engineering-upgrades`, plan 05 ruling 12):
      - *Contents*, *Pull requests* and *Workflows*, each read and write, no webhook, installable only on this account;
      - installed on `platform` only.
    - **JWall Engineering Deployments** (`jwall-engineering-deployments`), `live`'s mover (D6):
      - *Contents* and *Workflows*, each read and write, and *Metadata*, read; no webhook, installable only on this account;
      - installed on `platform` only, and `live`'s only bypass actor (ruling 11);
      - a move of `live` across an upgrade changes the workflow files `live` names, and *Workflows* write covers it, whether a release fast-forwards `live` or a rollback force-moves it.
    - **JWall Engineering Releases** (`jwall-engineering-releases`) stays as it is, and keeps Release Please's job only. It no longer bypasses `live` (D6).
    - **The new Apps' keys** are repository secrets, in each repository that reads them, never organization secrets ("a token only one repository uses is a repository secret"):
      - `COMMENTS_APP_PRIVATE_KEY`, `UPGRADES_APP_PRIVATE_KEY` and `DEPLOYMENTS_APP_PRIVATE_KEY` on `platform`;
      - `COMMENTS_APP_PRIVATE_KEY` on each site repository.
    - The client IDs are literals in the callers (plan 05 ruling 16).
11. **Rulesets, the environment and Actions' defaults.** All of them are in `scripts/apply-repo-settings.sh`, which the owner runs (H5).
    - `main`: the conventions' ruleset, with no bypass actors. It requires every check `ci.yml` reports, but the platform's plans until plan 07.
    - `live` restricts creation, updates and deletion, and blocks force pushes. JWall Engineering Deployments is its only bypass actor (D6), so only a release creates or moves it (plan 05 ruling 8), and a rollback may force-move it (plan 05 ruling 9).
    - `prod` takes deployments from `main` only, with no secrets and no reviewers. Nothing names it before plan 07.
    - Actions: `GITHUB_TOKEN` is read-only by default, and Actions may not approve pull requests. Fork pull requests' workflows need approval for every external contributor (`fork-pr-contributor-approval`).
    - No repository variables: the callers spell what they need (plan 05).
    - No roles: plan 06 adds none. After plan 07's enabling release, the hub's pull requests assume only the plan roles, and its `prod` jobs the apply roles (plan 03). No job that names the owner's folders assumes any.
12. **Dependabot never bumps a Jaws pin.** There is no `docker` ecosystem, and `github-actions` ignores `Jaws-Platform/jaws*`. Dependabot bumps the actions, npm, and the owner's two roots.
13. **The project-facing callers** offer every input of their Jaws workflow at `<tag>`, except two kinds:
    - the platform's own: `platform-image`, `account-id`, `name-root`, `check-prefix` and `app-client-id`;
    - the role overrides, which a hub derives (plan 05 ruling 2).

    They pass each input through, and each secret by name. A project then names no version and no role (spec 6.11).

## Owner decisions

The PR lists these. Each comes with the recommendation the plan is written to. D1 and D6 are decided. D2, D3 and D7 are decided before Task 3 merges, since the freeze then holds the configuration.

1. **D1, the retention remedy (ruling 1): decided** (2026-11-24). The hourly upgrade PR, keep-10 and no mirror. During development the owner bumps the pin by hand when needed, every pin in one commit, and automation comes later.
   - A busy day can prune a pin within a day: `jaws` shipped 12 to 13 releases on each of 11-16, 11-17 and 11-21.
   - `JAWS_PUBLIC_IMAGE_KEEP` is the escape hatch, and plan 05's `platform-base` `present` step names the fix when a base is gone.
2. **D2, the check-name prefix: `jwall`.** Decide before Task 3 merges: `brand.check_prefix` is configuration.
   - The site checks then read `… / jwall plan`. Check names are the company's under the white-label line (spec 4.8), though spec 6.7's list of what the owner's hub sets doesn't name them.
   - Check names change at each switch anyway (plan 05), so either choice costs nothing now.
   - To keep `jaws`, H4's `brand` leaves `check_prefix` out, and `BRAND` and the site callers say `jaws`.
3. **D3, the platform's own `Organization` tag:** it stays `Jaws-Platform` until takeover, then becomes `JWall-Engineering` in its own tag-only PR. Decide before Task 3 merges: `context.organization` is configuration.
   - Plan 07's acceptance plans then show no change at all. Spec 6.10's step 4 allows the tag update in them, but on every foundation and monitoring resource. A tag-only diff that long can hide a real change, and the plan comment truncates at 60,000 bytes.
   - To change it now, H4 also sets `context.organization`, and Task 3's `test_the_platform_keeps_its_names` changes with it. `test_the_configuration_is_jaws_s_but_the_hub_s_own_sections` then fails too, since `context` differs from `jaws`'s. Either that freeze test exempts `context.organization`, or plan 07's enabling release makes the same edit in `jaws`, which retags every foundation and monitoring resource from `jaws`.
4. **D4, where the comments App is installed:** `platform` and the three site repositories, not every onboarded owner. Plan 05's hand-off 3 and spec 7 say every owner, but only `site-plan`, `site-preview` and the hub's CI post comments. `remote-task` and `container-release` post none.
5. **D5, the costs from plan 07's enabling release:**
   - **the hub image's private ECR storage:** at most ten builds, about 2.8 GB, about $0.28 a month (plan 05 ruling 6, itself open);
   - **its pulls to GitHub's runners:**
     - each build is pulled once per repository that runs it (plan 05 ruling 4);
     - the projects' pulls replace the `jaws-cli` pulls they make today;
     - the sweep's are new: about 283 MiB per hub release, about 9 GB a month at one release a day;
     - that is inside the account's free 100 GB a month of data transfer out, and $0.09 a GB beyond it.
6. **D6, `live`'s mover: decided** (2026-11-24). A dedicated App, JWall Engineering Deployments (`jwall-engineering-deployments`, ruling 10).
   - Why: the release App is installed on every repository, and its key is an organization secret visible to all of them. As `live`'s bypass actor, a workflow in any JWall-Engineering repository could mint a token for `platform` and move `live` to any commit, past plan 05's `platform-move` checks, and every switched project runs what `live` names. It also holds no *Workflows*, under which GitHub lists the refs API's updates.
   - So Deployments holds *Contents* and *Workflows* write and *Metadata* read, is installed on `platform` only, keeps its key in the `platform` repository secret `DEPLOYMENTS_APP_PRIVATE_KEY`, and is `live`'s only bypass actor. The release App keeps Release Please's job only.
   - Plan 05 is amended to match, before it executes: `platform-release.yml` and `platform-rollback.yml` take a new input, `live-app-client-id`, and a new secret, `live-app-private-key`, and mint the `live`-moving token from them. Plan 07's callers pass Deployments' client ID as a literal, as plan 05 ruling 16 does for the comments App, and `DEPLOYMENTS_APP_PRIVATE_KEY`.
   - Cost: one more App and one more key, both the owner's (H2, H3), and no money.
7. **D7, the old pins' image during the freeze** (plan 05's hand-off 1). Decide before Task 3 merges.
   - Every project's pin, `@v0.76.0`, pulls `jaws-cli:v0.76.0` in `site-plan`, `site-preview` and `site-deploy`, and `jaws-cli` keeps only the newest `ecr.keep_release_images` release images. At today's pace that image goes within days. Then every site's plan, preview and deploy fails to pull: the spec's anti-goal, "a window where a project's CI is broken".
   - **Recommended: keep the projects' pins recent by merging their Dependabot bumps,** until each project switches (plan 07). The bumps aren't configuration, so the freeze allows them, and they match the owner's by-hand choice for the hub's own pin (D1). Cost: the owner's attention, a bump merged in each site often enough that its pin stays among the kept images. One that slips breaks that site's CI until its bump merges.
   - **The alternative: raise `ecr.keep_release_images`** far enough to outlast the freeze. That is a new `jaws-cli` storage cost for the owner to approve, at most about $0.03 a month for each extra image kept (ruling 1's price of a base), less where images share layers. It is configuration, so it lands in `<tag>` (H0): H8 forbids it once Task 3 merges.

**Plan 05's five open decisions** are built on as written. Where another answer would change plan 06:

| Plan 05 | Another answer would change |
|---|---|
| Ruling 6, ten builds | D5's storage line only |
| Ruling 7, `current` and `live` before monitoring's apply | nothing here: the release caller is plan 07's |
| Ruling 9, a rollback moves `live` | the `live` ruleset: with `current` alone, a second ruleset blocks force pushes for every actor, the Deployments App included |
| Ruling 10, the identity as literals | the callers and the render: they'd spell no account ID, and plan 07's switch PRs would set it in each project |
| Ruling 12, a dedicated upgrade App | no upgrade App and no `UPGRADES_APP_PRIVATE_KEY`. `upgrade.yml` passes the release App's client ID and `RELEASE_BOT_PRIVATE_KEY`, and the owner grants the release App *Workflows* on every repository |

## Owner hand-offs

The agent does none of these. Each needs the owner's credentials, an App's key, `admin:org`, or the GitHub UI.

- **H0, before Task 1.**
  - Plan 05, amended for D6, is merged and released, and plan 04's hand-off is done, so `public.ecr.aws/<alias>/jaws:<tag>` exists. `<tag>` is that release or a later one.
  - Every configuration change meant to land before the freeze is merged in `jaws` and released in `<tag>`, if it is still to do: for example `monitoring.cost.protect_raw: true` (spec 6.10), and `ecr.keep_release_images` if D7 takes the alternative. Task 3 checks that `main`'s `config/` and `datasets/` are `<tag>`'s.
  - Each of those `jaws` releases lands between 08:00 and 24:00 MT. They apply monitoring, and a release while the monitoring node is stopped, 00:00–08:00 MT, replaces it (plan 05's Global Constraints).
  - D7, the old pins' image, is decided before Task 3 merges. With the recommendation, the projects' Dependabot bumps keep merging through the freeze.
- **H1, if Task 1 can't create the repository:** create `JWall-Engineering/platform`, public and empty (no README, license or `.gitignore`), with Task 1's description.
- **H2, after Task 1 creates `platform` and before H5's first run: the three Apps** (ruling 10). The `live` ruleset names Deployments, so it exists first.
  - For each: no webhook; the avatar from `jwall-engineering-branding` as its logo, with the badge background Green, `#367456`; and a private key.
  - Install Comments on `platform` only for now (H6 adds the sites), and Upgrades and Deployments on `platform` only.
  - Give the agent Comments' and Upgrades' client IDs, for Task 5. Deployments' is for plan 07's callers. None is secret.
- **H3, before Task 5's PR: the keys.** Set `COMMENTS_APP_PRIVATE_KEY`, `UPGRADES_APP_PRIVATE_KEY` and `DEPLOYMENTS_APP_PRIVATE_KEY` on `platform`, each with `gh secret set <NAME> --repo JWall-Engineering/platform < <its key>.pem`. Each is a repository secret, never an organization secret.
- **H4, during Task 3: the hub's own configuration.** One commit on Task 3's branch, `feat(config): add the hub's brand and identity`, with three edits.
  - In `config/tool.yaml`, after `context`:

    ```yaml
    # JWall Engineering's brand: the header of every comment, and the first word of the
    # site checks' names (config/README.md, "The brand").
    brand:
      name: JWall Engineering
      mark: https://raw.githubusercontent.com/JWall-Engineering/jwall-engineering-branding/main/assets/logo/jwall-engineering-logo.png
      check_prefix: jwall
    ```

  - In `config/platform.yaml`, after the first entry of `platform.repositories`, which stays as it is, at the file's own indentation:

    ```yaml
        # The hub, trusted second while jaws still applies (plan 03 ruling 2).
        - repository: JWall-Engineering/platform
          owner_id: "<gh api orgs/JWall-Engineering --jq .id>"
          repository_id: "<gh api repos/JWall-Engineering/platform --jq .id>"
      hub:
        repository: JWall-Engineering/platform
        image: jaws-platform
    ```

    Plan 07's enabling release adds these lines to `jaws`'s copy verbatim.
  - In the table of `config/README.md`, the `tool.yaml` row names `brand`.
- **H5: the repository's settings.**
  - Run `scripts/apply-repo-settings.sh` once Task 1's PRs have merged and CI has run once. Run it again after Tasks 2, 4 and 5, which each add a required check. Its first run makes JWall Engineering Deployments `live`'s only bypass actor (D6), and requires approval of every external contributor's fork pull requests.
  - Check that JWall Engineering Releases is installed on `platform`. It is installed on all repositories, so it should be.
  - Set the social preview from the branding repository's.
- **H6, before plan 07's switches:** install Comments on the three site repositories under `jwallace145`, and set `COMMENTS_APP_PRIVATE_KEY` on each.
- **H7:** merge the hub's first Release Please PR, for v0.1.0. It tags a version and ships nothing (ruling 2).
- **H8: the freeze and the owner's folders.**
  - From Task 3's merge until plan 07's takeover, no change goes into `config/` or `datasets/` in either repository. The one exception is plan 07's enabling-release edit: H4's `platform` lines, in `jaws`.
  - Pin bumps aren't configuration, so they carry on: the upgrade PR, the owner's by-hand bump (ruling 1), and the projects' Dependabot bumps (D7).
  - From Task 4's merge, apply `owner-access` and `billing-export` only from the hub's `owner/`.

## For plan 07

- The enabling release's configuration edit is H4's `platform` lines, verbatim.
- Once the roles trust the hub, require `platform / Terraform plan`, `platform / Monitoring plan` and `platform / Data access plan`. They go in `REQUIRED_PLATFORM_CHECKS` and `scripts/apply-repo-settings.sh`, and the PR template's line that two of them are expected red goes.
- At takeover:
  - add the applying callers of ruling 2, each with the account rendered as Task 5 renders it. `release.yml` and `rollback.yml` pass `live-app-client-id`, Deployments' client ID as a literal, and `live-app-private-key: ${{ secrets.DEPLOYMENTS_APP_PRIVATE_KEY }}` (D6), and `test_the_platform_s_apps_are_spelled_once` gains that client ID;
  - delete `tests/platform/test_freeze.py`, since the freeze ends;
  - open D3's `Organization` PR.
- The switches:
  - a project calls `JWall-Engineering/platform/.github/workflows/<name>.yml@live` with its own inputs, and reads the outputs it read from Jaws's workflow: each caller passes them on (Task 5);
  - a site passes `app-private-key: ${{ secrets.COMMENTS_APP_PRIVATE_KEY }}` (H6);
  - its checks then read `<project job> / <hub job> / jwall …`.
- Cleanup removes from `jaws`:
  - the moved checks (ruling 7);
  - `owner-access/` and `billing-export/`, with their tests and runbooks;
  - `config/` and `datasets/`.

---

### Task 1: The repository, its conventions and Release Please

**Files** (in `platform`):
- Create, in the scaffold: `README.md`, `LICENSE`, `.gitignore`
- Create, in the conventions PR, copied from `jwall-engineering-branding`'s `main` as `.github` copied them:
  - `.github/CODEOWNERS`, `.github/ISSUE_TEMPLATE/`, `.github/dependabot.yml`, `.github/pull_request_template.md`, `.github/workflows/ci.yml` (without its `assets` job);
  - `.pre-commit-config.yaml`, `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, `commitlint.config.mjs`, `package.json`, `package-lock.json`;
  - `scripts/apply-repo-settings.sh`, `scripts/test-commitlint.sh`, `tests/commitlint/`, `tools/commitlint/`.
- Create, in the Release Please PR, from the branding repository's 55aad06: `.github/workflows/release-please.yml`, `release-please-config.json`, `.release-please-manifest.json` (`{".": "0.0.0"}`), `version.txt` (`0.0.0`)
- Test: `tools/commitlint/scopes.test.mjs`

**Interfaces:**
- Produces `SCOPES`, in spec 6.12's order:
  - `config`: "config/: the platform's accounts, projects, guardrails and brand";
  - `datasets`: "datasets/: the onboarded-dataset registry";
  - `image`: "The Dockerfile and .dockerignore: the hub's image";
  - `workflows`: ".github/workflows/: the hub's CI and the callers of Jaws's workflows";
  - `owner`: "owner/: the owner's folders and their runbooks, applied only by the owner";
  - `repo`: "README, CONTRIBUTING, AGENTS, commitlint, the tests' harness, the PR and issue templates, and repository tooling";
  - `deps`: "Dependency updates: Dependabot's, and the upgrade PR's Jaws upgrades";
  - `release`: "Release Please's release pull requests and its config".

  `CONTRIBUTING.md`'s Scopes table mirrors them.
- Produces `scripts/apply-repo-settings.sh [owner/repo]`, which defaults to `JWall-Engineering/platform`. On top of the conventions' merge settings, labels and `main` ruleset, it applies:
  - `REQUIRED_CHECKS=(commitlint pr-title commitlint-rules)`, a quoted bash array that Tasks 2, 4 and 5 extend;
  - the `live` ruleset (ruling 11): `target: branch`, with `conditions: {ref_name: {include: ["refs/heads/live"], exclude: []}}`; rules `creation`, `update`, `deletion` and `non_fast_forward`; one bypass actor, `{"actor_type": "Integration", "actor_id": <gh api apps/jwall-engineering-deployments --jq .id>, "bypass_mode": "always"}` (D6);
  - the `prod` environment: `deployment_branch_policy: {protected_branches: false, custom_branch_policies: true}`, then one branch policy, `main`, added only if it's missing;
  - `PUT repos/$REPO/actions/permissions/workflow`, with `default_workflow_permissions=read` and `can_approve_pull_request_reviews=false`;
  - `PUT repos/$REPO/actions/permissions/fork-pr-contributor-approval`, with `approval_policy=all_external_contributors`.
- Produces `.github/dependabot.yml`: `github-actions` with `ignore: [{dependency-name: "Jaws-Platform/jaws*"}]`, and `npm`, each weekly with `chore(deps)`. Task 4 adds the owner's roots.
- Produces `.github/workflows/release-please.yml`: the conventions' workflow, unchanged. It tags releases and ships nothing (ruling 2).

- [ ] **Step 1: Create the repository**

```bash
gh repo create JWall-Engineering/platform --public \
  --description "JWall Engineering's platform: its configuration, its image of Jaws, and the workflows its projects call"
git clone https://github.com/JWall-Engineering/platform.git ~/Projects/JWall-Engineering/platform
```

If GitHub refuses for permission, H1 is the owner's.

- [ ] **Step 2: Scaffold and push**
  - **`README.md`:** the header standard, with release, CI and license badges for `platform`. Then one paragraph: JWall Engineering's platform configuration, its image of Jaws, and the workflows its projects call, built with Jaws and part of JWall Engineering.
  - **`LICENSE`:** `.github`'s.
  - **`.gitignore`:** `jaws`'s Terraform, Node, editor and Python sections, and `.jaws/` (the CLI's run files), plus `.jaws-tool/` (Task 2's checkout).

```bash
git add README.md LICENSE .gitignore
git commit -m "chore(repo): initial scaffold"
git push origin main
```

This is the only direct push.

- [ ] **Step 3: Write the failing test** in `tools/commitlint/scopes.test.mjs`

```js
test("the scopes are spec 6.12's, in its order", () => {
  assert.deepEqual(Object.keys(SCOPES), [
    "config", "datasets", "image", "workflows", "owner", "repo", "deps", "release",
  ]);
});
```

- [ ] **Step 4: Run it and watch it fail**

Run: `npm ci && npm test`
Expected: FAIL. The copied `SCOPES` are the branding repository's.

- [ ] **Step 5: Adapt the copies**
  - `SCOPES` and the Scopes table, per the Interfaces.
  - The fixtures: `tests/commitlint/valid/feat-scope.txt` becomes `feat(config): onboard a project`, and `invalid/unknown-scope.txt` uses `assets`, a scope the hub doesn't have.
  - `package.json`: name `jwall-engineering-platform`, and its description. `package-lock.json`: both its `name` fields, the top level's and `packages[""]`'s, as `.github` changed its own.
  - The PR template's example: `feat(config): onboard a project`.
  - `CONTRIBUTING.md` and `AGENTS.md` describe the hub: what it holds, its checks, and that its releases ship nothing until plan 07. `AGENTS.md` also carries the Global Constraints' privacy rules, verbatim.
  - `scripts/apply-repo-settings.sh`, per the Interfaces.

- [ ] **Step 6: Run the checks and watch them pass**

Run: `npm test && shellcheck scripts/apply-repo-settings.sh scripts/test-commitlint.sh`
Expected: PASS, including "CONTRIBUTING.md lists exactly the configured scopes, in order".

- [ ] **Step 7: Open the two PRs, one after the other**

```bash
git switch -c conventions
git add -A && git commit -m "chore(repo): add the repository conventions, commitlint and ci"
git push -u origin conventions
gh pr create --title "chore(repo): add the repository conventions, commitlint and ci" --body-file <filled template>
# once it has merged:
git switch main && git pull --ff-only && git switch -c release-please
git add -A && git commit -m "ci(release): add release please"
git push -u origin release-please
gh pr create --title "ci(release): add release please" --body-file <filled template>
```

- [ ] **Step 8: Verify the settings and the commit rules,** once both PRs have merged and the owner has run H5.

Run: `gh api repos/JWall-Engineering/platform/rulesets --jq '[.[].name] | sort'`, `gh api repos/JWall-Engineering/platform/environments --jq '[.environments[].name]'` and `gh api repos/JWall-Engineering/platform/actions/permissions/fork-pr-contributor-approval --jq .approval_policy`
Expected: `["live","main"]`, `["prod"]` and `all_external_contributors`.

Then open a draft PR from a branch `verify-commitlint`, titled with the scope `assets`, and push its three commits in two rounds:
- first, one with only a `Co-authored-by` trailer after a blank line. Expected: `commitlint` passes;
- then one without a scope and one with a body. Expected: `commitlint` fails, and its log names both.

Expected throughout: `pr-title` fails on `assets`. Close the PR and delete its branch.

---

### Task 2: The image and the hub's test harness

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `pyproject.toml` (tool settings only, with no `[project]` table)
- Create: `tests/__init__.py`, `tests/conftest.py`, `tests/platform/__init__.py`, `tests/platform/test_image.py`, `tests/platform/test_ci.py`
- Modify: `.github/workflows/ci.yml` (the job `tests`), `scripts/apply-repo-settings.sh` (`tests` joins `REQUIRED_CHECKS`), `README.md` ("The image"), `CONTRIBUTING.md` (running the tests)

**Branch:** `image`, from an up-to-date `main`: `git switch main && git pull --ff-only && git switch -c image`.

**Interfaces:**
- Produces the `Dockerfile`, with these four instructions and its comment. `platform-build` (plan 05) adds the revision, source and base labels at build time.

```dockerfile
# JWall Engineering's image of Jaws: the pinned Jaws release, with the platform's
# configuration and datasets where the CLI and the stacks look. The pin moves only with
# every workflow pin, in one commit, by the upgrade PR or by hand (plan 05 ruling 11).
FROM public.ecr.aws/<alias>/jaws:<tag>@sha256:<digest>
LABEL org.opencontainers.image.title="jaws-platform" \
      org.opencontainers.image.vendor="JWall Engineering" \
      org.opencontainers.image.description="JWall Engineering's platform: a Jaws release with its configuration and datasets"
COPY config/ /etc/jaws/config/
COPY datasets/ /etc/jaws/datasets/
```

- Produces `.dockerignore`, with three lines and their comment: `*`, `!config` and `!datasets`. Neither `owner/` nor the tests ever reach the image.
- Produces, in `tests/conftest.py`:
  - `REPO_ROOT`, `PLATFORM_CONFIG_DIR = REPO_ROOT / "config"` and `WORKFLOWS = REPO_ROOT / ".github" / "workflows"`;
  - `JAWS_SOURCE = Path(os.environ.get("JAWS_SOURCE", REPO_ROOT / ".jaws-tool"))`: the checkout of the pinned release;
  - `FROM_PATTERN`, imported from the pinned release's `jaws.platform` (plan 05, Task 7), never copied;
  - `def pinned_release() -> tuple[str, str, str]`: the `Dockerfile`'s base name, tag and digest, by `FROM_PATTERN`;
  - `def workflow(path: Path) -> dict[str, Any]`: a workflow read with `yaml.safe_load`, with `on` restored from the `True` key PyYAML gives it;
  - `def jaws_workflow(name: str) -> dict[str, Any]`: `workflow(JAWS_SOURCE / ".github" / "workflows" / name)`.
- Produces the CI job `tests`, named `tests`, with `permissions: {contents: read}`. Its steps:
  1. the checkout;
  2. `id: base`, which writes `tag=` from the `Dockerfile`'s `FROM` by `FROM_PATTERN`, or fails with plan 05's rule 1 message. It runs before the release is checked out, so it holds the pattern verbatim;
  3. `actions/checkout` of `Jaws-Platform/jaws` at `${{ steps.base.outputs.tag }}`, with `path: .jaws-tool` and `persist-credentials: false`;
  4. `astral-sh/setup-uv`, pinned to a release as the branding repository's CI pins it, since it publishes no major tag;
  5. `uv sync --project .jaws-tool --locked`;
  6. `uv run --project .jaws-tool --locked` of `ruff format --check tests`, `ruff check tests` and `pytest`.
- Produces `pyproject.toml`: `jaws`'s `[tool.ruff]` and `[tool.ruff.lint]`, and `[tool.pytest.ini_options]` with `testpaths = ["tests"]` and `addopts = "-q"`.

- [ ] **Step 1: Write the failing tests**

In `tests/platform/test_image.py`, where `_instructions()` gives the `Dockerfile`'s instructions with comments dropped and continuation lines joined:

```python
def test_the_image_is_the_pinned_release_with_the_configuration_and_the_datasets() -> None:
    name, tag, digest = pinned_release()
    assert re.fullmatch(r"public\.ecr\.aws/[a-z0-9][a-z0-9._-]*/jaws", name)
    assert [i.split()[0] for i in _instructions()] == ["FROM", "LABEL", "COPY", "COPY"]
    assert _instructions()[0] == f"FROM {name}:{tag}@{digest}"
    assert _instructions()[2:] == [
        "COPY config/ /etc/jaws/config/",
        "COPY datasets/ /etc/jaws/datasets/",
    ]


def test_only_the_configuration_and_the_datasets_enter_the_build() -> None:
    lines = (REPO_ROOT / ".dockerignore").read_text().splitlines()
    assert [line for line in lines if line and not line.startswith("#")] == [
        "*",
        "!config",
        "!datasets",
    ]
```

In `tests/platform/test_ci.py`:
- `test_the_tests_run_on_the_release_the_dockerfile_pins`:
  - the `tests` job's checkout of `Jaws-Platform/jaws` has `ref: ${{ steps.base.outputs.tag }}`, `path: .jaws-tool` and `persist-credentials: False`;
  - every other line of a workflow that names `Jaws-Platform/jaws`, comments aside, is a `uses: Jaws-Platform/jaws/.github/workflows/<file>@<ref>` call. The one exception is that checkout's `repository: Jaws-Platform/jaws` line. So no third pin can hide in a step.
- `test_the_tests_read_the_base_as_the_check_reads_it`: the `base` step's `run` holds `FROM_PATTERN`, imported from `jaws.platform`, verbatim.
- `test_dependabot_never_bumps_a_jaws_pin` (Review Focus 2): `dependabot.yml` has no `docker` ecosystem, and its `github-actions` entry's `ignore` holds `{"dependency-name": "Jaws-Platform/jaws*"}`.
- `test_every_ci_job_is_a_required_check`: `REQUIRED_CHECKS`, parsed from the script with `shlex`, equals the names of `ci.yml`'s jobs that run steps, plus `REQUIRED_PLATFORM_CHECKS`. That constant is `[]` here; Task 5 fills it.

- [ ] **Step 2: Run them and watch them fail**

Run: `git clone --depth 1 --branch <tag> https://github.com/Jaws-Platform/jaws.git .jaws-tool && uv run --project .jaws-tool --locked pytest tests/platform`
Expected: FAIL. There is no `Dockerfile` and no `tests` job.

- [ ] **Step 3: Write the files** per the Interfaces. The digest is the one the release's summary printed. `docker buildx imagetools inspect public.ecr.aws/<alias>/jaws:<tag>` shows it too.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run --project .jaws-tool --locked ruff format --check tests && uv run --project .jaws-tool --locked ruff check tests && uv run --project .jaws-tool --locked pytest`
Expected: PASS.

- [ ] **Step 5: Docs.** `README.md`, "The image":
  - what it holds;
  - where it goes: `jaws-platform` in the platform account, which plan 07's enabling release creates;
  - its tags, `sha-<commit>` and `current` (plan 05);
  - that its pin moves only with every workflow pin, in one commit: by the upgrade PR, or by the owner's by-hand bump (ruling 1).

- [ ] **Step 6: Commit and open the PR**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py tests/platform/__init__.py
git commit -m "test(repo): add the hub's test harness on the pinned jaws release"
git add Dockerfile .dockerignore tests/platform/test_image.py
git commit -m "feat(image): build the hub's image from jaws <tag>"
git add .github/workflows/ci.yml scripts/apply-repo-settings.sh tests/platform/test_ci.py
git commit -m "ci(workflows): run the hub's tests on the jaws release the dockerfile pins"
git add README.md CONTRIBUTING.md && git commit -m "docs(repo): describe the hub's image and how to run its tests"
git push -u origin image
gh pr create --title "feat(image): build the hub's image from a pinned jaws release" --body-file <filled template>
```

---

### Task 3: The configuration and the datasets

> **Reviews (Global Constraints):** this task's `config/` and `datasets/` commits, H4's included, are sealed. No `git diff`, `git show`, `git log -p` or `review-package` runs over a range that holds them. The controller writes the review package as "Reviews" says, and every prompt carries the Privacy rules and "Reviews" verbatim.

**Files:**
- Create, copied whole from `jaws` at `<tag>`: `config/`, `datasets/`
- The owner edits `config/` in H4.
- Create, in `tests/platform/`: `test_config_layout.py`, `test_owner_registry.py`, `test_owner_rules.py`, `test_owner_image_labels.py`, `test_hub_identity.py`, `test_freeze.py`
- Modify: `tests/conftest.py`, `README.md` ("The configuration")

**Branch:** `configuration`, from an up-to-date `main`: `git switch main && git pull --ff-only && git switch -c configuration`. Not `config`, which git would confuse with the directory.

**Interfaces:**
- Consumes: `PLATFORM_CONFIG_DIR`, `JAWS_SOURCE` and `pinned_release()` (Task 2); from `jaws`, `jaws.settings.load_document` and `load_settings`, `jaws.errors.ConfigError` and `jaws.image.label_namespace`.
- Produces, in `tests/conftest.py`:
  - `def platform_settings(path: Path = PLATFORM_CONFIG_DIR) -> Settings`. It returns `load_settings(path, environ={})`. On `ConfigError` it calls `pytest.fail(NOT_LOADED, pytrace=False)`, never with the error's text. `NOT_LOADED` is "config/ does not load with the pinned Jaws release: run `jaws config show` in the hub's image to see why";
  - `def owner_values(document: Mapping[str, Any]) -> set[str]`: `jaws`'s `owner_values()` from `tests/platform/test_no_owner_values.py`, for a given document;
  - `HUB = {"repository": "JWall-Engineering/platform", "image": "jaws-platform"}`;
  - `BRAND = {"name": "JWall Engineering", "mark": LOGO, "check_prefix": "jwall"}`, where `LOGO` is H4's URL.
- Produces `SECTION_FILES`: `jaws`'s, plus `"brand": "tool.yaml"`. That is plan 02's hand-off.
- Produces, in `test_owner_rules.py`:
  - `RESERVED_KEYS = ("owner-access", "billing-export", "monitoring", "release-infra")`;
  - `MAX_PROJECT_KEY = 15` and `MAX_RESEARCH_PROJECT_KEY = 30`, each documented as `jaws`'s measurement in `tests/test_bots_registry.py`.

- [ ] **Step 1: Write the failing tests**

The moved checks are `jaws`'s, with `platform_settings()` and the local constants: `test_every_section_is_in_its_file`, `test_the_owner_s_configuration_loads`, `test_the_engine_s_old_project_name_is_gone`, `test_no_project_takes_a_reserved_key`, `test_registered_keys_fit_the_apply_policy_size` and `test_the_owner_s_label_namespace_is_unchanged`. Then the new ones.

In `test_config_layout.py` (Review Focus 3):

```python
def test_a_configuration_that_does_not_load_is_reported_without_its_values(
    tmp_path: Path,
) -> None:
    document = load_document(PLATFORM_CONFIG_DIR)
    broken = copy.deepcopy(document)
    broken["aws"]["accounts"][broken["aws"]["primary"]]["account_id"] = "not-an-account"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(broken))
    with pytest.raises(pytest.fail.Exception) as failed:
        platform_settings(path)
    if leaked := [value for value in owner_values(document) if value in str(failed.value)]:
        pytest.fail(f"the report holds {len(leaked)} owner values", pytrace=False)
```

In `test_hub_identity.py`:
- `test_the_hub_is_this_repository_and_trusted_second`:
  - `platform.hub` is `HUB`;
  - `[r.repository for r in platform.repositories] == ["Jaws-Platform/jaws", "JWall-Engineering/platform"]`.
- `test_the_hub_s_ids_are_this_repository_s`, skipped outside Actions: the second entry's `owner_id` and `repository_id` are `GITHUB_REPOSITORY_OWNER_ID` and `GITHUB_REPOSITORY_ID`. A failure names the field.
- `test_the_brand_is_jwall_engineering_s`: the brand's three fields are `BRAND`'s.
- `test_the_platform_keeps_its_names`: `context.name_root == "jaws"`, `context.managed_by == "JAWS"`, `context.organization == "Jaws-Platform"` (D3) and `context.tags == {}`.

In `test_freeze.py` (Review Focus 1, ruling 4):

```python
def _platform_is_jaws_s_but_the_hub_s(ours: dict[str, Any], theirs: dict[str, Any]) -> bool:
    """The hub's copy may add its own entry after jaws's, and name itself the hub."""
    first = theirs["repositories"]
    extra = [entry["repository"] for entry in ours["repositories"][len(first) :]]
    rest = {"repositories", "hub"}
    return (
        ours["repositories"][: len(first)] == first
        and extra in ([], [ours["hub"]["repository"]])
        and theirs.get("hub") in (None, ours["hub"])
        and {k: v for k, v in ours.items() if k not in rest}
        == {k: v for k, v in theirs.items() if k not in rest}
    )


def test_the_configuration_is_jaws_s_but_the_hub_s_own_sections() -> None:
    """The freeze (spec 6.10): every section is jaws's at the pinned release, but brand."""
    ours, theirs = load_document(PLATFORM_CONFIG_DIR), load_document(JAWS_SOURCE / "config")
    differing = sorted(
        section
        for section in set(ours) | set(theirs)
        if section not in ("brand", "platform") and ours.get(section) != theirs.get(section)
    )
    if not _platform_is_jaws_s_but_the_hub_s(ours["platform"], theirs["platform"]):
        differing.append("platform")
    if differing:
        pytest.fail(f"config/ differs from jaws's in {', '.join(differing)}", pytrace=False)
```

Also `test_the_datasets_are_jaws_s`: every file under `datasets/` has the bytes of the same path under `JAWS_SOURCE / "datasets"`, and neither side has a file the other lacks. A failure gives the count.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --project .jaws-tool --locked pytest tests/platform`
Expected: FAIL. There is no `config/` or `datasets/`.

- [ ] **Step 3: Copy both directories whole,** naming no file and printing only hashes

```bash
jaws=~/Projects/Jaws-Platform/jaws
git -C "$jaws" fetch --tags origin
for dir in config datasets; do
  test "$(git -C "$jaws" rev-parse <tag>:$dir)" = "$(git -C "$jaws" rev-parse origin/main:$dir)" \
    || { echo "$dir: main has changed since <tag>: stop (H0)"; exit 1; }
done
git -C "$jaws" archive --format=tar <tag> config | tar -x -C .
git add config && git commit -m "feat(config): copy the platform's configuration from jaws <tag>"
git -C "$jaws" archive --format=tar <tag> datasets | tar -x -C .
git add datasets && git commit -m "feat(datasets): copy the onboarded-dataset registry from jaws <tag>"
for dir in config datasets; do
  test "$(git rev-parse HEAD:$dir)" = "$(git -C "$jaws" rev-parse <tag>:$dir)" && echo "$dir: byte for byte"
done
```

Expected: "config: byte for byte" and "datasets: byte for byte", and nothing else.

- [ ] **Step 4: The owner's edit (H4).** Push the branch with `git push -u origin configuration`, wait for the owner's commit on it, then `git pull --ff-only`.

- [ ] **Step 5: Run the tests and the image, and watch them pass**

Run: `uv run --project .jaws-tool --locked pytest`
Expected: PASS.

Run:

```bash
docker build -t platform:local .
docker run --rm --network none platform:local config show >/dev/null 2>&1; echo "config show: exit $?"
docker run --rm --network none --entrypoint sh platform:local -c \
  'test -f /etc/jaws/datasets/README.md && ls /etc/jaws/config/*.yaml | wc -l'
```

Expected:
- `config show: exit 0`;
- then `9`, the files of `SECTION_FILES`, once the datasets' `README.md` is found. The foundation refuses to plan without that README while Databricks is ready (plan 04).

If `docker build` can't pull its base, the pin has been pruned: stop until the owner bumps it by hand (ruling 1), then rebase and clone `.jaws-tool` again at the new tag.

- [ ] **Step 6: Docs.** `README.md`, "The configuration":
  - the table of files and sections, from `SECTION_FILES`;
  - that the configuration is `jaws`'s at `<tag>`, plus `brand` and the hub's identity;
  - the freeze, until plan 07's takeover;
  - that a person edits a configuration file, and an agent never prints one.

- [ ] **Step 7: Commit and open the PR**

```bash
git add tests && git commit -m "test(config): check the owner's configuration, the hub's identity and the freeze"
git add README.md && git commit -m "docs(repo): describe the hub's configuration and its freeze"
git push
gh pr create --title "feat(config): take the platform's configuration and datasets from jaws <tag>" --body-file <filled template>
```

The freeze (H8) starts when this PR merges, so the owner decides D2, D3 and D7 before it does.

---

### Task 4: The owner's folders and their guards

> **Reviews (Global Constraints):** this task's `owner/` commits are sealed: the folders, the runbooks and `owner/README.md`. No `git diff`, `git show`, `git log -p` or `review-package` runs over a range that holds them. The controller writes the review package as "Reviews" says, and every prompt carries the Privacy rules and "Reviews" verbatim.

**Files:**
- Create, copied whole from `jaws` at `<tag>`: `owner/owner-access/`, `owner/billing-export/`
- Create, copied from `jaws` at `<tag>`:
  - `owner/owner-access.md` and `owner/billing-export.md`, from `docs/`;
  - `.tflint.hcl`;
  - `.github/actions/terraform-init/action.yml`.
- Create: `owner/config`, a link to `../config`; `owner/README.md`; `tests/platform/test_owner_folders.py`
- Modify: `owner/billing-export/README.md` (one path)
- Modify:
  - `.github/workflows/ci.yml`: the jobs `owner-access` and `billing-export`;
  - `.github/dependabot.yml`: `terraform` for `/owner/owner-access` and `/owner/billing-export`;
  - `scripts/apply-repo-settings.sh`, `tests/conftest.py` (`hcl_values`), `README.md` ("The owner's folders") and `AGENTS.md`.

**Branch:** `owner-folders`, from an up-to-date `main`: `git switch main && git pull --ff-only && git switch -c owner-folders`.

**Interfaces:**
- Consumes: `platform_settings()` (Task 3), and `workflow()` and `WORKFLOWS` (Task 2).
- Produces the jobs `owner-access` and `billing-export`, each named as its id. Each is `jaws`'s `owner-access-stack` or `billing-export-stack` job, with:
  - `working-directory: owner/<root>`;
  - `permissions: {contents: read}`;
  - no `id-token`, no credentials, and no `terraform plan|apply|destroy`.
- Produces `def hcl_values(path: Path) -> dict[str, str]` in `tests/conftest.py`: a backend file's `key = "value"` lines, parsed as `jaws`'s `tests/platform/test_foundation_backend.py` parses them. Its result holds the bucket, whose name holds an account ID, so no test asserts on it whole.

- [ ] **Step 1: Write the failing tests** in `tests/platform/test_owner_folders.py`
- `test_the_owner_s_folders_read_the_hub_s_configuration`: `owner/config` is a link, and resolves to `PLATFORM_CONFIG_DIR`.
- `test_their_state_keys_are_their_reserved_prefixes`: for each root, `hcl_values` of `owner/<root>/backend/prod.hcl` has `key == f"project={root}/env=prod/{root}-prod.tfstate"` and `region == "us-east-1"`. Like its siblings, a mismatch fails with `pytest.fail(f"owner/{root}/backend/prod.hcl: {field}", pytrace=False)`, never a bare `assert`, whose report would print the dict and the bucket's account ID.
- `test_their_state_is_in_the_management_account_s_owner_only_bucket`: `jaws`'s check from `test_state_backends.py`. Each bucket is `jaws-owner-access-state-<the management account's ID>`, and neither is `state.bucket`. A failure names the file.
- `test_ci_only_checks_the_owner_s_folders` (Review Focus 5):
  - across `.github/workflows/*.yml`, the jobs whose text names `owner-access` or `billing-export` are exactly `ci.yml`'s `owner-access` and `billing-export`;
  - each has `permissions == {"contents": "read"}`;
  - no step `uses` `aws-actions/configure-aws-credentials`;
  - no `run` matches `terraform (plan|apply|destroy)`.
- `test_the_runbooks_run_from_the_hub_s_root`:
  - neither runbook holds `cd owner-access`, `chdir=owner-access` or `cd billing-export`;
  - every relative link in them resolves to a path under `owner/`.

  A failure gives the runbook and a count.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --project .jaws-tool --locked pytest tests/platform/test_owner_folders.py`
Expected: FAIL. There is no `owner/`.

- [ ] **Step 3: Move the folders whole,** printing only hashes

```bash
jaws=~/Projects/Jaws-Platform/jaws
git -C "$jaws" archive --format=tar --prefix=owner/ <tag> owner-access billing-export | tar -x -C .
ln -s ../config owner/config
git add owner && git commit -m "feat(owner): move owner-access and billing-export from jaws <tag> unchanged"
for root in owner-access billing-export; do
  test "$(git rev-parse HEAD:owner/$root)" = "$(git -C "$jaws" rev-parse <tag>:$root)" && echo "$root: byte for byte"
done
```

Expected: "owner-access: byte for byte" and "billing-export: byte for byte", and nothing else.

- [ ] **Step 4: Move the runbooks, and rewrite their paths by counted substitution**

```bash
git -C "$jaws" archive --format=tar <tag> docs/owner-access.md docs/billing-export.md | tar -x -C owner --strip-components=1
```

Apply each substitution with `perl -pi -e`. Count each pattern with `grep -c`, before and after, and print only the counts. The counts are `jaws` `main`'s at e6f7096. If `<tag>`'s differ, stop and hand that file to the owner.

| File | From | To | Count |
|---|---|---|---|
| `owner/owner-access.md` | `cd owner-access` | `cd owner/owner-access` | 1 |
| | `chdir=owner-access` | `chdir=owner/owner-access` | 3 |
| | `](../owner-access)` | `](owner-access)` | 1 |
| `owner/billing-export.md` | `](../billing-export/` | `](billing-export/` | 2 |
| | `](costs.md`, `](monitoring.md`, `](remote-tasks.md` | `](https://github.com/Jaws-Platform/jaws/blob/main/docs/` plus the same name | 1, 2, 1 |
| `owner/billing-export/README.md` | `cd billing-export` | `cd owner/billing-export` | 1 |

The owner reads the runbooks' prose in the PR. The agent doesn't read them, since they hold account IDs.

- [ ] **Step 5: Write the rest** per the Interfaces.
  - **The tooling, copied:** `git -C "$jaws" archive --format=tar <tag> .tflint.hcl .github/actions/terraform-init | tar -x -C .`. Neither holds an owner value.
  - **`owner/README.md`**, with no values:
    - what each root is;
    - that only the owner applies them, from their own shell with admin credentials, and that CI never plans or applies them;
    - where their state is;
    - why `owner/config` is a link;
    - that `jaws bootstrap` replaces them later (spec 6.9).
  - **`README.md`, "The owner's folders":** a summary that links `owner/README.md`.
  - **`AGENTS.md`:** never display `owner/`; never add `id-token` or credentials to a job that names it.

- [ ] **Step 6: Run everything and watch it pass**

Run: `uv run --project .jaws-tool --locked pytest`
Expected: PASS.

Run, for each root:

```bash
(cd owner/<root> && terraform init -backend=false -input=false >/dev/null 2>&1 \
  && terraform validate -no-color >/dev/null 2>&1; echo "validate: exit $?"; terraform test -no-color 2>&1 | tail -1)
tflint --init --config "$PWD/.tflint.hcl" >/dev/null 2>&1 \
  && tflint --chdir owner/<root> --config "$PWD/.tflint.hcl" >/dev/null 2>&1; echo "tflint: exit $?"
```

Expected: `validate: exit 0`, then `Success! N passed, 0 failed.`, then `tflint: exit 0`. On a failure, hand the root to the owner: its errors and tflint's findings quote the source.

- [ ] **Step 7: Commit and open the PR**

```bash
git add owner/owner-access.md owner/billing-export.md owner/billing-export/README.md owner/README.md
git commit -m "docs(owner): move the owner's runbooks beside their folders"
git add .tflint.hcl .github scripts/apply-repo-settings.sh
git commit -m "ci(owner): validate, lint and test the owner's folders, and never plan or apply them"
git add tests && git commit -m "test(owner): guard the owner's folders' state and ci"
git add README.md AGENTS.md && git commit -m "docs(repo): describe the owner's folders in the hub"
git push -u origin owner-folders
gh pr create --title "feat(owner): move the owner's folders from jaws, with their guards" --body-file <filled template>
```

From its merge, the owner applies both roots only from the hub (H8).

---

### Task 5: The callers

> **Reviews (Global Constraints):** this task's commit of the six project-facing callers is sealed, since five of them hold the rendered account. No `git diff`, `git show`, `git log -p` or `review-package` runs over a range that holds it, and a reviewer reads each caller only through the mask. The controller writes the review package as "Reviews" says, and every prompt carries the Privacy rules and "Reviews" verbatim.

**Files:**
- Create, in `.github/workflows/`: `upgrade.yml`, `site-plan.yml`, `site-preview.yml`, `site-deploy.yml`, `site-release-please.yml`, `remote-task.yml`, `container-release.yml`
- Create: `tests/platform/test_callers.py`
- Modify:
  - `.github/workflows/ci.yml`: the job `platform`;
  - `scripts/apply-repo-settings.sh` and `tests/platform/test_ci.py`: `platform / Platform check` joins the required checks and `REQUIRED_PLATFORM_CHECKS`;
  - `tests/conftest.py`: `COMMENTS_APP_CLIENT_ID` and `UPGRADES_APP_CLIENT_ID`, H2's values;
  - `README.md` ("For project teams", "Upgrading Jaws"), `AGENTS.md` (the mask), and `.github/pull_request_template.md` (Verification).

**Branch:** `callers`, from an up-to-date `main`: `git switch main && git pull --ff-only && git switch -c callers`.

**Interfaces:**
- Consumes plan 05's workflows at `<tag>`:
  - `platform-ci.yml`, with the input `app-client-id` and the secret `app-private-key`;
  - `platform-upgrade.yml`, with both required;
  - the six project-facing workflows, which take `platform-image`, `account-id` and `name-root`. `site-plan`, `site-preview` and `site-deploy` also take `check-prefix`.
- Consumes `jaws platform check`; `IDENTITY_WORKFLOWS` and `CHECK_PREFIX_WORKFLOWS`, imported from the pinned release's `jaws.platform` (plan 05, Task 7); and H2's and H3's Apps and keys.
- Produces the job `platform` in `ci.yml`, with no `name`:
  - `uses: Jaws-Platform/jaws/.github/workflows/platform-ci.yml@<tag>`;
  - `with: {app-client-id: <Comments' client ID>}`;
  - `secrets: {app-private-key: ${{ secrets.COMMENTS_APP_PRIVATE_KEY }}}`;
  - `permissions: {contents: read, id-token: write, pull-requests: write}`.

  Its checks read `platform / <job name>`. `platform / Platform check` is required now, and plan 07 adds the plans.
- Produces `upgrade.yml`:
  - `on: {schedule: [{cron: "17 * * * *"}], workflow_dispatch: {}}`;
  - `concurrency: {group: upgrade, cancel-in-progress: false}`;
  - the job `upgrade`, which calls `platform-upgrade.yml@<tag>` with Upgrades' client ID, `secrets.UPGRADES_APP_PRIVATE_KEY` and `permissions: {contents: read}`.
- Produces the six project-facing callers. Each is `on: workflow_call`, with top-level `permissions: {}` and one job that calls its Jaws workflow at `<tag>`.
  - It offers every input of that workflow but `PLATFORM_INPUTS` and `ROLE_OVERRIDES`, with Jaws's type, required and default, and passes each through as `${{ inputs.<name> }}`. A description may be in the hub's own words: the tests leave descriptions out, so a Jaws rewording never fails the upgrade PR.
  - Every key of its job's `with:` is an input of that workflow at `<tag>`: the offered inputs, and the platform's own that the table lists.
  - It declares exactly that workflow's secrets, each with Jaws's `required`, and passes each through by name.
  - It declares every output of that workflow, by the same name and with its description, valued `${{ jobs.<job>.outputs.<name> }}`. A site's `release.yml` reads `release_created` and `tag` to decide and name its deploy.
  - Its job grants what that workflow's jobs declare.

  | Caller | Job | Spells, besides its inputs | Secrets | Outputs |
  |---|---|---|---|---|
  | `site-plan.yml` | `plan` | the identity, `check-prefix`, `app-client-id` | `app-private-key` | none |
  | `site-preview.yml` | `preview` | the identity, `check-prefix`, `app-client-id` | `app-private-key` | none |
  | `site-deploy.yml` | `deploy` | the identity, `check-prefix` | none | none |
  | `site-release-please.yml` | `release-please` | nothing | `RELEASE_BOT_CLIENT_ID`, `RELEASE_BOT_PRIVATE_KEY` | `release_created`, `tag` |
  | `remote-task.yml` | `task` | the identity | none | `outcome`, `interrupted-at` |
  | `container-release.yml` | `release` | the identity | none | none |

  The identity, as literals (plan 05 ruling 10): `platform-image: jaws-platform`, `account-id: "<rendered>"`, `name-root: jaws` and `check-prefix: jwall`.
- Produces the mask, the only way to read a caller: `sed -E 's/^( *account-id: )"[0-9]{12}"/\1"<account>"/' <caller>`.

- [ ] **Step 1: Write the failing tests** in `tests/platform/test_callers.py`

```python
PROJECT_FACING = (
    "site-plan",
    "site-preview",
    "site-deploy",
    "site-release-please",
    "remote-task",
    "container-release",
)
PLATFORM_INPUTS = {"platform-image", "account-id", "name-root", "check-prefix", "app-client-id"}
ROLE_OVERRIDES = {"plan-role-arn", "preview-role-arn", "apply-role-arn", "release-role-arn"}
# Not "description": the hub may word an input its own way, and a Jaws rewording
# mustn't fail the upgrade PR.
FIELDS = ("type", "required", "default")


@pytest.mark.parametrize("name", PROJECT_FACING)
def test_each_project_facing_caller_offers_what_jaws_takes_but_the_platform_s(name: str) -> None:
    offered = workflow(WORKFLOWS / f"{name}.yml")["on"]["workflow_call"].get("inputs", {})
    taken = jaws_workflow(f"{name}.yml")["on"]["workflow_call"].get("inputs", {})
    left = {k: v for k, v in taken.items() if k not in PLATFORM_INPUTS | ROLE_OVERRIDES}
    assert set(offered) <= set(left), f"{name}.yml offers an input Jaws {pinned_release()[1]} lacks"
    assert {k for k, v in left.items() if v.get("required")} <= set(offered)
    for key, spec in offered.items():
        assert [spec.get(f) for f in FIELDS] == [left[key].get(f) for f in FIELDS], key
```

The rest:
- `test_each_caller_passes_its_inputs_and_secrets_through_by_name`:
  - the one job's `uses` is `Jaws-Platform/jaws/.github/workflows/<name>.yml@<tag>`;
  - every key of its `with` is an input of the Jaws workflow at `<tag>`, compared as sets of keys. So an extra key, such as `app-client-id` given to `site-deploy`, fails here rather than at plan 07's switch;
  - its `with`, without `PLATFORM_INPUTS`, is `{k: "${{ inputs.k }}"}` for every offered input;
  - the caller's own `on.workflow_call.secrets` are exactly the Jaws workflow's, each with the same `required`;
  - its `secrets` is `{k: "${{ secrets.k }}"}` for every one of them, and never `inherit`.
- `test_each_caller_passes_its_outputs_through`: the caller's `on.workflow_call.outputs` has exactly the Jaws workflow's output names at `<tag>`, each valued `${{ jobs.<job>.outputs.<name> }}`, where `<job>` is its one job. So a new Jaws output fails the upgrade PR. As for inputs, descriptions aren't compared.
- `test_each_caller_grants_exactly_what_its_jaws_jobs_ask`, for the six callers, `ci.yml`'s `platform` and `upgrade.yml`'s `upgrade`: the caller job's `permissions` are the union of its Jaws workflow's jobs' `permissions`, where `write` outranks `read`.
- `test_every_identity_literal_is_the_configuration_s`: `identity_problems(WORKFLOWS, platform_settings())` is empty.
  - `def identity_problems(workflows: Path, settings: Settings) -> list[str]` returns one `"{file}: job {job} passes {key} other than the configuration's"` for each disagreement, a missing key included. In each job that calls a file of `IDENTITY_WORKFLOWS`, it compares `platform-image` with `platform.hub.image`, `account-id` with `aws.account_id` and `name-root` with `context.name_root`; in one that calls a file of `CHECK_PREFIX_WORKFLOWS`, also `check-prefix` with `brand.check_prefix`.
  - It repeats `platform check`'s rules 4 and 5 rather than calling `check_hub`, whose messages quote both values. Its own messages name only a file, a job and a key.
  - A failure joins them in `pytest.fail(..., pytrace=False)`.
- `test_a_wrong_identity_is_reported_without_its_values` (Review Focus 3): in a copy of `.github/workflows/` under `tmp_path`, `site-plan.yml`'s account becomes `"000000000000"`, by a regex on the text. `identity_problems` then returns exactly one problem, naming `site-plan.yml`, `plan` and `account-id`, and none of `owner_values(load_document(PLATFORM_CONFIG_DIR))` appears in it.
- `test_the_platform_s_apps_are_spelled_once`:
  - every `app-client-id` is `COMMENTS_APP_CLIENT_ID`, but `upgrade.yml`'s, which is `UPGRADES_APP_CLIENT_ID`;
  - the two differ, and both match `^Iv[0-9A-Za-z.]+$`.
- `test_no_workflow_runs_on_pull_request_target_or_inherits_secrets` (Review Focus 5), on the parsed YAML: no workflow's `on` holds `pull_request_target`, whether `on` is a string, a list or a mapping; no job's `secrets` is `inherit`; and every workflow's top-level `permissions` is `{}`. A comment may name either: plan 05 adds one to Jaws's own `site-release-please.yml`, and a caller may copy it.
- `test_the_upgrade_runs_hourly_and_never_overlaps`: the cron is `17 * * * *`, beside `workflow_dispatch`, and the concurrency is `{group: upgrade, cancel-in-progress: False}`.
- `test_no_caller_holds_the_release_s_concurrency_group` (plan 05, "For plans 06 and 07"), on the parsed YAML: no workflow, and no job of one, has a `concurrency` group of `platform-release`, whether `concurrency` is a string or a mapping. The text may name it: plan 07's `release.yml` calls `…/platform-release.yml@<tag>`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --project .jaws-tool --locked pytest tests/platform/test_callers.py`
Expected: FAIL. There are no callers.

- [ ] **Step 3: Write the callers** per the Interfaces. Write each `account-id` as `"__ACCOUNT_ID__"`, then render the account in without printing it:

```bash
docker build -t platform:local .
ACCOUNT_ID="$(docker run --rm --network none platform:local config env 2>/dev/null | sed -n 's/^account_id=//p')" \
  perl -pi -e 's/__ACCOUNT_ID__/$ENV{ACCOUNT_ID}/g' .github/workflows/*.yml
grep -c '__ACCOUNT_ID__' .github/workflows/*.yml
grep -c 'account-id: "[0-9]\{12\}"' .github/workflows/*.yml
grep -cE '[0-9]{12}' .github/workflows/*.yml
```

Expected:
- `0` placeholders in every file;
- `1` rendered account in each of `site-plan.yml`, `site-preview.yml`, `site-deploy.yml`, `remote-task.yml` and `container-release.yml`, and `0` in the rest;
- the same counts of lines with twelve digits in a row, so the mask hides every account.

If `docker build` can't pull its base, the pin has been pruned: stop until the owner bumps it by hand (ruling 1), then rebase and pin every call this branch adds to the new tag.

- [ ] **Step 4: Run the tests and the check, and watch them pass**

Run: `uv run --project .jaws-tool --locked pytest`
Expected: PASS.

Run:

```bash
docker run --rm --network none -v "$PWD:/hub:ro" -e GITHUB_REPOSITORY=JWall-Engineering/platform \
  platform:local platform check --root /hub >/dev/null 2>&1; echo "platform check: exit $?"
```

Expected: `platform check: exit 0`. Its errors print values, so its output goes nowhere. If it fails, `test_every_identity_literal_is_the_configuration_s` names the job and the key.

- [ ] **Step 5: Docs**
  - **`README.md`, "For project teams"**, which takes over `jaws`'s `docs/consumer-note.md`'s role:
    - onboarding is a hub PR to `config/projects.yaml`, after the freeze;
    - a project calls `JWall-Engineering/platform/.github/workflows/<name>.yml@live` once it has switched (plan 07), and names no Jaws version;
    - each caller's inputs, the outputs it passes on, and the permissions its job grants;
    - a site's `app-private-key: ${{ secrets.COMMENTS_APP_PRIVATE_KEY }}`;
    - that `secrets: inherit` stops at an organization;
    - the check names, `<project job> / <hub job> / jwall …`.
  - **`README.md`, "Upgrading Jaws"** (ruling 1):
    - the hourly upgrade PR, which bumps the `Dockerfile` and every pin at once, with its plans run on the candidate;
    - merge it within about two days, and within a day on a busy one: ECR Public keeps ten releases, and `jaws` shipped 12 to 13 on each of 11-16, 11-17 and 11-21;
    - when the base is gone, `platform / Platform check` fails with `present`'s error, which names the fixes: merge the open upgrade PR, or bump by hand, moving the `FROM` tag and digest and every `Jaws-Platform/jaws/.github/workflows/<file>@` pin together, in one commit;
    - never bump one pin alone;
    - to hold the hub back, or to keep a pin through a busy day, raise `JAWS_PUBLIC_IMAGE_KEEP` in `Jaws-Platform/jaws`;
    - during the freeze, a release that needs a configuration change waits. A workflow fix for an upgrade goes on a branch cut from `jaws-upgrade`, in its own PR, since the hourly run force-pushes `jaws-upgrade`; close the upgrade PR once the fix merges;
    - `platform / Terraform plan` and `platform / Data access plan` are red on every PR, the upgrade's and Release Please's included, until plan 07's enabling release. They fail at their credentials and aren't required. They stay red rather than skip: a skipped job satisfies a required check, so once plan 07 requires them, a broken trust would pass.
  - **`.github/pull_request_template.md`, Verification:** one line, that `platform / Terraform plan` and `platform / Data access plan` are expected red until plan 07's enabling release.
  - **`AGENTS.md`:** the render and the mask.

- [ ] **Step 6: Commit and open the PR**

```bash
git add .github/workflows/ci.yml && git commit -m "feat(workflows): check and plan every pull request with the hub's candidate image"
git add .github/workflows/upgrade.yml && git commit -m "feat(workflows): open the jaws upgrade pull request every hour"
git add .github/workflows && git commit -m "feat(workflows): give projects the hub's copies of jaws's workflows"
git add tests scripts/apply-repo-settings.sh
git commit -m "test(workflows): check the callers against jaws <tag> and the configuration"
git add README.md AGENTS.md .github/pull_request_template.md
git commit -m "docs(repo): tell project teams how to call the hub, and how it upgrades jaws"
git push -u origin callers
gh pr create --title "feat(workflows): call jaws's workflows from the hub, pinned to <tag>" --body-file <filled template>
```

Expected CI:
- `platform / Platform check` passes;
- until plan 07's enabling release, `platform / Terraform plan` and `platform / Data access plan` fail at their credentials, by design. `Monitoring plan` skips with a notice, and the project plans with a warning (plan 05). None of them is required.

If `Platform check` fails with `present`'s error instead, the base has been pruned: the owner bumps the pin by hand (ruling 1), and this branch rebases and moves every pin it adds to the new tag.

Then the owner runs H5. Dispatch `upgrade.yml` once: it prints "Jaws <tag> is the newest release", or opens the upgrade PR.

---

### Task 6: The organization's documents

**Files:**
- Modify: `JWall-Engineering/.github`'s `profile/README.md`
- Modify: `JWall-Engineering/jwall-engineering-branding`'s `README.md` (the Avatar row)

**Branches:** `add-platform` in each repository, from an up-to-date `main`: `git switch main && git pull --ff-only && git switch -c add-platform`.

Do this as soon as Task 1 has merged and H2 has made the Apps. The conventions update the profile as soon as a repository or App is added.

- [ ] **Step 1: The profile**
  - The Repositories table gains `platform`: "JWall Engineering's platform: its configuration and datasets, its image of Jaws, the workflows its projects call, and the owner's folders".
  - The GitHub Apps table gains `jwall-engineering-comments`, "Posts the platform's plan and preview comments"; `jwall-engineering-upgrades`, "Opens the pull request that upgrades the platform's Jaws release"; and `jwall-engineering-deployments`, "Moves the platform's `live` branch to each release, and back on a rollback".
  - "What's here, and what's coming", worded for the day it merges: `platform` is the hub that takes the configuration over from `jaws`, which holds and applies it until the takeover.

- [ ] **Step 2: The branding README.** The Avatar row's use names every App: Releases, Comments, Upgrades and Deployments.

- [ ] **Step 3: Run each repository's checks**

Run: `npm ci && npm test` in `.github`, and `scripts/check.sh` in `jwall-engineering-branding`
Expected: PASS.

- [ ] **Step 4: Commit, push and open the two PRs**

```bash
cd ~/Projects/JWall-Engineering/.github
git add profile/README.md && git commit -m "feat(profile): add the platform repository and its apps"
git push -u origin add-platform
gh pr create --title "feat(profile): add the platform repository and its apps" --body-file <filled template>
cd ~/Projects/JWall-Engineering/jwall-engineering-branding
git add README.md && git commit -m "docs(repo): name every app whose logo is the avatar"
git push -u origin add-platform
gh pr create --title "docs(repo): name every app whose logo is the avatar" --body-file <filled template>
```

Their Verification sections say the owner looked at the profile on GitHub.

---

### Task 7: Ready for plan 07

**Files:**
- Modify: `jaws`'s `docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md`, on `hub-split/06-hub` (draft PR #326)

Before Task 7 starts, rebase the plan's branch onto `main`, so a review's range starts after the rebase: `git switch hub-split/06-hub && git fetch origin && git rebase origin/main`.

- [ ] **Step 1: Check the hub's required checks,** after H5's last run

Run: `gh api repos/JWall-Engineering/platform/rulesets --jq '.[] | select(.name == "main") | .id'`, then `gh api repos/JWall-Engineering/platform/rulesets/<id> --jq '[.rules[] | select(.type == "required_status_checks") | .parameters.required_status_checks[].context] | sort'`
Expected: `billing-export`, `commitlint`, `commitlint-rules`, `owner-access`, `platform / Platform check`, `pr-title` and `tests`.

- [ ] **Step 2: Bring the roadmap up to date**
  - Row 06's status becomes "done: JWall-Engineering/platform".
  - Row 07 gains this plan's "For plan 07", in a few words.
  - "Before plan 06" becomes done. It names the release App `jwall-engineering-releases`, as the organization conventions do.
  - "During plan 07" gains H6 and H8.

```bash
git add docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md
git commit -m "docs(repo): add plan 06's rulings to the roadmap"
git push --force-with-lease
gh pr edit 326 --body-file <filled template>
gh pr ready 326
```

The body fills every template section, links the spec and this plan, and lists the owner decisions.

Expected: `jaws`'s CI passes, and every plan comment says merging leaves AWS alone.
