# Jaws as a product, plan 07: migration and cleanup: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Most of this plan is the owner's.** Run it in the order of "The run order": an agent task starts only once the owner step before it is done. Before any review, read the Global Constraints' "Privacy" and "Reviews". The owner's configuration edits, the hub's rendered callers and the cleanup's deletions are sealed commits.

**Goal:** Move the owner's platform onto `JWall-Engineering/platform` in place, with nothing in AWS rebuilt: the enabling release, the acceptance plans, the takeover and the seven project switches. Then take the owner's platform out of `jaws`, retire `jaws-cli` and the trust on `Jaws-Platform/jaws`, and rewrite the conventions.

**Architecture:**
- **Five phases, in spec 6.10's order.** Each ends at an owner gate.
  1. **Enable.** One `jaws` release adds the hub's identity to `jaws`'s `config/platform.yaml`. Its apply makes the platform's roles trust the hub, and creates the hub image's repository.
  2. **Accept.** The hub's next pull request plans every stack and project with real roles. Every plan must show no changes. The hub then requires its plans.
  3. **Take over.** In one sitting:
     - `jaws` stops applying, sweeping, planning the platform and pushing `jaws-cli`;
     - the hub gains its release, rollback, by-hand applies and sweep;
     - the hub's first release builds its image, applies with no changes, and creates `current` and `live`. The freeze ends.
  4. **Switch.** The seven projects call the hub at `@live`, one at a time.
  5. **Clean up.**
     - `jaws` loses `config/`, `datasets/`, the owner's folders, the project-facing workflows' mode without a platform image, and the `jaws-cli` stage. It gains a guard against owner values.
     - The hub checks the release it pins for its values, and retires the trust on `Jaws-Platform/jaws` and `jaws-cli`.
- **Agent tasks and owner steps are kept apart.** Agent tasks are pull requests and read-only checks. Every merge, every release, every AWS command and every repository setting is the owner's.

**Tech Stack:** GitHub Actions (reusable workflows, rulesets, environments, Apps), Release Please, Terraform 1.14.7 (`terraform test` with mock providers), Python 3.13 with uv, pytest, ruff and PyYAML, `gh`, yq, Docker.

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md):
- 6.10 and 6.11;
- 2: goal 1 and the anti-goals;
- 6.3, `jaws-cli` retired; 6.6, the old trust; 6.12, the cleanup's scopes.

Roadmap: [row 07](2026-11-23-hub-split-00-roadmap.md). It builds on plans 05 (#323) and 06 (#326).

**Written before plans 05 and 06 ran.** It follows them as approved: plan 05's rulings 6, 7, 9, 10 and 12, and plan 06's D1–D4 and D6. Ruling 3 shortens plan 06's D7, and Task 4 waits for the owner's answer. Task 1 re-checks every name it borrows against their merged code before anything else runs.

**Where the work happens:**

| Repository | Local clone | Tasks | Branches |
|---|---|---|---|
| `Jaws-Platform/jaws` | `~/Projects/Jaws-Platform/jaws` | 1, 2, 4, 9–14 | `hub-split/07-recheck`, `hub-split/07-enabling`, `hub-split/07-takeover`, `hub-split/07-cleanup` |
| `JWall-Engineering/platform` (the hub) | `~/Projects/JWall-Engineering/platform` | 3, 5, 6, 12 (its README), 15, 16 | one per PR, named in the task |
| The seven project repositories (Task 7) | `~/Projects/<owner>/<repo>`, cloned if missing | 7 | `switch-to-hub` |
| `jwallace145/repository-template`, `JWall-Engineering/.github`, `Jaws-Platform/.github` | `~/Projects/Common/Repository`, `~/Projects/JWall-Engineering/.github`, `~/Projects/Jaws-Platform/.github` | 8 | `hub-conventions` |

`<tag>` is the Jaws release the hub pins at the time. `<scratch>` is the session's scratchpad directory, never a repository.

## Global Constraints

- **Each repository's rules** (its `AGENTS.md` and `CONTRIBUTING.md`) bind its pull requests:
  - never push to `main`: one branch, one PR;
  - each commit is one line, `type(scope): subject`, at most 100 characters, with a lowercase subject and no trailing period. Only `Co-authored-by` trailers may follow, after a blank line;
  - the PR title is a valid commit header, and the body fills every section of the repository's template.
- **Scopes,** from each repository's `SCOPES`:
  - in `jaws`: `config` (Task 2 only), `workflows`, `cli`, `foundation`, `repo`;
  - in the hub: `config`, `workflows`, `repo`;
  - in the projects, their own (Task 7's table); `conventions` in `repository-template`; `profile` in both `.github` repositories.
- **Commits in public repositories use the owner's GitHub noreply address,** which the local git config already holds. Never change git config.
- **The agent never touches real infrastructure.** It never runs `terraform apply`, a `terraform plan` against real state, `jaws apply|publish|release|destroy`, `jaws platform plan|apply` with credentials, `docker push`, or any `aws` command. CI's plans are the only real plans, and the agent reads them with the plan filter.
- **The owner merges every PR in this plan,** in every repository: the project repositories' rules say so, and here every merge either releases or gates a release. The agent opens and updates PRs and comments on them, and writes nothing else on GitHub: no settings, rulesets, environments, variables, secrets or Apps.
- **Every change to AWS is the owner's merge of a release PR, between 08:00 and 24:00 MT.** The monitoring node is stopped from 00:00 to 08:00, and a release in that window replaces it. Each owner step says what to check before and after.
- **Money: nothing that costs money happens before G0,** the owner's go-ahead on "Costs". The first cost starts at the enabling release, whose apply lets the hub's PRs plan with real roles.
- **Nothing stateful is rebuilt** (spec 2). Every plan here is read with the filter. The only destroys in this plan are Task 16b's: `jaws-cli`, after the owner has emptied it, and the `-2` ECR policies that pointed at it.
- **Privacy** (plan 06's rules, which still bind the hub):
  - never print a value from `config/`;
  - never name an individual `config/` file in a command, except inside `git rev-parse <rev>:<path>`, which prints a hash;
  - every `config/` edit is the owner's;
  - read a file that may hold an account ID or an email (the README, `docs/`, the hub's callers) only through the mask: `sed -E 's/[0-9]{12}/<account-id>/g; s/[[:alnum:]._%+-]+@[[:alnum:].-]+\.[[:alpha:]]{2,}/<email>/g'`;
  - read a plan only through the plan filter;
  - change a file that holds a value by counted substitution: `perl -pi -e`, then `grep -c` of the old and the new pattern, before and after, printing only the counts;
  - a failing check names a file, a field or a count, never a value (`pytest.fail(..., pytrace=False)`); run pytest with `-q`;
  - if the privacy hook refuses a command, stop and hand that step to the owner. Never work around it.
- **Reviews.** A sealed commit touches `config/`, `datasets/`, `owner/`, a hub caller with a rendered account, or a file whose added or removed lines hold an account ID or an email.
  - Nobody runs `git diff`, `git show`, `git log -p` or `review-package` over a range that holds one, except `git diff --stat` and `--shortstat`, which print counts.
  - The controller writes the review package itself, as plan 06's "Reviews" says: `git log --oneline` and `git diff --stat` of the range, the diff of each commit that isn't sealed, and each sealed commit's evidence (its hashes, counts, filter output and test summary line).
  - Every implementer and reviewer prompt carries this rule and the Privacy rules verbatim.
- **The plan filter.** A plan's text is its job's log (`gh run view <run> -R <repo> --log --job <job>`), or its `.jaws/plan.txt` artifact (`gh run download <run> -R <repo> -n <artifact> -D <scratch>/<name>`). Read it only through these, which print resource addresses, actions, attribute names and counts, never values:

```sh
plan_actions() {  # stdin: a plan's text. Each resource's action, then the summary.
  sed -nE -e 's/.*# (.+) (will be created|will be updated in-place|will be destroyed|must be replaced)$/\2: \1/p' \
    -e 's/.*# (.+) has moved to (.+)$/moved: \1 -> \2/p' \
    -e 's/.*(Plan: [0-9]+ to add, [0-9]+ to change, [0-9]+ to destroy).*/\1/p' \
    -e 's/.*(No changes\.|Changes to Outputs:).*/\1/p'
}
plan_attributes() {  # stdin: a plan's text. How often each attribute name changes.
  sed -nE 's/^.*[[:space:]]~ ([a-z_]+)[[:space:]]+=.*/\1/p' | sort | uniq -c
}
```

- **Long commands** (`gh pr checks --watch`, `gh run watch`) run with the Bash tool's `run_in_background`, and the agent waits for the notification. Never an unbounded `until` or `while` loop.
- **Before each PR,** run the repository's own checklist: `jaws`'s `AGENTS.md` "Before opening a PR", the hub's from plan 06, or the project's `CONTRIBUTING.md`.

## Review Focus

1. **A required check that no job reports any more.** `jaws`'s takeover removes four required checks (three plans and the Databricks project list), and its cleanup two stack checks. The hub starts requiring three plans. Expected: the change that removes or adds a job changes the required checks with it, and a test fails otherwise. Without that, every later PR waits forever. Task 4, `test_every_required_check_is_a_ci_job` (run again in Task 12); Task 3, `test_every_ci_job_is_a_required_check`.
2. **A switched caller that passes an input the hub's caller doesn't take, or reads an output it doesn't pass.** A remote task runs days later, and fails then. Expected: Task 7's call check refuses the call before its PR opens, naming the file, the job and the key. Task 7, Steps 2 and 4.
3. **Two sweepers, or one left on in `jaws`.** Expected: from the takeover, no `jaws` workflow runs on a schedule, and the hub's sweep is the only one. Task 4, `test_jaws_s_own_workflows_are_its_ci_and_its_release`; Task 5, `test_the_release_runs_on_main_and_the_sweep_every_fifteen_minutes`.
4. **A platform stack run with no configuration,** once `config/` has left `jaws`. Expected: the plan stops at once, naming `/etc/jaws/config` and `config_path`, rather than failing deep in the stack. Task 9, `stops_without_a_configuration` in both stacks.
5. **An owner value back in the product:** in a doc, a test's sample value, the package description the public image carries, or a design record. Expected: a check fails on the file, naming its rule and a count, never the value. Task 13, `test_no_product_file_holds_an_owner_value`; Task 15, `test_the_pinned_jaws_release_holds_no_owner_value`.

## Rulings

Calls this plan makes. Those marked **To confirm** are the owner's: each gives the spec text it departs from, or the gap it fills, and what the other answer would change. The PR lists them.

1. **The freeze lets in exactly the enabling edit, and ends at the hub's first release. To confirm.** This is roadmap row 07's open item.
   - **The edit:** plan 06's H4 `platform` lines, verbatim, by the owner, in `jaws`'s `config/platform.yaml` (O1). Nothing else goes into `config/` or `datasets/`, in either repository.
   - **How it is let in:** the hub's freeze check (plan 06's `test_freeze.py`) already accepts `jaws`'s `platform` section with or without the hub's lines. So the hub's upgrade to the enabling release passes it, and any other change in that release fails it. Task 2 checks the bytes as well.
   - **The gap it fills.** Spec 6.10 says "No change goes into `config/` or `datasets/` in either repository during that window", but step 3's release falls inside the window and needs the hub's identity in `jaws`'s configuration.
   - **When it ends:** once the hub's first release has applied (O5). Task 5 deletes the freeze check, every configuration change is then a hub PR, and `jaws`'s copy is never edited again; Task 12 deletes it.
   - **The other answer:** cut the enabling release before plan 06's Task 3 copies the configuration, so no exception is needed. The hub's H4 would add only `brand`, and its plans would pass from its first PR, but plans 06 and 07 would interleave, against the roadmap's order.
2. **At takeover, `jaws` also stops planning the platform. To confirm.**
   - Spec 6.10's step 5 switches off the appliers and the sweep. This ruling also takes out `ci.yml`'s platform plans and their required checks: `Terraform plan`, `Monitoring plan`, `Data access plan`, and the bot and Databricks plans.
   - **Why:** after the freeze the hub changes the configuration, so `jaws`'s frozen copy would plan every hub change as one to undo, on every `jaws` PR. A product change is then planned where spec 6.5 puts it: in the hub's upgrade PR, with the candidate image. With ruling 3, `jaws`'s only access to AWS from the takeover on is the publishing role (spec 6.8).
   - **The other answer:** keep the plans until cleanup, with misleading comments, and with `jaws` assuming the platform's plan roles until then.
3. **At takeover, `jaws` stops pushing `jaws-cli`. To confirm.**
   - **It departs from plan 04 and shortens plan 06's D7.** Plan 04 says releases "keep pushing the configuration-baked `jaws-cli` image until cleanup". D7 has projects merge their Jaws pin bumps until each switches; they now stop at the takeover.
   - **Why:** after the takeover `jaws`'s configuration is stale, so a new `jaws-cli` would bake in a configuration nobody applies. And `jaws-cli` keeps its newest 20 release images: with no new push nothing more expires, so every image a project pins at the takeover stays until cleanup.
   - **The cost:** a project can't take a newer Jaws release until it switches, since a bump would name a `jaws-cli` tag that doesn't exist. For task and bot repositories, a bump would run with `jaws`'s frozen configuration, and from the cleanup release on it would fail for want of the platform's identity. Projects switch soon after the hub goes live anyway (spec 6.10, step 6).
   - **The other answer:** keep the release's `image` job until cleanup, rewired off the removed apply. `jaws` would assume the foundation's apply role until then, and the D7 bumps would continue, each new push expiring an older pin's image.
4. **The takeover's order: `jaws` off, then the hub on, then the hub's first release, in one sitting. To confirm.**
   - **The gap it fills.** Spec 6.10 says the same workflows in `jaws` "are switched off at the same time, so exactly one sweeper runs". Two merges can't land at once, so this order risks minutes with no sweep, and never two sweepers.
   - Between the hub's takeover PR and its first release, the hub's sweeps assume the data-access apply role and stop at `platform-image`'s resolve ('jaws-platform:current does not exist: the hub's first release tags its build current'), before any change.
   - **The other answer:** the hub first. Two sweepers and two appliers would run for a few minutes, with only the state lock to order them.
5. **What "no changes" means,** in the acceptance plans, at takeover and in the switches.
   - Every plan reads `No changes.` With D3, not even a tag changes (plan 06).
   - **Allowed:** the monitoring node's output-only `public_ip` change in hours (`Changes to Outputs:`, with `public_ip` alone), which touches no resource; and `moved:` lines after cleanup.
   - **Off-hours,** the Monitoring plan shows the node replaced, because AWS releases a stopped node's public IP. Re-run that job in hours.
   - **The plans run at the release `jaws` last applied.** A hub pinned older or newer shows that release's changes, not the migration's.
   - **A site's plans** run the hub's release against a site last deployed at its own pin (`v0.76.0` today). A difference from that gap is the release's, not the migration's. Before O5, fix it in the site, or accept it as the site's next deploy; a plan that fails is fixed in the site's `jaws.yaml`.
6. **The switches go sites first, then the bot, then the task projects, and none starts a run to prove itself. To confirm.**
   - **The gap it fills.** Spec 6.10 says "Each switch's PR plan shows no changes", but a task or bot repository has no plan. Its call runs only with a task or a release, which costs money or changes the bot. So its call is checked against the hub's caller before its PR opens (Task 7's call check), and its first real run, part of the owner's own work, is the proof.
   - **The order** is Task 7's table: `guitar-knowledge-base` (the smallest site), `cs-survival-guide` (no required Jaws check), `site`, `braveheart-lichess-bot`, `braveheart-selfplay`, `braveheart-trainer`, and `braveheart`, the most used, last.
   - **Seven, as the roadmap says,** found from GitHub. Code search finds only `braveheart`; reading every repository's workflows under the four owners found the other six. `Pi-Mathematical-Reasoning` and `Prog-Strength` call no Jaws workflow, and `braveheart-databricks` is applied by hand.
   - **The other answer:** a test run per switch, a task, a bot release or a site deploy, each spending money or changing what serves.
7. **`jaws-cli` retires through the configuration. To confirm.**
   - **In the product** (Task 11), `ecr.repository` becomes optional. With it, the foundation keeps `jaws-cli`, moved under a count; without it, there is no repository. The bot images' lifecycle settings stay in `ecr`.
   - **In the hub,** the owner removes `ecr.repository` after the last switch (Task 16b), and its plan destroys `jaws-cli`. The module refuses to destroy a repository that holds images (`force_delete = false`), so the owner empties it first (O12), once the agent's scan finds no caller left.
   - **The gap it fills.** The spec says `jaws-cli` "is retired" (6.3, 6.10 step 7), not how.
   - **The other answers:** refuse `ecr.repository` in the cleanup release, which forces the retirement into that upgrade; or forget the repository with a `removed` block, and delete it by hand.
8. **The guard after `config/` leaves: patterns in `jaws`, exact values in the hub. To confirm.**
   - **Why two:** today's guard builds its values from `config/`, so it can't outlive it.
     - `jaws` (Task 13) checks every tracked file by pattern for account IDs, emails and `jwall`, which covers the owner's login. The other owner names, `LICENSE`'s holder and ruling 9's example owners, stay: the owner's call (To confirm).
     - The hub (Task 15) checks the release it pins with its own configuration's exact values: the GitHub and Databricks IDs, the zone and the owner's login, which no pattern can tell apart.
   - **Exempt:** `release-infra/` (spec 6.8); `CHANGELOG.md`, which records what releases said (the git history keeps the old tree anyway); and the lock files. `jwall` may stay in `docs/superpowers/`, whose records of the split name the hub, and in `.github/CODEOWNERS`, the maintainer's login.
   - **What the public image carries** (plan 04, Review Focus 5) is built from tracked files, `README.md` (in the package metadata) and `pyproject.toml` included, so the scan covers it.
   - **The other answer:** exact values only, at the hub's upgrade, after a release has already made a leak public.
9. **The docs split, and the examples' names. To confirm.**
   - **The product's docs** describe Jaws for any platform, with the fixture's values in examples: `example.com`, `222222222222`, `Example-Hub/platform`, `example-owner`.
   - **The example projects keep their names** (`braveheart`, `guitar-knowledge-base`, `Braveheart-Chess` and so on), as plan 01 left them: they are public repositories, and renaming them would touch most tests for nothing. Plan 01: "Plan 07 decides whether the examples are renamed".
   - **The README's owner-only sections,** `Accounts`, `History`, `Bootstrap` and `Owner hand-off`, move to the hub's README verbatim, by counted copy, and `jaws` gets product versions of `Accounts` and `Owner hand-off`. The moved sections hold the account ID, so the agent never displays them; the owner rewords them in the hub later.
   - **`docs/consumer-note.md` goes:** the hub's "For project teams" replaced it (spec 6.1). **The design records stay,** with `<account-id>` in place of the account IDs the monitoring records spell.
   - **The other answer:** rewrite the moved sections now, or move every doc that mentions the platform to the hub.
10. **The trust on `Jaws-Platform/jaws` goes after the last switch,** as spec 6.10 step 7 places it, though nothing assumes it from the takeover on. Until then, reverting the takeover lets `jaws` apply again.
11. **`release-infra/`'s checks need no configuration. To confirm.**
    - Plan 04 said its checks against `config/` "become literals". Literals in a test would spell the account outside the folder, against spec 6.8: "No account ID appears in code outside this folder".
    - So the checks hold the folder to itself (its state bucket is `jaws-terraform-state-<its account>`) and, in Actions, to GitHub's own IDs for `Jaws-Platform/jaws`.
    - **The other answer:** the literals, with the guard exempting the test that holds them.

## Costs, for the owner's go-ahead (G0)

The owner's rule is "don't spend any money in the cloud". Plan 06's D5 costs start in this plan, so none of them is approved yet.
- Without C1 and C2 the hub can't release, so if either isn't approved, plan 07 stops at G0.
- The estimates use plan 04's measured image size (about 283 MiB) and plan 05's cache (each repository pulls a build once).

| | What | Starts | Estimate |
|---|---|---|---|
| C1 | The hub image's storage in private ECR | the hub's first release (O5) | At most ten builds, about 2.8 GB: at most about $0.28 a month at $0.10 a GB-month (plan 05 ruling 6). Less where builds share their Jaws base |
| C2 | Pulls of the hub image to GitHub's runners, billed as data transfer out | O5 | Free within the account's 100 GB a month of data transfer out, then $0.09 a GB. See below |
| C3 | The AWS requests of the hub's PR plans: state reads, lock writes, SSM and KMS | the enabling release (O2) | A few cents a month at most. Until O5 they come on top of `jaws`'s own; from O5 they replace them |

**C2's pulls:**
- **New:** the hub's release and sweep, about 283 MiB per build; and each switched task or bot repository, which pulls no image today, about 283 MiB per build it runs.
- **Per pull request too:** a repository's PR runs pull a build once per PR branch, until a run on `main` has cached it (plan 05). braveheart's SPRT runs and every site's plan and preview run on PRs: about 283 MiB per new PR branch per build.
- **Replaced:** the sites' pulls replace their `jaws-cli` pulls, which are uncached today.
- **At one hub release a day:** up to about 9 GB for the hub and 34 GB for the four repositories, about 43 GB a month, plus 283 MiB per such PR branch.
- **At three a day:** about 130 GB, plus 283 MiB per such PR branch, which is about $2.70 a month past the free 100 GB if nothing else used it.
- The owner checks last month's data transfer out in the Billing console before approving C2.

**Free, moved or saved:**
- **Free:** the enabling release's empty repository and IAM changes; basic scanning on push (free while the registry's scanning is basic: the owner checks the scanning setting at G0); GitHub for public repositories (Actions, caches, artifacts, rulesets, environments and Apps); and the hub's anonymous pulls of the public base (plan 06).
- **Moved, not added:** the sweep's and the applies' requests.
- **No new run:** no switch starts a task, a bot release or a production deploy (ruling 6). A site's switch PR runs its usual preview deploy.
- **Saved:** `jaws-cli`'s storage, about $0.10 a month, at O12; and `jaws`'s PR plans' requests, at O5.

## The run order

| # | Who | Step | The next starts when |
|---|---|---|---|
| 1 | owner | O0 | plans 05 and 06 are done |
| 2 | agent | Task 1 | its PR has merged, or nothing changed |
| 3 | owner | G0 | every cost is approved |
| 4 | agent, owner | Task 2, O1 | the PR's plans read as Task 2 expects |
| 5 | owner | O2 | the enabling release has applied |
| 6 | owner, agent | O3 | every plan reads `No changes.` |
| 7 | agent, owner | Task 3, O4 | the hub requires its three plans |
| 8 | agent | Tasks 4 and 5 | both PRs are green |
| 9 | owner | O5 | the hub's first release has applied, and `live` exists |
| 10 | agent, owner | Task 6, O6 | released; it may run alongside the switches |
| 11 | owner | O7 | the comments App is on the three sites |
| 12 | agent, owner | Task 7, O8, seven times | the seventh switch has merged |
| 13 | agent, owner | Task 8, O9 | merged; it may start after the first switch |
| 14 | agent | Tasks 9–14, then Task 16b's Step 1 scan | the cleanup PR is green, and the scan finds no caller |
| 15 | owner | O10 | the hub runs the cleanup release |
| 16 | agent | Task 15 | merged |
| 17 | agent, owner | Task 16a, O11 | released |
| 18 | agent, owner | Task 16b, O12 | released: plan 07 is done |

## Owner steps

The agent does none of these. Each says what to check before and after.

- **O0. Before plan 07.**
  - Plans 05 and 06 are done: plan 05 merged and released, and plan 06's Tasks 1–7 with its hand-offs H0–H5, H7 and H8. H6 can wait for O7.
  - The hub's `main` is green, and `platform / Platform check` is required.
  - The hub pins the release `jaws` last applied.
  - Give the agent JWall Engineering Deployments' client ID, which plan 06's H2 kept for this plan's callers. It isn't secret.
- **G0. The go-ahead on costs.**
  - Read "Costs", and check last month's data transfer out in the Billing console.
  - Approve C1, C2 and C3 in writing, on this plan's PR or to the controller. Nothing from Task 2 on runs before that.
- **O1. The enabling edit** (Task 2, Step 2). On `hub-split/07-enabling`:
  - add plan 06's H4 `platform` lines to `config/platform.yaml`, verbatim and with the same IDs, after the first entry;
  - commit it as `feat(config): trust the hub and create its image repository`, and push.

  Nothing else in `config/` or `datasets/` changes (ruling 1).
- **O2. The enabling release.**
  - **Before:** Task 2's reading of the plans is as it expects; the Release Please PR holds the enabling PR and nothing whose plan showed a change; it is 08:00–24:00 MT.
  - **Do:** merge the enabling PR, then the Release Please PR.
  - **After:** the release's `Terraform apply` and `Monitoring apply` succeeded, and its public image summary names the new tag. Within the hour, the hub's upgrade PR to that tag opens. From now on the hub's PRs plan with real roles (C3).
- **O3. Acceptance,** on the hub's upgrade PR to the enabling release, or a by-hand bump to it (plan 06, ruling 1).
  - **Check:** every check is green, `tests` included. Its freeze check accepts the enabling edit as the one exception.
  - **The agent** posts each plan's filter output as a PR comment: `Terraform plan`, `Monitoring plan`, `Data access plan`, and every `Site plan`, `Bot plan` and `Databricks plan`.
  - **Accept** when every one reads `No changes.`, with ruling 5's exceptions only. Then merge the upgrade PR.
  - **If a plan shows a change, stop.** Nothing merges in the hub until the change is explained. A product fix is a `jaws` release and a new upgrade PR, and the acceptance starts again.
- **O4. Require the plans.** Merge Task 3's PR, then run the hub's `scripts/apply-repo-settings.sh`. **After:** `gh api repos/JWall-Engineering/platform/rulesets/<main's id>` lists the four `platform /` checks.
- **O5. The takeover,** in one sitting between 08:00 and 24:00 MT, with an hour to spare.
  - **Before:**
    - Tasks 4 and 5's PRs are green;
    - Task 4's reported checks pass, and the four it removes show as expected;
    - the hub pins the release `jaws` last applied, and its last PR's plans all read `No changes.`;
    - no `jaws` release PR with changes is open;
    - G0 covers C1 and C2, which start now.
  - **Do, in this order:**
    0. mark both PRs ready;
    1. run `jaws`'s `scripts/apply-repo-settings.sh` from Task 4's branch, so the four platform plans stop being required;
    2. merge Task 4's PR: `jaws`'s sweep, applies, platform plans and `jaws-cli` pushes stop. It is a `ci` commit, so it cuts no release;
    3. check that no `Data access apply` run is in progress in `jaws`, then merge Task 5's PR: the hub gains its appliers, and its `release.yml` opens a release PR;
    4. merge that release PR at once. Until it has run, the hub's sweeps stop at `current` (ruling 4).
  - **After:**
    - the release's jobs pass in order: the build `sha-<commit>`, then `Terraform apply` (`No changes.` through the filter), then the move of `current`, then the move of `live`. `Monitoring apply` runs beside the moves (plan 05, ruling 7) and also passes;
    - `live` exists, at the release commit;
    - the next sweep reads `Sweep: no-changes`.
  - **From now on:**
    - no project merges a Jaws pin bump until it switches (ruling 3);
    - every configuration change is a hub PR;
    - `jaws`'s `config/` is a dead copy, left alone until cleanup.
  - **If the release fails** before `current` moves, fix forward and re-run the failed job.
  - **To go back,** revert Task 4's PR in `jaws`, which brings back its appliers and sweep, and Task 5's in the hub, then run `jaws`'s `scripts/apply-repo-settings.sh` from `main`. The trust stays until Task 16, so `jaws` can apply again.
- **O6. D3** (Task 6). Commit `context.organization: JWall-Engineering` to the hub's `config/tool.yaml` on Task 6's branch. Merge once the filter reading is tags-only, then the release PR, between 08:00 and 24:00 MT. **After:** the release's applies change as many resources as the plan said.
- **O7. Before the switches:** plan 06's H6. Install JWall Engineering Comments on the three site repositories, and set `COMMENTS_APP_PRIVATE_KEY` on each.
- **O8. Each switch** (Task 7), one at a time.
  - **A site, before merging:** its `plan / plan / jwall plan` reads `No changes.` In its `main` ruleset (Settings, Rules), replace the required checks `plan / jaws plan` and `preview / jaws preview deploy` with the names its PR reports. `cs-survival-guide` has no ruleset: its classic branch protection requires `build` and `pr-title`, neither of them a Jaws check, so it doesn't change.
  - **A site, after merging:** delete its variables `AWS_PLAN_ROLE_ARN`, `AWS_PREVIEW_ROLE_ARN`, `AWS_APPLY_ROLE_ARN` and `JAWS_APP_CLIENT_ID`, and its secret `JAWS_APP_PRIVATE_KEY`. Close any open Dependabot PR that bumps a Jaws pin. Its next release deploys through the hub.
  - **A task or bot repository:** merge. Its next task or release, run as part of your own work, is its first through the hub. If that fails at the call, revert the switch PR.
- **O9. The conventions:** merge Task 8's three PRs.
- **O10. The cleanup in `jaws`.**
  - **Before:** the seven switches have merged, and the agent's scan (the command in Task 16b, Step 1, run after the seventh switch) finds no caller of `Jaws-Platform/jaws`'s workflows in a project. Merge the hub's README PR (Task 12) first.
  - **Do:** run `jaws`'s `scripts/apply-repo-settings.sh` from the cleanup branch; merge Task 14's PR; then merge its release PR between 08:00 and 24:00 MT. It applies nothing, but it is the hub's next upgrade.
  - **After:** the release publishes the public image. The hub's upgrade PR's plans read `No changes.`, apart from `moved:` lines for `module.sites_image` (Task 11). Merge it. Its `chore(deps)` commit opens no release PR on its own, since Release Please hides `chore`, so the cleanup release goes live with Task 16a's release.
- **O11. The old trust** (Task 16a). Commit the hub's `config/platform.yaml` without its first entry, `Jaws-Platform/jaws`. Merge once the filter reading is as Task 16a expects, then the release PR, between 08:00 and 24:00 MT.
- **O12. `jaws-cli`** (Task 16b).
  - **Before:** the agent's scan finds no caller. Then empty the repository with the production account's admin profile:

    ```sh
    aws sso login --profile jaws-prod && export AWS_PROFILE=jaws-prod
    aws ecr list-images --region us-east-1 --repository-name jaws-cli --query 'imageIds[*]' --output json > jaws-cli-images.json
    aws ecr batch-delete-image --region us-east-1 --repository-name jaws-cli --image-ids file://jaws-cli-images.json --query 'length(failures)'
    ```

    Expected: `0`. Otherwise run both again until `list-images` returns `[]`.
  - **Do:** commit the hub's `config/tool.yaml` without `ecr.repository` on Task 16b's branch. Merge once the filter reading is as Task 16b expects, then the release PR, between 08:00 and 24:00 MT.
  - **After:** `jaws-cli` is gone. Optionally, delete `jaws`'s `prod` environment, its `JAWS_APP_CLIENT_ID` variable and its `JAWS_APP_PRIVATE_KEY` secret: nothing has used them since the takeover.

---

### Task 1: Re-check this plan against plans 05 and 06 as merged

**Repository:** `jaws`, on `hub-split/07-migration` (draft PR #333), which the owner merges before Task 2. Its `docs` commit rides in the next `jaws` release, which applies the platform, so that release PR is merged between 08:00 and 24:00 MT. **When:** O0 is done.

**Files:**
- Modify, only where a name differs: `docs/superpowers/plans/2026-11-26-hub-split-07-migration.md`

**Interfaces:**
- Consumes, from plan 05 in `jaws`: the `platform-*.yml` workflows' file names, inputs and secrets; the project-facing workflows' platform inputs and role overrides; `jaws platform check`, `IDENTITY_WORKFLOWS`, `CHECK_PREFIX_WORKFLOWS` and `FROM_PATTERN`; the job names `Platform check`, `Terraform plan`, `Monitoring plan` and `Data access plan`, and the plan jobs' artifact names; plan 05's release and rollback job names, the sweep's summary `Sweep: no-changes`, `platform-image`'s resolve message, `JAWS_TOOL_CONFIG`, the `platform-role` step ids, the sections of `docs/platform-workflows.md`, and the tests of today's mode that Task 10 deletes; and the hub image's tags, `sha-<commit>` and `current`.
- Consumes, from plan 06 in the hub:
  - `tests/conftest.py`'s `PLATFORM_CONFIG_DIR`, `JAWS_SOURCE`, `WORKFLOWS`, `workflow`, `jaws_workflow`, `pinned_release`, `platform_settings`, `owner_values`, `HUB`, `BRAND`, `COMMENTS_APP_CLIENT_ID` and `UPGRADES_APP_CLIENT_ID`;
  - `tests/platform/test_callers.py`'s constants and tests, `REQUIRED_PLATFORM_CHECKS`, `REQUIRED_CHECKS`, `test_freeze.py` and `test_hub_identity.py`'s four tests;
  - the callers' job ids, the account render and the mask.
- Produces: this plan, true to the merged code.

- [ ] **Step 0: Branch:** `git fetch origin && git switch hub-split/07-migration`

- [ ] **Step 1: Look up each name** on both repositories' `main` with `git grep -c -- '<name>' -- .github src tests scripts docs`, which prints counts per file, never in `config/`, `datasets/` or `owner/`. To read a matching line, pipe `git grep -n` through the mask.
Expected: each name has a nonzero count where this plan says it is.

- [ ] **Step 2: Amend the plan where a name differs,** and nowhere else. Open a PR listing the names that changed under Changes. The owner merges it before Task 2. If nothing changed, open no PR and tell the owner.

```bash
git add docs/superpowers/plans/2026-11-26-hub-split-07-migration.md
git commit -m "docs(repo): align plan 07 with plans 05 and 06 as merged"
```

---

### Task 2: The enabling pull request

**Repository:** `jaws`, branch `hub-split/07-enabling`. **When:** G0 is given.

> **Reviews:** the owner's commit is sealed.

**Files:**
- Modify (the owner, O1): `config/platform.yaml`

**Interfaces:**
- Produces, in `jaws`'s configuration (plan 03's rulings 1–2, plan 06's H4):
  - `platform.repositories[1]`: `JWall-Engineering/platform`, with its two IDs;
  - `platform.hub`: `{repository: JWall-Engineering/platform, image: jaws-platform}`.

  The first entry, `Jaws-Platform/jaws`, stays first, so no `Repository` tag moves.
- Produces, at its release:
  - every role of spec 6.6 also trusts the hub, and each site plan role trusts the hub's pull requests;
  - the repository `jaws-platform`, with its lifecycle (plan 05, ruling 6);
  - `ecr/pull` on it for every CI role, and `ecr/push-2` for the infra apply role (plan 03, Task 8).

- [ ] **Step 1: Push the branch**

```bash
git switch -c hub-split/07-enabling origin/main
git push -u origin hub-split/07-enabling
```

- [ ] **Step 2: Wait for the owner's commit (O1),** then run `git pull --ff-only`.

- [ ] **Step 3: Check the edit, printing no value**

```bash
git diff --shortstat origin/main...HEAD
hub=~/Projects/JWall-Engineering/platform
git -C "$hub" fetch --quiet origin
test "$(git rev-parse HEAD:config/platform.yaml)" = "$(git -C "$hub" rev-parse origin/main:config/platform.yaml)" \
  && echo "platform.yaml: the hub's, byte for byte"
```

Expected: `1 file changed, 7 insertions(+)`, then the byte-for-byte line. If the hashes differ, the hub's freeze check in O3 still decides. Tell the owner.

- [ ] **Step 4: Open the PR**
  - Title: `feat(config): trust the hub and create its image repository`.
  - Body: the template.
    - Why: spec 6.10 step 3, ruling 1's exception, and the costs it starts (C3).
    - Verification: Step 3's output and Step 5's reading.

```bash
gh pr create --title "feat(config): trust the hub and create its image repository" --body-file <filled template>
```

- [ ] **Step 5: Read the plans with the filter,** once CI has run.
Expected:
  - **`Terraform plan`:**
    - `0 to destroy`, and no `must be replaced`;
    - created: the hub image's repository and lifecycle policy (`module.hub_image[0]`), and IAM policies and attachments keyed `ecr/pull`, `ecr/pull-2` or `ecr/push-2`;
    - updated in place: only `aws_iam_role`s, and `plan_attributes` lists only `assume_role_policy`.
  - **`Monitoring plan`, `Data access plan`, and every `Bot plan` and `Databricks plan`:** `No changes.`, with ruling 5's exceptions.

Post the filter's output on the PR as a comment, then hand it to the owner (O2).

---

### Task 3: The hub requires its plans

**Repository:** the hub, branch `require-plans`. **When:** O3 has accepted the plans.

**Files:**
- Modify: `scripts/apply-repo-settings.sh` (`REQUIRED_CHECKS`), `tests/platform/test_ci.py` (`REQUIRED_PLATFORM_CHECKS`)
- Modify: `.github/pull_request_template.md` and `README.md` ("Upgrading Jaws"): the line that two plans are expected red until plan 07's enabling release goes

**Interfaces:**
- Produces `REQUIRED_PLATFORM_CHECKS = ["platform / Platform check", "platform / Terraform plan", "platform / Monitoring plan", "platform / Data access plan"]` (plan 05, "For plans 06 and 07"). `REQUIRED_CHECKS` gains the same three plans.

- [ ] **Step 0: Branch:** `git fetch origin && git switch -c require-plans origin/main`

- [ ] **Step 1: Write the failing test.** In `tests/platform/test_ci.py`, set `REQUIRED_PLATFORM_CHECKS` to the four. `test_every_ci_job_is_a_required_check` then fails, since the script doesn't require the three plans.

`Monitoring plan` skips, with a notice, when its credentials fail (plan 05), and a skip satisfies a required check. O3 and every later reading must therefore find its plan's text, `No changes.`, and not the notice.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --project .jaws-tool --locked pytest -q -o addopts="" tests/platform/test_ci.py`
Expected: FAIL in `test_every_ci_job_is_a_required_check`: the script doesn't require the three plans.

- [ ] **Step 3: Add the three plans to `REQUIRED_CHECKS`,** and drop the expected-red line from the template and the README.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run --project .jaws-tool --locked pytest -q -o addopts=""`
Expected: PASS, with the `N passed` line.

- [ ] **Step 5: Commit and open the PR**

```bash
git add scripts/apply-repo-settings.sh tests/platform/test_ci.py .github/pull_request_template.md README.md
git commit -m "ci(repo): require the platform's plans now that its roles trust the hub"
git push -u origin require-plans
gh pr create --title "ci(repo): require the platform's plans now that its roles trust the hub" --body-file <filled template>
```

Expected CI: the four `platform /` checks pass, and their plans read `No changes.`

---

### Task 4: `jaws` stops applying, sweeping and planning the platform

**Repository:** `jaws`, branch `hub-split/07-takeover`. **When:** O4 is done, and the owner has confirmed ruling 3. Otherwise the release keeps its `account` and `image` jobs, with `image` rewired off the removed `apply` (ruling 3's other answer); `test_the_release_publishes_only_the_public_image` lists them; and `test_they_reach_aws_only_to_publish` allows the infra apply role in `image`. The owner merges it in O5, not before.

**Files:**
- Delete:
  - `.github/workflows/data-access.yml`, `.github/workflows/bot-apply.yml`, `.github/workflows/databricks-apply.yml`;
  - `scripts/projects.sh`, `scripts/databricks-credentials.sh`, `scripts/data-access-sweep.sh`, the scripts only those and the removed jobs use (plan 05, "For plans 06 and 07");
  - `tests/test_data_access_sweep.py`.
- Modify:
  - `.github/workflows/ci.yml`: the jobs `account`, `terraform-plan`, `monitoring-plan`, `bot-projects`, `bot-plan`, `databricks-projects` and `databricks-plan` go, and so does the `data-access-stack` job's step `shellcheck the sweep`. That job's comment stops saying `data-access.yml` plans the stack;
  - `.github/workflows/release-please.yml`: the jobs `account`, `apply`, `monitoring-apply` and `image` go. Its header comment and the dispatch input's description say it publishes the public image;
  - `scripts/apply-repo-settings.sh`: `Terraform plan`, `Monitoring plan`, `Data access plan` and `Databricks projects` go.
- Modify the tests of what went, deleting each test of a deleted job or script and keeping the rest:
  - `tests/test_foundation_workflows.py`, `tests/test_monitoring_workflows.py`, `tests/test_databricks_workflows.py`, `tests/test_bots_registry.py`, `tests/test_access_files.py`;
  - `tests/test_workflow_roles.py`, `tests/test_tool_checkout.py`, `tests/test_repository_name.py`;
  - `tests/test_cli_image.py`: the two tests of the `jaws-cli` job;
  - `tests/test_public_image.py`: `test_the_public_job_runs_only_when_the_check_says_so` keeps its assertions, with the `account` job's `if` and the `image` job's `TAG` written out as the expressions they hold today;
  - `tests/test_config_projects.py` (plan 05): the comparison with `scripts/projects.sh` becomes one with the fixture's expected JSON, written out;
  - `tests/test_databricks_workflows.py` keeps `needs_yq` (or it moves to `tests/workflow_steps.py`), which `tests/test_public_image.py` and `tests/test_config_projects.py` import;
  - `tests/conftest.py`: `fixture_root`, once nothing uses it. If the privacy hook refuses an edit to `tests/conftest.py`, hand that edit to the owner.
- Create: `tests/test_jaws_workflows.py`
- Modify: `AGENTS.md` (the apply rule), `CONTRIBUTING.md` (the required checks table and the release paragraph), `README.md` ("CI/CD", "CI roles for this repository")
- Modify: `docs/databricks.md`, `docs/lichess-bot.md`, `docs/research-projects.md`, `docs/remote-tasks.md` and `docs/datasets.md`, and README's rows for the deleted scripts: Bot apply, Databricks apply, the sweep and the plans are a hub's (`docs/platform-workflows.md`), not `jaws`'s

**Interfaces:**
- Produces: `jaws`'s own workflows are `ci.yml` and `release-please.yml`.
  - Neither runs on a schedule.
  - The one role either assumes is `vars.JAWS_PUBLISH_ROLE_ARN`'s, in `public-image`. Spec 6.8: "After the split, this role is `jaws`'s only access to AWS".
- Produces: the release's jobs are `release-please`, `public-image-check` and `public-image` (plan 04, ruling 13).
- The project-facing and `platform-*` workflows don't change. They are a hub's and its projects'.

- [ ] **Step 0: Branch:** `git fetch origin && git switch -c hub-split/07-takeover origin/main`

- [ ] **Step 1: Write the failing tests** in `tests/test_jaws_workflows.py`

```python
"""jaws's own workflows after the takeover: its CI and its release. A hub plans, applies
and sweeps its platform; jaws reaches AWS only to publish its image (spec 6.8)."""

from __future__ import annotations

from typing import Any

import yaml

from tests.workflow_steps import WORKFLOWS, required_checks

OWN = {"ci.yml", "release-please.yml"}
PLATFORM_CHECKS = {"Terraform plan", "Monitoring plan", "Data access plan", "Databricks projects"}


def _parsed(name: str) -> dict[Any, Any]:
    parsed: dict[Any, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
    return parsed


def _triggers(name: str) -> set[str]:
    parsed = _parsed(name)
    on = parsed.get("on", parsed.get(True))
    return {on} if isinstance(on, str) else set(on)


def test_jaws_s_own_workflows_are_its_ci_and_its_release() -> None:
    own = {p.name for p in WORKFLOWS.glob("*.yml") if _triggers(p.name) - {"workflow_call"}}
    assert own == OWN
    assert not any("schedule" in _triggers(name) for name in OWN)


def test_they_reach_aws_only_to_publish() -> None:
    for name in OWN:
        for job_name, job in _parsed(name)["jobs"].items():
            roles = [
                step["with"]["role-to-assume"]
                for step in job.get("steps", [])
                if str(step.get("uses", "")).startswith("aws-actions/configure-aws-credentials")
            ]
            expected = ["${{ vars.JAWS_PUBLISH_ROLE_ARN }}"] if job_name == "public-image" else []
            assert roles == expected, f"{name}: {job_name}"


def test_every_required_check_is_a_ci_job() -> None:
    names = {job["name"] for job in _parsed("ci.yml")["jobs"].values()}
    assert required_checks() <= names
    assert not required_checks() & PLATFORM_CHECKS
```

Also `test_the_release_publishes_only_the_public_image`: `set(_parsed("release-please.yml")["jobs"]) == {"release-please", "public-image-check", "public-image"}`. Read workflows with one shared reader in `tests/workflow_steps.py`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest -q -o addopts="" tests/test_jaws_workflows.py`
Expected: FAIL. `data-access.yml` runs on a schedule, the release still applies, and the four platform checks are required.

- [ ] **Step 3: Delete and modify what the Files list says.**

- [ ] **Step 4: Run everything and watch it pass**

Run: `uv run ruff format --check && uv run ruff check && uv run mypy && uv run pytest -q -o addopts="" && shellcheck scripts/*.sh && npm test`
Expected: PASS.

- [ ] **Step 5: Docs**
  - `AGENTS.md`: "Applies happen only through the Release Please `apply` job" becomes "`jaws` applies nothing to a platform: a hub's release does ([docs/platform-workflows.md](docs/platform-workflows.md))".
  - `CONTRIBUTING.md`: the `Terraform plan` row goes from the checks table, and so does Workflow step 4. Releases says that merging the release PR tags the version and publishes the public image: items 2 and 3, and "the deliberate act that changes AWS", go.
  - `README.md`: "CI/CD" says the same. "CI roles for this repository" says that `jaws` no longer assumes them, and that their trust on `Jaws-Platform/jaws` goes at cleanup.

- [ ] **Step 6: Commit and open the PR as a draft**

```bash
git add -A .github scripts tests docs AGENTS.md CONTRIBUTING.md README.md
git commit -m "ci(workflows): hand the platform's applies, sweep and plans to the hub"
git push -u origin hub-split/07-takeover
gh pr create --draft --title "ci(workflows): hand the platform's applies, sweep and plans to the hub" --body-file <filled template>
```

The body says what O5 does with it, and that a `ci` commit cuts no release.

---

### Task 5: The hub applies

**Repository:** the hub, branch `takeover`. **When:** O4 is done. The owner merges it in O5.

> **Reviews:** the callers' commit is sealed, since five callers hold the rendered account.

**Files:**
- Create: `.github/workflows/release.yml`, `rollback.yml`, `bot-apply.yml`, `databricks-apply.yml`, `sweep.yml`
- Delete:
  - `.github/workflows/release-please.yml`. `release.yml` replaces it, with the same config and manifest (plan 06, ruling 2);
  - `tests/platform/test_freeze.py`. The freeze ends at this PR's first release (ruling 1).
- Modify:
  - `tests/conftest.py`: `DEPLOYMENTS_APP_CLIENT_ID`, O0's value;
  - `tests/platform/test_callers.py`;
  - `README.md`: "Releases and rollbacks" and "By-hand applies and the sweep" are new, and "The configuration" says the freeze is over;
  - `AGENTS.md`, and `CONTRIBUTING.md`: merging the release PR applies the platform, between 08:00 and 24:00 MT.

**Interfaces:**
- Consumes plan 05's `platform-release.yml`, `platform-rollback.yml`, `platform-bot-apply.yml`, `platform-databricks-apply.yml` and `platform-sweep.yml` at `<tag>`, and plan 06's render, mask and `PLATFORM_INPUTS`.
- Produces the five callers. Each has:
  - top-level `permissions: {}`, and one job that calls its Jaws workflow at `<tag>` with `permissions: {contents: read, id-token: write}`;
  - the identity as literals: `platform-image: jaws-platform`, `account-id: "<rendered>"`, `name-root: jaws`.

| Caller | `on` | Job | Calls | Also passes | Secrets |
|---|---|---|---|---|---|
| `release.yml` | `push` to `main` | `release` | `platform-release.yml` | `live-app-client-id` | `RELEASE_BOT_CLIENT_ID`, `RELEASE_BOT_PRIVATE_KEY`, and `live-app-private-key: ${{ secrets.DEPLOYMENTS_APP_PRIVATE_KEY }}` |
| `rollback.yml` | `workflow_dispatch` | `rollback` | `platform-rollback.yml` | `live-app-client-id`, `commit` | `live-app-private-key`, the same |
| `bot-apply.yml` | `workflow_dispatch` | `apply` | `platform-bot-apply.yml` | `project`, `destroy`, `consumer-ref` | none |
| `databricks-apply.yml` | `workflow_dispatch` | `apply` | `platform-databricks-apply.yml` | `project`, `action` | none |
| `sweep.yml` | `schedule` (`*/15 * * * *`) and `workflow_dispatch` | `sweep` | `platform-sweep.yml` | nothing | none |

- A dispatch caller offers every input of its Jaws workflow but the platform's own, with Jaws's `type`, `required` and `default`, and passes each as `${{ inputs.<name> }}`.
- `live-app-client-id` is `DEPLOYMENTS_APP_CLIENT_ID`, as a literal (plan 06, D6).
- No caller holds the concurrency group `platform-release` (plan 05).

- [ ] **Step 0: Branch:** `git fetch origin && git switch -c takeover origin/main`

- [ ] **Step 1: Write the failing tests** in `tests/platform/test_callers.py`. Use `APPLYING = ("release", "rollback", "bot-apply", "databricks-apply", "sweep")`, `BY_HAND = ("rollback", "bot-apply", "databricks-apply")` and `APPLYING_INPUTS = PLATFORM_INPUTS | {"live-app-client-id"}`.
  - `test_each_applying_caller_calls_its_jaws_workflow`:
    - each caller's one job `uses` `Jaws-Platform/jaws/.github/workflows/platform-<name>.yml@<tag>`, with `<tag>` from `pinned_release()`;
    - every key of its `with` is an input of that workflow, and every required input is given.
  - `test_each_by_hand_caller_offers_what_its_jaws_workflow_takes`, over `BY_HAND`:
    - its `on` holds only `workflow_dispatch`;
    - its inputs are the Jaws workflow's inputs without `APPLYING_INPUTS`, each with the same `FIELDS` (`type`, `required`, `default`);
    - its `with`, without `APPLYING_INPUTS`, is `{key: "${{ inputs.<key> }}"}`.
    - Put the comparison in one helper that both tests call.
  - `test_the_release_runs_on_main_and_the_sweep_every_fifteen_minutes`:
    - `release.yml`'s `on` is `{"push": {"branches": ["main"]}}`;
    - `sweep.yml`'s `on` has exactly `schedule: [{"cron": "*/15 * * * *"}]` and `workflow_dispatch`.
  - `test_live_moves_with_the_deployments_app_only`, for `release.yml` and `rollback.yml`:
    - `with["live-app-client-id"] == DEPLOYMENTS_APP_CLIENT_ID`;
    - `secrets["live-app-private-key"] == "${{ secrets.DEPLOYMENTS_APP_PRIVATE_KEY }}"`;
    - the release's secrets are exactly its three, and the rollback's exactly `live-app-private-key`.
  - **Extend** `test_each_caller_grants_exactly_what_its_jaws_jobs_ask` to the five.
  - **Extend** `test_the_platform_s_apps_are_spelled_once`: every `live-app-client-id` is `DEPLOYMENTS_APP_CLIENT_ID`, which differs from the other two client IDs and matches `^Iv[0-9A-Za-z.]+$`.
  - `test_every_identity_literal_is_the_configuration_s` already covers the five, since `IDENTITY_WORKFLOWS` names their Jaws workflows.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run --project .jaws-tool --locked pytest -q -o addopts="" tests/platform/test_callers.py`
Expected: FAIL. There are no applying callers.

- [ ] **Step 3: Write the callers,** each with `account-id: "__ACCOUNT_ID__"`, and render the account as plan 06's Task 5, Step 3 does. Delete `release-please.yml` and `test_freeze.py`.
Expected:
  - `0` placeholders in every file;
  - `1` rendered account in each of the five new callers;
  - the same counts of twelve-digit lines, so the mask hides every account.

- [ ] **Step 4: Run the tests and the check, and watch them pass**

```bash
uv run --project .jaws-tool --locked pytest -q -o addopts=""
docker build -t platform:local .
docker run --rm --network none -v "$PWD:/hub:ro" -e GITHUB_REPOSITORY=JWall-Engineering/platform \
  platform:local platform check --root /hub >/dev/null 2>&1; echo "platform check: exit $?"
```

Expected: PASS, then `platform check: exit 0`.

- [ ] **Step 5: Docs:** `README.md`, `AGENTS.md` and `CONTRIBUTING.md`, per the Files.

- [ ] **Step 6: Commit and open the PR as a draft.** The callers' commit is sealed, and kept apart.

```bash
git add .github/workflows/release.yml .github/workflows/rollback.yml .github/workflows/bot-apply.yml \
  .github/workflows/databricks-apply.yml .github/workflows/sweep.yml .github/workflows/release-please.yml
git commit -m "feat(workflows): release, roll back, apply by hand and sweep the platform from the hub"
git add tests && git commit -m "test(workflows): check the hub's applying callers, and drop the freeze check"
git add README.md AGENTS.md CONTRIBUTING.md
git commit -m "docs(repo): describe the hub's releases, rollbacks, by-hand applies and sweep"
git push -u origin takeover
gh pr create --draft --title "feat(workflows): apply the platform from the hub" --body-file <filled template>
```

Expected CI: every check passes, and the plans read `No changes.`

---

### Task 6: The platform's own `Organization` tag (D3)

**Repository:** the hub, branch `organization`. **When:** O5's first release has applied.

> **Reviews:** the owner's commit is sealed.

**Files:**
- Modify (the owner, O6): `config/tool.yaml`, `context.organization`
- Modify: `tests/platform/test_hub_identity.py`

**Interfaces:**
- Produces: the foundation's and monitoring's resources carry `Organization = JWall-Engineering`. Projects keep deriving theirs from their GitHub owner (spec 6.7).

- [ ] **Step 0: Branch:** `git fetch origin && git switch -c organization origin/main`

- [ ] **Step 1: Write the failing test.** `test_the_platform_keeps_its_names` becomes `test_the_platform_keeps_its_names_and_takes_its_organization`, which asserts `context.organization == "JWall-Engineering"`, with the other three assertions unchanged.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run --project .jaws-tool --locked pytest -q -o addopts="" tests/platform/test_hub_identity.py`
Expected: FAIL. The organization is still `Jaws-Platform`.

- [ ] **Step 3: Push the test, and wait for the owner's edit (O6)**

```bash
git add tests/platform/test_hub_identity.py
git commit -m "test(config): expect jwall engineering as the platform's own organization tag"
git push -u origin organization
```

Then `git pull --ff-only`, and run Step 2's command again. Expected: PASS.

- [ ] **Step 4: Open the PR, and read its plans with the filter**

```bash
gh pr create --title "feat(config): tag the platform's own stacks with jwall engineering" --body-file <filled template>
```

Expected:
- `Terraform plan` and `Monitoring plan`: `0 to add`, `0 to destroy`, only `updated in-place`, and `plan_attributes` lists only `tags` and `tags_all`, with the node's `public_ip` output in hours;
- every other plan reads `No changes.`

The PR comment truncates at 60,000 bytes; the filter reads the whole log.

---

### Task 7: Switch a project to the hub

**Repository:** each of the seven, branch `switch-to-hub`, in the table's order and one at a time. **When:** O5 is done, and for a site O7 too. Each starts once the owner has merged the one before (O8).

| # | Repository | Files | Calls | Leaves out of `with:` | Commit and PR title |
|---|---|---|---|---|---|
| 1 | `jwallace145/guitar-knowledge-base` | `ci.yml`, `preview.yml`, `release-please.yml` | `site-plan`, `site-preview`, `site-release-please`, `site-deploy` | `plan-role-arn`, `preview-role-arn`, `apply-role-arn`, `app-client-id` | `ci: call jwall engineering's platform at live instead of jaws` |
| 2 | `jwallace145/cs-survival-guide` | `build.yml`, `preview.yml`, `release-please.yml` | the same | the same | the same |
| 3 | `jwallace145/site` | `ci.yml`, `preview.yml`, `release.yml` | the same | the same | the same |
| 4 | `Braveheart-Chess/braveheart-lichess-bot` | `release-to-lichess.yml` | `container-release` | nothing | `ci(deploy): call jwall engineering's platform at live instead of jaws` |
| 5 | `Braveheart-Chess/braveheart-selfplay` | `datagen.yml`, `relabel.yml` | `remote-task` | nothing | `ci(infra): call jwall engineering's platform at live instead of jaws` |
| 6 | `Braveheart-Chess/braveheart-trainer` | `gpu-smoke.yml`, `train.yml` | `remote-task` | nothing | the same as 5 |
| 7 | `Braveheart-Chess/braveheart` | `match.yml`, `sprt.yml` (three calls) | `remote-task` | nothing | the same as 5 |

Every file is under `.github/workflows/`. Today the sites pin `@v0.76.0`, the three task projects `@v0.76.0` or `@v0.80.1`, and the bot `@v0.76.0`.

**Interfaces:**
- Consumes: the hub's project-facing callers at `live` (plan 06, Task 5). They offer every Jaws input but the platform's own and the role overrides, and pass every output through.
- Produces, in each project:
  - every `uses: Jaws-Platform/jaws/.github/workflows/<name>.yml@<ref>` becomes `uses: JWall-Engineering/platform/.github/workflows/<name>.yml@live`;
  - each `with:` keeps its keys, but those the table leaves out;
  - a site's `site-plan` and `site-preview` calls pass `app-private-key: ${{ secrets.COMMENTS_APP_PRIVATE_KEY }}`;
  - each job keeps its `permissions`;
  - a comment that names `jaws-platform-comments` names JWall Engineering Comments instead.
- Produces a site's checks `<job> / <hub job> / jwall …`: `plan / plan / jwall plan` and `preview / preview / jwall preview deploy`, as the PR's run reports them.
- Produces the call check, `<scratch>/check_calls.py WORKFLOW...`, kept outside the project and run with `uv run --no-project --with pyyaml python -I`. For each job whose `uses` starts with `JWall-Engineering/platform/.github/workflows/`:
  - it reads that caller's `on.workflow_call` at `live`, with `gh api -H "Accept: application/vnd.github.raw" "repos/JWall-Engineering/platform/contents/.github/workflows/<file>?ref=live"`. PyYAML reads the key `on` as `True`;
  - it reports a ref other than `live`; a `with:` key the caller doesn't take; a required input left out; the same two for `secrets:`; and a `needs.<job>.outputs.<name>` anywhere in the file that the caller doesn't output.

  It prints one line per problem, naming the file, the job and the key, or `the calls agree with the hub's callers at live`. It exits 1 on any problem, and when no job calls the hub at all.

- [ ] **Step 1: Write the call check** per the Interfaces.

- [ ] **Step 2: Run it on the project's files and watch it fail**

```bash
git switch -c switch-to-hub origin/main
uv run --no-project --with pyyaml python -I <scratch>/check_calls.py .github/workflows/<each file in the table>
```

Expected: `no job calls JWall-Engineering/platform's workflows`, and exit 1.

- [ ] **Step 3: Edit the calls** per the Interfaces.

- [ ] **Step 4: Run the check again and watch it pass**

Expected: `the calls agree with the hub's callers at live`, and exit 0. A problem line names the file, the job and the key. Fix the call, never the hub's caller.

- [ ] **Step 5: Run the project's own checks, then commit and open the PR**

```bash
git add .github/workflows
git commit -m "<the table's commit>"
git push -u origin switch-to-hub
gh pr create --title "<the same>" --body-file <the project's filled template>
```

The body says that the project now names no Jaws version. For a site, it also lists the variables and secret that go unused, the checks' new names, and O8's steps.

- [ ] **Step 6: Read the PR's checks**
  - A site: `plan / plan / jwall plan` passes and reads `No changes.` through the filter, and `preview / preview / jwall preview deploy` deploys the preview.
  - A task or bot repository: its own checks pass. Its calls run with its next task or release (ruling 6).

---

### Task 8: The conventions and the organization profiles

**Repositories:** `jwallace145/repository-template`, `JWall-Engineering/.github` and `Jaws-Platform/.github`, branch `hub-conventions` in each. **When:** the first switch has merged, so a working example exists.

**Files:**
- `repository-template`:
  - `organization-conventions.md`: "Release bot" (the Apps example), "Organization secrets and variables", "Cloud infrastructure with Jaws", and the checklist;
  - `repository-conventions.md`: "CI baseline", "Cloud infrastructure with Jaws", and the checklist.
- `JWall-Engineering/.github`: `profile/README.md`, "What's here, and what's coming"
- `Jaws-Platform/.github`: `profile/README.md`, its onboarding steps and its `jaws` row

**Interfaces:** Produces these statements, in each document's own words (spec 6.11):
- Onboarding is one reviewed change to the hub's `config/projects.yaml`, in `JWall-Engineering/platform`, under the project's GitHub owner.
- The MUST that no organization keeps its own Terraform has one exception: the hub's `owner/` folders, until `jaws bootstrap` replaces them.
- A repository calls the hub's workflows at `@live`, names no Jaws version, and Dependabot bumps nothing of Jaws's. It needs no role variable, because the hub derives every role. It passes secrets by name, since `secrets: inherit` stops at an organization.
- A repository whose workflows post comments, today a site, has the hub's comments App installed and holds its key as `COMMENTS_APP_PRIVATE_KEY` (plan 06, D4). Organizations install JWall Engineering Comments (`jwall-engineering-comments`) on those repositories, not `jaws-platform-comments`.
- "AWS role ARNs from Jaws are repository variables" goes, in both documents.
- What the documents say about `jaws.yaml` stays as it is.
- JWall-Engineering's profile: `platform` holds and applies the platform's configuration.
- Jaws-Platform's profile: `jaws` is the product (the CLI, its stacks and workflows, and the public image), and a platform's hub onboards its projects.

- [ ] **Step 0: Branch,** in each of the three repositories: `git fetch origin && git switch -c hub-conventions origin/main`

- [ ] **Step 1: Edit each document** per the Interfaces.

- [ ] **Step 2: Run each repository's checks**

Run: `npm ci && npm test` in each.
Expected: PASS.

- [ ] **Step 3: Commit and open the three PRs**

```bash
git commit -am "docs(conventions): onboard and run projects through the platform's hub"   # repository-template
git commit -am "docs(profile): say the platform repository now applies the configuration"  # JWall-Engineering/.github
git commit -am "docs(profile): describe jaws as the product a platform's hub runs"         # Jaws-Platform/.github
```

Then, in each: `git push -u origin hub-conventions && gh pr create --title "<its commit>" --body-file <filled template>`.

---

### Task 9: No product test reads the owner's configuration

**Repository:** `jaws`, branch `hub-split/07-cleanup`. Tasks 9–14 share it and one PR. **When:** O8's seven switches have merged.

**Files:**
- Delete: `tests/platform/`.
  - Its owner checks are the hub's (plan 06, ruling 7).
  - `test_release_infra.py`'s checks move into `tests/test_release_infra.py`.
  - `test_isolation.py` becomes `tests/test_no_owner_configuration.py`, and `test_no_owner_values.py` Task 13's guard.
  - The backend checks go with the backend files (Task 12).
- Create: `tests/test_no_owner_configuration.py`
- Modify:
  - `tests/conftest.py`: `PLATFORM_CONFIG_DIR` goes. If the privacy hook refuses an edit to `tests/conftest.py`, hand that edit to the owner;
  - `tests/test_release_infra.py`;
  - `foundation/config.tf` (its `config_path` variable and `local.config_path`), and `monitoring/variables.tf` and `monitoring/config.tf` (the same two);
  - `foundation/tests/foundation.tftest.hcl`, `monitoring/tests/monitoring.tftest.hcl`;
  - `AGENTS.md`: its sentence on how the tests read the configuration.

**Interfaces:**
- Produces, in both stacks, `variable "config_path"` with a validation:
  - condition: `var.config_path != null || local.in_image` (Terraform 1.14 lets a validation read a local);
  - error_message: "No configuration: run in a platform's image, which holds /etc/jaws/config, or pass config_path (a caller's JAWS_CONFIG, as TF_VAR_config_path).";
  - `local.config_path = var.config_path != null ? var.config_path : local.image_config_path`. The fallback to the repository's `config/` goes.
- Produces: the foundation's tests read the datasets fixture `../tests/fixtures/datasets` (its `README.md` and `braveheart-selfplay/positions.yaml`), not the repository's `datasets/`.
- Produces, in `tests/test_release_infra.py`, checks of `release-infra/` against itself and GitHub, never `config/` (ruling 11).

- [ ] **Step 0: Branch:** `git fetch origin && git switch -c hub-split/07-cleanup origin/main`

- [ ] **Step 1: Write the failing tests**
  - **Both stacks:** replace the runs that read the repository's `config/` on purpose, `reads_its_configuration_and_datasets_from_the_repository_outside_the_image` and `reads_its_configuration_from_the_repository_outside_the_image`, with:

```hcl
run "stops_without_a_configuration" {
  command = plan

  variables {
    config_path = null
  }

  expect_failures = [var.config_path]
}
```

  - **`foundation/tests/foundation.tftest.hcl`:** its file-level `variables` block sets `datasets_path = "../tests/fixtures/datasets"`, and its comment says why.
  - **`tests/test_release_infra.py`:** each failure names the field, never the value.
    - `test_its_state_is_in_its_own_account_s_bucket`: `main.tf` names one `account_id` of twelve digits, and `backend/prod.hcl`'s `bucket` is `jaws-terraform-state-<that ID>`.
    - `test_it_trusts_this_repository`: `local.repository.name` is `Jaws-Platform/jaws`. When `GITHUB_REPOSITORY == "Jaws-Platform/jaws"`, its `owner_id` and `repository_id` are `GITHUB_REPOSITORY_OWNER_ID` and `GITHUB_REPOSITORY_ID`; elsewhere the test is skipped.
    - `test_the_publishing_role_is_outside_jaws_s_name_root`: the role is `release-infra-publish`, and not `jaws-*` (`AGENTS.md`).
  - **`tests/test_no_owner_configuration.py`:**

```python
def test_no_test_reads_a_configuration_at_the_repository_root() -> None:
    """The product's tests read tests/fixtures/platform/; a platform's own checks are its hub's."""
    readers = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in (REPO_ROOT / "tests").rglob("*.py")
        if path.name != "test_no_owner_configuration.py"
        and (
            "PLATFORM_CONFIG_DIR" in path.read_text() or 'REPO_ROOT / "config"' in path.read_text()
        )
    )
    assert readers == []
```

- [ ] **Step 2: Run them and watch them fail**

Run: `(cd foundation && terraform init -backend=false >/dev/null && terraform test) ; (cd monitoring && terraform test) ; uv run pytest -q -o addopts=""`
Expected: FAIL. Neither stack validates `config_path`, `conftest.py` and `tests/platform/` read `config/`, and the release-infra checks don't exist yet.

- [ ] **Step 3: Implement** the validation and the local in both stacks, delete `tests/platform/`, and drop `PLATFORM_CONFIG_DIR`. Then regenerate the foundation's fixtures with `uv run python -m tests.test_foundation_fixtures`.
  - Make the configuration's locals an empty document unless `var.config_path != null || local.in_image`, rather than wrapping them in `try()`.

- [ ] **Step 4: Run them and watch them pass**

```bash
(cd foundation && terraform test) && (cd monitoring && terraform test)
uv run pytest -q -o addopts=""
```

Expected: both stacks' tests pass, and the pytest run ends with `N passed`.

- [ ] **Step 5: Commit, then run the suite with no configuration at all**

```bash
git add -A tests foundation monitoring AGENTS.md
git commit -m "test(cli): run the product's tests without any of the owner's configuration"
work=$(mktemp -d -p <scratch>) && git worktree add --detach "$work" HEAD >/dev/null
for dir in config datasets; do rm -rf "${work:?}/$dir"; done
(cd "$work" && uv run pytest -q -o addopts="" | tail -1); git worktree remove --force "$work"
```

Expected: the run in the worktree ends with `N passed`.

---

### Task 10: Today's mode and `jaws-cli` leave the workflows, the action and the image

**Files:**
- Modify:
  - `.github/workflows/site-plan.yml`, `site-preview.yml`, `site-deploy.yml`, `remote-task.yml`, `container-release.yml`;
  - `.github/actions/jaws/action.yml`;
  - `Dockerfile`, and `.github/workflows/ci.yml`'s `image` job;
  - `release-please-config.json`;
  - `docs/platform-workflows.md` ("Project-facing workflows": the mode without a platform image goes), `README.md` ("Reusable workflows for site repositories", "Jaws's public image"), the caller sections of `docs/remote-tasks.md` and `docs/lichess-bot.md`, `AGENTS.md` ("Version literals are Release Please's") and `CONTRIBUTING.md` ("Releases", item 1).
- Test: `tests/test_site_workflows.py`, `tests/test_remote_task_workflow.py`, `tests/test_container_release_workflow.py`, `tests/test_jaws_action.py`, `tests/test_cli_image.py`, `tests/test_versions.py`, `tests/test_bots_registry.py`

**Interfaces:**
- Produces, in the five project-facing workflows (plan 05, ruling 1: "Plan 07 removes today's mode"):
  - `platform-image`, `account-id` and `name-root` are `required: true`, with no default;
  - `check-prefix` keeps its default, `jaws`, and the role inputs stay optional overrides (plan 05, ruling 2);
  - `platform-role`, the credentials and `platform-image` run with no condition, and the `jaws` steps take no `role-arn`;
  - `remote-task.yml` and `container-release.yml` always read `.jaws-platform/config`, and the branches of their `role` steps that read `config env` go.
- Produces the `jaws` action:
  - its inputs are `command`, `image` (required), `platform-commit`, `platform-source`, `github-token`, `debug` and `head-sha`;
  - its steps `check`, `credentials`, `ecr` and `image` go, and with them `IMAGE_TAG`, `role-arn` and `aws-region`.
- Produces: Release Please's `extra-files` is `["src/jaws/__init__.py"]`.
- Produces the `Dockerfile`'s one image, the stage `generic`, with no `COPY config` or `COPY datasets`. The public job looks for that stage (plan 04, ruling 2). CI builds and budgets only `jaws:ci`.

- [ ] **Step 1: Write the failing tests**
  - `test_each_project_facing_workflow_needs_the_platform_s_identity`, over the five workflows: each of `platform-image`, `account-id` and `name-root` is `{"required": True, "type": "string"}`, plus its description, with no `default`.
  - `test_the_role_always_comes_from_the_identity`, over the same five: no step's `if` names `platform-image`, `account-id`, `name-root`, `steps.role.outputs.arn` or `steps.platform.outputs.arn`, and no step runs `config env`.
  - `test_the_jaws_action_runs_only_a_given_image`:
    - the action's inputs are exactly the seven above, and `image` is required;
    - no step uses `configure-aws-credentials` or `amazon-ecr-login`;
    - the action's text holds neither `IMAGE_TAG` nor `/config`.
  - `test_the_image_carries_no_configuration`: the `Dockerfile` holds no `AS jaws-cli`, `COPY config` or `COPY datasets`, and does hold `AS generic`.
  - `test_release_please_bumps_only_the_package_version`: `extra-files` is `["src/jaws/__init__.py"]`.
  - **Delete the tests of today's mode:**
    - `test_without_a_platform_image_a_site_job_runs_as_today`, `test_without_a_platform_image_a_task_runs_as_today` and `test_without_a_platform_image_a_release_runs_as_today`;
    - `test_without_an_image_the_action_runs_as_today`, `test_the_action_needs_a_role_or_an_image`, and `tests/test_jaws_action.py`'s tests of the configuration it read;
    - `test_action_yml_uses_the_generic_updater`, and `tests/test_cli_image.py`'s tests of the `jaws-cli` stage.
  - **Change the tests of plan 05 that spell today's mode:** `test_each_site_workflow_takes_the_platform_s_identity` and `test_it_takes_the_platform_s_identity` expect `required: True` and no default. `test_in_a_hub_the_role_comes_from_the_identity` and `test_in_a_hub_the_release_role_comes_from_the_platform_s_identity` expect no `if` and no `role` step in `container-release.yml`. `test_runs_the_cli_from_this_workflow_commit` expects `JAWS_TOOL_CONFIG: .jaws-platform/config`. `test_in_a_hub_the_task_role_comes_from_the_platform_s_identity` expects no `config env`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest -q -o addopts=""`
Expected: FAIL. The identity is optional, and the action still reads `config/`.

- [ ] **Step 3: Implement it** per the Interfaces, with the Files' docs.

- [ ] **Step 4: Run them, and smoke-test the image**

```bash
uv run pytest -q -o addopts="" && npm test
docker build --platform linux/amd64 --build-arg TERRAFORM_VERSION=1.14.7 -t jaws:local .
docker run --rm --network none --entrypoint sh jaws:local -c 'test ! -e /etc/jaws' && echo "no configuration inside"
```

Expected: PASS, then `no configuration inside`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/site-plan.yml .github/workflows/site-preview.yml .github/workflows/site-deploy.yml \
  .github/workflows/remote-task.yml .github/workflows/container-release.yml .github/actions/jaws \
  release-please-config.json docs README.md AGENTS.md CONTRIBUTING.md tests/test_site_workflows.py \
  tests/test_remote_task_workflow.py tests/test_container_release_workflow.py tests/test_jaws_action.py \
  tests/test_versions.py tests/test_bots_registry.py
git commit -m "refactor(workflows)!: run the project-facing workflows only from a platform's image"
git add Dockerfile .github/workflows/ci.yml tests/test_cli_image.py
git commit -m "refactor(cli)!: build only the generic image"
```

---

### Task 11: `ecr.repository` becomes optional

**Files:**
- Modify:
  - `src/jaws/settings.py`: `EcrSection.repository`, and the check that the hub's image isn't `ecr.repository`'s;
  - `src/jaws/cli.py`: `config env`;
  - `foundation/ecr.tf`, and `foundation/oidc.tf`'s preconditions;
  - `foundation/outputs.tf`: `sites_image_repository_url` is `one(module.sites_image[*].url)`, null without `ecr.repository`;
  - `README.md`: the `ecr.tf` row, and the `tool.yaml` row of the configuration table.
- Test: `tests/test_settings.py`, `tests/test_one_account.py` (whose existing `ecr_repository=jaws-cli` expectation goes), `tests/test_platform_stacks.py`, `foundation/tests/foundation.tftest.hcl`, and `tests/test_foundation_fixtures.py` for two fixtures
- Regenerate: `foundation/tests/fixtures/*.yaml`

**Interfaces:**
- Produces `EcrSection.repository: str | None = None`, with today's pattern when set. `keep_release_images` and `expire_untagged_after_days` stay required: the bot images' repositories take them (`stack.py`).
- Produces: `jaws config env` prints no `ecr_repository=` line. Its one reader, `jaws`'s release `account` job, went in Task 4.
- Produces, in `foundation/ecr.tf`:
  - `local.cli_image = try(local.account.ecr.repository, null)`;
  - `local.sites_image_repository_arn` is null without it, and `local.image_repository_arns = compact([local.sites_image_repository_arn, local.hub_image_repository_arn])`;
  - `module "sites_image"` takes `count = local.cli_image == null ? 0 : 1`, with a `moved` block from `module.sites_image` to `module.sites_image[0]`, so a platform that keeps it sees only a move;
  - the check `sites_image_repository_arn_matches` iterates `module.sites_image`.
- Produces, in `foundation/oidc.tf`:
  - the check that `platform.hub.image` isn't `ecr.repository` holds only when that is set;
  - a new precondition: `local.hub != null || local.cli_image != null`, with "The platform has no image repository: set platform.hub (config/platform.yaml), whose image every run uses."
- Produces two fixtures: `no-cli-image.yaml`, which is `hub.yaml`'s changes without `ecr.repository`; and `no-image.yaml`, the default without `ecr.repository`.

- [ ] **Step 1: Write the failing tests**
  - `test_the_cli_image_repository_is_optional` (`tests/test_settings.py`): the fixture without `ecr.repository` loads, with `settings.ecr.repository is None` and `settings.ecr.keep_release_images == 20`.
  - `test_config_env_names_no_image_repository` (`tests/test_one_account.py`): no line of `config env` starts with `ecr_repository=`.
  - `test_the_cli_image_repository_keeps_its_state_address` (`tests/test_platform_stacks.py`): `foundation/ecr.tf` holds the `moved` block from `module.sites_image` to `module.sites_image[0]`.
  - `a_platform_without_the_cli_image_has_no_cli_image_repository` (`foundation.tftest.hcl`, with `no-cli-image.yaml` and plan 03's `override_module` for `module.hub_image`):
    - `length(module.sites_image) == 0 && local.image_repository_arns == [local.hub_image_repository_arn]`;
    - every `module.site_ci_plan` role's policy keys are `toset(["tfstate/read", "static-site/read", "ecr/pull"])`;
    - `module.infra_ci_apply.policy_arns` has `ecr/push` and `ecr/pull`, and neither `ecr/push-2` nor `ecr/pull-2`.
  - `refuses_a_platform_with_no_image`, with `no-image.yaml`: `expect_failures = [data.aws_iam_openid_connect_provider.github]`.
  - Every existing run still passes unchanged. With `ecr.repository` set, `count` is 1.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run python -m tests.test_foundation_fixtures && (cd foundation && terraform test) ; uv run pytest -q -o addopts=""`
Expected: FAIL. `ecr.repository` is required, and `module.sites_image` has no count.

- [ ] **Step 3: Implement it** per the Interfaces.

- [ ] **Step 4: Run them and watch them pass**

Run: `(cd foundation && terraform validate && terraform test) && uv run pytest -q -o addopts="" && uv run mypy`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src tests foundation README.md
git commit -m "feat(foundation): make the cli image's repository optional, so a platform can retire it"
```

---

### Task 12: The owner's platform leaves `jaws`

> **Reviews:** three commits are sealed: the deletion commit; the `README.md` commit, whose removed lines spell the account ID (the intro and `Accounts`); and the hub's README commit, whose added lines do.

**Files:**
- Delete, in one sealed commit:
  - `config/`, `datasets/`, `owner-access/`, `billing-export/`;
  - `foundation/backend/`, `monitoring/backend/`, `data-access/backend/`;
  - `docs/owner-access.md`, `docs/billing-export.md`, `docs/consumer-note.md`.
- Delete:
  - `tests/test_owner_access.py`, `tests/test_billing_export.py`;
  - the `ci.yml` jobs `owner-access-stack` and `billing-export-stack`, and their `.pre-commit-config.yaml` hooks.
- Modify:
  - `commitlint.config.mjs` and `CONTRIBUTING.md`'s Scopes;
  - `scripts/apply-repo-settings.sh`: two checks go;
  - `.dockerignore`: `owner-access` goes;
  - the tests that list those roots: `tests/test_versions.py`, `tests/test_hooks.py`, `tests/test_monitoring_workflows.py`, `tests/test_cli_image.py`;
  - `AGENTS.md`: the owner's folders, and their names in the module-pins rule and in "Things that need the owner"; their checklist line; and the configuration paragraph;
  - the comments that name the removed folders, scripts or docs: `src/jaws/product.yaml`, `src/jaws/access.py`, `src/jaws/settings.py` and `foundation/state.tf`;
  - `README.md`: ruling 9's moves, and the product's own intro, "Layout", "Accounts" and "Owner hand-off".
  - the links to the deleted docs and folders in `docs/costs.md`, `docs/databricks.md`, `docs/datasets.md`, `docs/lichess-bot.md`, `docs/monitoring.md` and README's "Bot projects". Each says "the platform's runbook, in its hub", without a link: a link to the hub would add the brand Task 13 refuses.
- Modify, in the hub (branch `from-jaws`, its own PR): `README.md`
- Create: `tests/test_product_tree.py`, and `tests/test_ci_roles.py`, which keeps spec 2's anti-goal in the product once the two tests it names are gone: "Any CI role gaining Identity Center or management-account access"

**Interfaces:**
- Produces the scopes (spec 6.12): `cli`, `foundation`, `sites`, `bots`, `databricks`, `access` ("data-access/"), `monitoring` ("The monitoring/ root and its docs"), `publishing`, `workflows`, `repo`, `deps`, `release`.
- Produces the required checks: Task 4's, without `Owner access stack validate, tflint, test` and `Billing export validate, tflint, test`.
- Produces, in the hub's README, a section `## The platform's setup, from jaws`. It holds `jaws`'s `Accounts`, `History`, `Bootstrap` and `Owner hand-off` sections:
  - verbatim from the cleanup branch's base, each a level lower;
  - with relative links made absolute at that commit, so every one still resolves.
- Produces `jaws`'s README sections for the product:
  - the intro: what Jaws provisions, for a platform its hub configures, and what this repository ships;
  - "Accounts": the `aws` section, with the fixture's values;
  - "Layout": no `config/`, `datasets/` or owner rows. "The tool configuration" stays, as what a platform's `config/` holds, with the fixture's values;
  - "Owner hand-off": the vendor's own steps only: the release bot, `publish`, `release-infra/`, the alias, the variables, and `JAWS_PUBLIC_IMAGE_KEEP` at v1.

- [ ] **Step 1: Write the failing test** in `tests/test_product_tree.py`

```python
BACKENDS = ("foundation/backend", "monitoring/backend", "data-access/backend")


def test_the_owner_s_platform_is_not_in_the_product() -> None:
    owned = ("config", "datasets", "owner-access", "billing-export", *BACKENDS)
    assert [path for path in owned if (REPO_ROOT / path).exists()] == []


def test_no_workflow_names_an_owner_s_folder() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text()
        assert "owner-access" not in text and "billing-export" not in text, path.name
```

And in `tests/test_ci_roles.py`, `test_the_ci_roles_take_only_known_catalog_policies`. Its `KNOWN_POLICIES` is a frozenset of the 29 jaws-ci policy names the foundation's roles take today, from `compute/manage` to `tfstate/write`: what `grep -ohE '"[a-z0-9-]+/[a-z0-9-]+"'` finds in `foundation/*.tf` but `versions.tf`. The test asserts that the same search's result is a subset of `KNOWN_POLICIES`. Its docstring says a new policy family is a reviewed change to that set, and that none may reach Identity Center or AWS Organizations.

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest -q -o addopts="" tests/test_product_tree.py tests/test_ci_roles.py`
Expected: `test_product_tree.py` FAILs, since every folder is still there. `test_ci_roles.py` passes already: it pins today's roles.

- [ ] **Step 3: Move the README's owner sections to the hub first,** by counted copy, printing only counts

```bash
jaws=~/Projects/Jaws-Platform/jaws hub=~/Projects/JWall-Engineering/platform
base=$(git -C "$jaws" merge-base origin/main HEAD)
git -C "$jaws" show "$base:README.md" \
  | awk '/^## (Accounts|History|Bootstrap|Owner hand-off)/ {p=1; print; next} /^## / {p=0} p' > <scratch>/moved.md
grep -c '^## ' <scratch>/moved.md
perl -pi -e 's/^(#+) /#$1 /' <scratch>/moved.md
perl -pi -e "s{\]\((?!https?://)([^)#][^)]*)\)}{](https://github.com/Jaws-Platform/jaws/blob/$base/\$1)}g; s{\]\(#}{](https://github.com/Jaws-Platform/jaws/blob/$base/README.md#}g" <scratch>/moved.md
perl -ne '$n++ while /\]\((?!https?:\/\/)/g; END { print $n + 0, " relative links\n" }' <scratch>/moved.md
```

Expected: `4` sections, then `0 relative links`. Then append them to the hub's README, under a heading and one sentence, printing only counts:

```bash
git -C "$hub" fetch origin && git -C "$hub" switch -c from-jaws origin/main
{ printf "\n## The platform's setup, from jaws\n\nThese sections came from jaws's README at the split, and are the platform's to reword.\n\n"
  cat <scratch>/moved.md; } >> "$hub/README.md"
git -C "$hub" diff --shortstat
git -C "$hub" add README.md && git -C "$hub" commit -m "docs(repo): keep the platform's setup and history from jaws's readme"
git -C "$hub" push -u origin from-jaws
gh pr create -R JWall-Engineering/platform --head from-jaws \
  --title "docs(repo): keep the platform's setup and history from jaws's readme" --body-file <filled template>
```

The owner reads the moved prose in that PR.

- [ ] **Step 4: Delete the owner's platform** in one sealed commit, printing only the count

```bash
git rm -r -q config datasets owner-access billing-export foundation/backend monitoring/backend data-access/backend
git rm -q docs/owner-access.md docs/billing-export.md docs/consumer-note.md
git commit -m "chore(repo)!: take the owner's configuration, datasets and folders out of jaws"
git diff --shortstat HEAD^ HEAD
```

- [ ] **Step 5: Make the rest** per the Files and Interfaces: the scopes, the checks, the CI jobs and hooks, the tests' root lists, `AGENTS.md`, and `README.md`'s product sections. Read `README.md` through the mask.

- [ ] **Step 6: Run everything and watch it pass**

Run: `AGENTS.md`'s "Before opening a PR" list, without its `billing-export` line, then `uv run pytest -q -o addopts="" tests/test_product_tree.py tests/test_jaws_workflows.py`.
Expected: PASS, `test_every_required_check_is_a_ci_job` included.

- [ ] **Step 7: Commit**

```bash
git add -A commitlint.config.mjs CONTRIBUTING.md scripts .dockerignore .pre-commit-config.yaml .github tests AGENTS.md
git commit -m "chore(repo): retire the config and datasets scopes and the owner's folders' checks"
git add README.md
git commit -m "docs(repo): describe jaws as the product, and leave the owner's setup to the hub"
```

---

### Task 13: The guard: no owner value in the product

> **Reviews:** the replacement commit is sealed: its removed lines hold account IDs.

**Files:**
- Create: `tests/test_no_owner_values.py`
- Modify, by counted substitution:
  - `README.md`, `AGENTS.md`, `CONTRIBUTING.md` and `docs/*.md`;
  - the five design records under `docs/superpowers/` that spell an account ID;
  - `pyproject.toml`: its description, which the public image's package metadata carries;
  - `.github/workflows/release-please.yml`: a comment;
  - `tests/test_settings.py`, `tests/conftest.py`, `tests/test_stack.py`, `tests/test_repository_name.py`.
  - `monitoring/tests/monitoring.tftest.hcl` and `tests/fixtures/errors/AWS-ASSUME-ROLE-PROPAGATION--sts-assume-role.txt`: their sample account IDs become `333333333333`;

**Interfaces:**
- Produces `def owner_value_problems(path: str, text: str) -> list[str]` in `tests/test_no_owner_values.py`. It returns one `"<rule>: <count>"` entry per rule that finds anything, never the value. The rules (ruling 8):
  - **account IDs:** a run of exactly twelve digits, outside a longer alphanumeric run and outside a UUID, other than `NEUTRAL_ACCOUNTS`;
  - **email addresses:** any outside `example.com`, `example.org`, `example.net` and the `.test` domains, other than the co-author address `noreply@anthropic.com`;
  - **brand names:** `jwall`, in any case, except under `BRAND_ALLOWED`.
- The files it checks: `git ls-files`, without `EXEMPT` and every `.terraform.lock.hcl`, and skipping files that aren't UTF-8.

```python
#: Spec 6.8's exception, the release history, and files that no person writes.
EXEMPT = ("release-infra/", "CHANGELOG.md", "uv.lock", "package-lock.json")
#: Where the owner's brand may stay: the split's own records, the maintainer's login, this file.
BRAND_ALLOWED = ("docs/superpowers/", ".github/CODEOWNERS", "tests/test_no_owner_values.py")
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
ACCOUNT_ID = re.compile(r"(?<![0-9A-Za-z])[0-9]{12}(?![0-9A-Za-z])")
#: The examples the tests and docs use, `000000000000`, the SDK for pandas layer's account (AWS's own, as the 2026-11-21 monitoring record spells it; copy it into the set from there), and Databricks's own AWS account (its Unity Catalog role).
NEUTRAL_ACCOUNTS = frozenset(
    {"000000000000", "111111111111", "222222222222", "333333333333", "123456789012", "111122223333", "414351767826"}
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}")
PLACEHOLDER_EMAIL = re.compile(r"(?i).+@(example\.(com|org|net)|[\w.-]+\.test)")
CO_AUTHOR = "noreply@anthropic.com"
BRAND = re.compile("jwall", re.IGNORECASE)
```

- [ ] **Step 1: Write the failing tests**

```python
def test_each_rule_finds_its_kind_and_spares_the_examples() -> None:
    nines = "9" * 12
    assert owner_value_problems("README.md", f"s3://jaws-billing-{nines}") == ["account IDs: 1"]
    assert owner_value_problems("README.md", "arn:aws:iam::222222222222:role/x") == []
    assert owner_value_problems("README.md", "00000000-0000-4000-8000-000000000001") == []
    assert owner_value_problems("README.md", "a" + "@" + "corp.io") == ["email addresses: 1"]
    assert owner_value_problems("README.md", "owner@example.com, admin@corp.test") == []
    assert owner_value_problems("README.md", "site-plan.yml@v0.6.1") == []
    assert owner_value_problems("docs/x.md", "J" + "Wall Engineering") == ["brand names: 1"]
    assert owner_value_problems("docs/superpowers/plans/x.md", "J" + "Wall Engineering") == []


@pytest.mark.parametrize("path", _files())
def test_no_product_file_holds_an_owner_value(path: str) -> None:
    if problems := owner_value_problems(path, (REPO_ROOT / path).read_text()):
        pytest.fail(f"{path} holds {', '.join(problems)}", pytrace=False)
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest -q -o addopts="" tests/test_no_owner_values.py`
Expected: a collection error (`NameError`) until `owner_value_problems` and `_files` exist. Then the second test fails on each file the Files list names.

- [ ] **Step 3: Replace each value** by counted substitution, and reword by hand the few sentences that no longer read:

| Rule | Found | Becomes |
|---|---|---|
| account IDs | the owner's IDs, in prose and in names | `<account-id>`, as in `jaws-terraform-state-<account-id>` |
| brand names | `jwall.engineering`, and names under it | `example.com`, and the same names under it |
| brand names | the owner's hub as an example | `Example-Hub/platform` |
| brand names | `jwallace145`, as a GitHub owner | `example-owner` |
| brand names | `jwallace145-release-bot` | `jaws-platform-release-bot`, `jaws`'s own release App |
| brand names | `jwall-admin`, the owner's admin profile | "the owner's admin profile" |
| brand names | `@jwall-engineering.test`, in the tests | `@example.com` |
| brand names | `jwall-databricks-poc.cloud.databricks.com` | `example-databricks-poc.cloud.databricks.com` |
| brand names | `.jwall-engineering-infra`, a checkout path a test forbids | the test asserts the path it wants, `.jaws-tool` |
| brand names | `pyproject.toml`'s description | "Provisions sites, bots, research projects and Databricks workspaces with Terraform, from one YAML file per project." |

The account IDs' substitution, run on the files Step 2 names, leaves the neutral values, UUIDs and longer runs alone:

```bash
perl -pi -e 's/(?<![0-9A-Za-z])(?<![0-9a-fA-F]{4}-)(?!(?:000000000000|111111111111|222222222222|333333333333|123456789012|111122223333|414351767826)(?![0-9]))[0-9]{12}(?![0-9A-Za-z])/<account-id>/g' <files>
```

If the privacy hook refuses an edit to `tests/conftest.py`, hand that edit to the owner.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest -q -o addopts="" && uv run ruff check && uv lock --check`
Expected: PASS.

- [ ] **Step 5: Commit.** The replacements' commit is sealed.

```bash
git add README.md AGENTS.md CONTRIBUTING.md docs pyproject.toml .github/workflows/release-please.yml monitoring/tests/monitoring.tftest.hcl tests/fixtures/errors
git commit -m "docs(repo): replace the owner's account ids and names with neutral ones"
git add tests
git commit -m "test(cli): fail on any value of a platform's owner in the product's files"
```

---

### Task 14: Open the cleanup pull request

- [ ] **Step 1: The roadmap**
  - Row 07's status becomes "in its pull request (#<n>); the hub then retires the old trust and `jaws-cli` (plan 07, Task 16)".
  - "During plan 07" gains this plan's owner steps, in a few words each.

```bash
git add docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md
git commit -m "docs(repo): add plan 07's rulings to the roadmap"
```

- [ ] **Step 2: Run the full checklist:** `AGENTS.md`'s "Before opening a PR", now without `billing-export`.
Expected: every command passes. A pytest run without `config/` is now the normal run.

- [ ] **Step 3: Push the branch and open the PR**
  - Title: `refactor(repo)!: take the owner's platform out of jaws`.
  - Body: the template.
    - Under Why, the breaking changes:
      - a project-facing workflow needs the platform's identity;
      - the image has no `jaws-cli` stage;
      - `ecr.repository` is optional;
      - `config env` prints no `ecr_repository`.
    - The hub's README PR, and O10.

```bash
git push -u origin hub-split/07-cleanup
gh pr create --title "refactor(repo)!: take the owner's platform out of jaws" --body-file <filled template>
```

Expected CI: every check passes. No platform plan runs in `jaws` any more (ruling 2): the hub's upgrade PR plans this release (O10).

---

### Task 15: The hub checks the Jaws release it pins

**Repository:** the hub, branch `pinned-release-check`. **When:** the hub has upgraded to the cleanup release (O10).

**Files:**
- Create: `tests/platform/test_jaws_release.py`

**Interfaces:**
- Consumes `JAWS_SOURCE`, `PLATFORM_CONFIG_DIR` and `owner_values` (plan 06, Task 3).
- Produces the exact half of ruling 8: spec 2's goal 1, checked with the hub's own values against the release it runs. `jaws`'s guard holds only patterns (Task 13).

- [ ] **Step 0: Branch:** `git fetch origin && git switch -c pinned-release-check origin/main`

- [ ] **Step 1: Write the failing test.** It fails until the hub pins the cleanup release.

```python
#: The release's history, its design records, the maintainer's login (ruling 8), Jaws's own release infrastructure, generated files.
EXEMPT = ("release-infra/", "CHANGELOG.md", "docs/superpowers/", ".github/CODEOWNERS", "uv.lock", "package-lock.json")


def _release_files() -> list[str]:
    listed = subprocess.run(
        ["git", "-C", str(JAWS_SOURCE), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    return [p for p in listed if not p.startswith(EXEMPT) and not p.endswith(".terraform.lock.hcl")]


def test_the_pinned_jaws_release_holds_no_owner_value() -> None:
    values = owner_values(load_document(PLATFORM_CONFIG_DIR))
    holding = []
    for path in _release_files():
        try:
            text = (JAWS_SOURCE / path).read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if any(value in text for value in values):
            holding.append(path)
    if holding:
        pytest.fail(
            f"the pinned jaws release holds the platform's values in {holding}", pytrace=False
        )
```

Also `test_the_pinned_jaws_release_holds_no_configuration`: `not (JAWS_SOURCE / "config").exists()`.

Also `test_the_pinned_release_s_fixture_has_every_section_the_platform_uses`: every section of the hub's `config/` is in `JAWS_SOURCE / "tests/fixtures/platform"`.

- [ ] **Step 2: Run it against the release before the cleanup, and watch it fail**

Run: `git clone -q --depth 1 --branch <the release before the cleanup> https://github.com/Jaws-Platform/jaws.git <scratch>/old && JAWS_SOURCE=<scratch>/old uv run --project .jaws-tool --locked pytest -q -o addopts="" tests/platform/test_jaws_release.py`
Expected: FAIL, naming the files and never a value.

- [ ] **Step 3: Run it against the pinned release, and watch it pass**

Run: `uv run --project .jaws-tool --locked pytest -q -o addopts=""`
Expected: PASS.

- [ ] **Step 4: Commit and open the PR**

```bash
git add tests/platform/test_jaws_release.py
git commit -m "test(repo): check that the jaws release the hub pins holds none of the platform's values"
git push -u origin pinned-release-check
gh pr create --title "test(repo): check that the jaws release the hub pins holds none of the platform's values" --body-file <filled template>
```

---

### Task 16: The hub retires the old trust and `jaws-cli`

**Repository:** the hub. Two PRs, each the owner's edit and the agent's checks, each released on its own.

> **Reviews:** both owner commits are sealed.

**16a. The trust,** on branch `retire-jaws-trust`. **When:** O10 is done.

**Files:**
- Modify (the owner, O11): `config/platform.yaml`. The first entry, `Jaws-Platform/jaws`, goes with its comment.
- Modify: `tests/platform/test_hub_identity.py`

**Interfaces:**
- Produces `platform.repositories`: `JWall-Engineering/platform` alone. So:
  - the roles of spec 6.6 trust only the hub;
  - the `Repository` tag, the zone's comment and the roles' descriptions name the hub (plan 03, ruling 2).

- [ ] **Step 0: Branch:** `git fetch origin && git switch -c retire-jaws-trust origin/main`

- [ ] **Step 1: Write the failing tests**
  - `test_the_hub_is_this_repository_and_trusted_second` becomes `test_the_hub_is_this_repository_and_the_only_one_trusted`: `[r.repository for r in platform.repositories] == ["JWall-Engineering/platform"]`.
  - `test_the_hub_s_ids_are_this_repository_s` reads the first entry.

- [ ] **Step 2: Run them and watch them fail,** then push the branch and wait for the owner's edit (O11)

```bash
uv run --project .jaws-tool --locked pytest -q -o addopts="" tests/platform/test_hub_identity.py
git add tests/platform/test_hub_identity.py
git commit -m "test(config): expect the hub to be the only repository the platform trusts"
git push -u origin retire-jaws-trust
```

Expected: FAIL. `Jaws-Platform/jaws` is still first. After the owner's edit and `git pull --ff-only`, the same run passes.

- [ ] **Step 3: Open the PR, and read its plans with the filter**

```bash
gh pr create --title "feat(config): stop trusting jaws's workflows now that the hub applies" --body-file <filled template>
```

Expected:
- `Terraform plan` and `Monitoring plan`: `0 to add`, `0 to destroy`, only `updated in-place`, and, if the cleanup release hasn't been released yet, the `moved:` lines for `module.sites_image`;
- `plan_attributes` lists only `assume_role_policy`, `description`, `comment`, `tags` and `tags_all`, with the node's `public_ip` output in hours;
- every other plan reads `No changes.`

**16b. `jaws-cli`,** on branch `retire-jaws-cli`. **When:** 16a is released.

**Files:**
- Modify (the owner, O12): `config/tool.yaml`. `ecr.repository` goes; `ecr.keep_release_images` and `ecr.expire_untagged_after_days` stay.

**Interfaces:**
- Consumes Task 11's optional `ecr.repository`.
- Produces a platform without `jaws-cli`. Every site role and the infra apply role keep only the hub image's policies.

- [ ] **Step 1: Confirm that nothing calls `jaws`'s workflows.** Read every non-archived repository's workflows under `jwallace145`, `Braveheart-Chess`, `Pi-Mathematical-Reasoning` and `Prog-Strength`, as this plan's writer did. Print only the matching `uses:` lines.

```bash
for owner in jwallace145 Braveheart-Chess Pi-Mathematical-Reasoning Prog-Strength; do
  for repo in $(gh repo list "$owner" --limit 200 --json nameWithOwner,isArchived --jq '.[] | select(.isArchived | not) | .nameWithOwner'); do
    for f in $(gh api "repos/$repo/contents/.github/workflows" --jq '.[] | select(.type == "file") | .path' 2>/dev/null); do
      gh api -H "Accept: application/vnd.github.raw" "repos/$repo/contents/$f" | grep -H --label="$repo/$f" 'uses: *Jaws-Platform/jaws/'
    done
  done
done
```

Run it with `bash`, since zsh doesn't split `$(…)`. Expected: no output. Tell the owner, who then empties `jaws-cli` (O12).

- [ ] **Step 2: Push the branch, and wait for the owner's edit (O12)**

```bash
git switch -c retire-jaws-cli origin/main && git push -u origin retire-jaws-cli
```

Then `git pull --ff-only`, and run `uv run --project .jaws-tool --locked pytest -q -o addopts=""`. Expected: PASS.

- [ ] **Step 3: Open the PR, and read its plans with the filter**

```bash
gh pr create --title "feat(config): retire the jaws-cli image repository" --body-file <filled template>
```

Expected `Terraform plan`:
- destroyed, exactly: `module.sites_image[0].aws_ecr_lifecycle_policy.this`, `module.sites_image[0].aws_ecr_repository.this`, and the IAM policies and attachments keyed `ecr/pull-2` and `ecr/push-2`;
- updated in place: the policies `ecr/pull` and `ecr/push`, and `plan_attributes` lists only `policy`;
- nothing created, and nothing replaced, and `Changes to Outputs:` for `sites_image_repository_url` alone.

Every other plan reads `No changes.` The owner then merges and releases (O12).
