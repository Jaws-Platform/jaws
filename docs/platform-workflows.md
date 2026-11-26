# The platform workflows: running Jaws from a hub

A hub is the repository that holds a platform's configuration, such as
`Example-Hub/platform`, and runs Jaws for it. Its workflow files are callers:
each is a few lines that call one of Jaws's reusable workflows at a release,
`Jaws-Platform/jaws/.github/workflows/<name>.yml@vX.Y.Z`. Projects then call
the hub's copies at `@live`. This page is for whoever writes the hub's callers.
The sections after this one each cover a group of workflows, with their inputs
and the permissions their callers grant.

## How a hub runs Jaws

### The identity

Each caller that runs the hub's image spells the platform's identity:

| Input | What it is | For example |
|---|---|---|
| `platform-image` | the hub image's private ECR repository | `jaws-platform` |
| `account-id` | the platform account, which holds that repository and every CI role | `123456789012` |
| `name-root` | the configuration's `context.name_root`, the root of every name | `jaws` |

A run builds each role it assumes from them, before it has any credentials:
`arn:aws:iam::<account-id>:role/<name-root>-<project>-ci-<role>`. A site's
project comes from its `jaws.yaml`. The workflows' role inputs, such as
`plan-role-arn`, become optional overrides, which must be roles in
`account-id`, so a project that calls the hub needs no role variable. The
registry is `<account-id>.dkr.ecr.us-east-1.amazonaws.com`: the region is
`us-east-1`, a product constant.

The three come together. A caller that passes `account-id` or `name-root`
without `platform-image` passes half an identity, and the job stops before any
AWS call, naming the input. A project-facing workflow given none of them runs
as it does for a project still on Jaws's own pin.

Each is a literal in the caller, never an expression. A project's run can read
neither the hub's variables, because a called workflow's `vars` are the calling
repository's, nor the hub's configuration, which is in an image the run can't
pull before it has a role. So the hub spells its identity, and the hub's CI
holds each literal to its configuration: `jaws platform check` compares them
with what the configuration in the pull request's candidate image says, and
fails a pull request where they disagree.

### The image's tags, and one build per run

Each hub release builds the image from the release commit and tags it
`sha-<hub commit>`. That tag never moves. `current` is the one tag that moves:
it names the build that is live. The repository keeps the newest ten `sha-`
builds, never expires the build `current` names, and expires untagged images
after 7 days, so a rollback reaches the last ten releases.

A run resolves `current` once, at its start, and runs that build for every
step ([spec 6.3](superpowers/specs/2026-11-22-hub-split-design.md#63-the-images)),
so a hub release that lands mid-run can't mix two configurations:

1. `platform-role` builds the job's role from the identity, and the job
   assumes it.
2. `platform-image` checks that the role is in `account-id`, and resolves
   `current` to one manifest digest with `aws ecr batch-get-image`, which the
   role's pull grant allows (it doesn't grant `DescribeImages`). It then loads
   or pulls that build, and outputs the image ID the runner reports.
3. Every later step runs the build by that ID. The `jaws` action, given it as
   `image`, runs it as given: it assumes no role, logs in nowhere and pulls
   nothing.
4. A later job of the run takes the digest from the first job's outputs, and
   passes it to `platform-image` as `digest` in place of the tag.

A pull request's candidate is never pushed. The job that builds it passes it
to the plan jobs as this run's artifact `platform-image`, and `platform-image`,
given `artifact` and the candidate's `image-id`, loads it, checks its ID and
reaches no registry.

### The cache

A repository pulls each build once. `platform-image` keeps the build's
`docker save` in the Actions cache, keyed by the image ID the runner reports,
and checks the ID of what it loads from there. An entry that holds another
build, or doesn't load, never fails the run: the build is pulled again, with a
warning that names the entry's key.

The image ID depends on the runner's image store. Docker's classic store
reports a build's config digest, and the containerd store, Docker 29's default
on a fresh install, its manifest digest. The cache is looked up under both,
and `platform-image` logs the ID with both digests, so a run's log shows which
store its runner has.

What it saves: the hub's data-access sweep runs every 15 minutes, 96 times a
day. Without the cache, each run would pull the build, about 283 MiB: about
875 GB a month from private ECR to GitHub's runners, about $70 at $0.09 per GB
past the free 100 GB. With it, the sweep pulls once per hub release. The cache
is free up to 10 GB a repository. A cache belongs to a branch, and a branch
falls back to the default branch's, so a pull request's branch pulls a build
once, until `main`'s cache holds it.

### The labels, and the footer's commit

The hub's build carries labels that name what it was built from:
`org.opencontainers.image.revision`, the hub commit;
`org.opencontainers.image.source`, the hub repository's URL; and
`org.opencontainers.image.base.name` and `.base.digest`, the Jaws release it is
built on. `platform-image` outputs the first two as `platform-commit` and
`platform-source`. A job passes them, from the same `platform-image` step as
its `image`, to the `jaws` action, which gives them to the CLI as
`JAWS_PLATFORM_COMMIT` and `JAWS_PLATFORM_SOURCE`.

The comments' footer then names the build's hub commit after "Built with Jaws
vX.Y.Z": `Platform` and the commit's short SHA, linked to the commit on the
hub. It is the commit of the build the run resolved, not the hub's `main`, so
a reader sees which configuration planned or applied. Without the labels, the
footer is as it is outside a hub.

## Project-facing workflows

### `site-plan.yml`, `site-preview.yml` and `site-deploy.yml`

Each takes the identity above as inputs, all optional with default `""`:
`platform-image`, `account-id` and `name-root`. Each also takes `check-prefix`,
default `jaws`, the first word of the job's check name. Its role input
(`plan-role-arn`, `preview-role-arn` or `apply-role-arn`) is optional too: it is
needed without `platform-image`, and with it is an override that must be a role
in `account-id`. `site-preview.yml` also takes `artifact`, and `site-deploy.yml`
`artifact` and `tag`. The comments' App is the platform's: `app-client-id` and
the `app-private-key` secret.

With an identity, a job builds its role with `platform-role`, assumes it,
resolves the image once with `platform-image`, and runs every `jaws` step by
that image's ID. Without one, it runs as it does at a pin from before hubs: the
same `jaws-cli` image, the role input, and `config/` from the tool checkout.
Half an identity stops the job before any AWS call.

A hub's caller for `site-plan`, with placeholder values. `app-client-id` is
the App's client ID, a literal because it isn't secret and a project's run can't
read the hub's variables:

```yaml
name: plan
on:
  workflow_call:
    secrets:
      app-private-key: { required: false }
jobs:
  plan:
    permissions:
      contents: read
      id-token: write
      pull-requests: write
    uses: Jaws-Platform/jaws/.github/workflows/site-plan.yml@vX.Y.Z
    with:
      platform-image: jaws-platform
      account-id: "123456789012"
      name-root: jaws
      check-prefix: example
      app-client-id: Iv23liEXAMPLE0000000
    secrets:
      app-private-key: ${{ secrets.app-private-key }}
```

### `remote-task.yml` and `container-release.yml`

Both take the same three inputs, `platform-image`, `account-id` and `name-root`,
default `""`. With an identity, a job builds its role with `platform-role` (`task`
or `release`), assumes it, resolves the hub's image with `platform-image` and
extracts its configuration to `.jaws-platform`, which the CLI then reads
(`--config .jaws-platform/config`, with the image's infra root and commit).
Without one, a job runs as it does at a pin from before hubs: the role from
`config env`, and `config/` from the tool checkout.

They run the CLI from source, with `uv` from the workflow's own commit, not
from the image (ruling 14): `remote-task` needs the CLI itself to take the
cancel signal and terminate the instance, and `container-release` needs Docker
on the runner for its build. The configuration comes from the image; the code,
from the checkout.

### The check names

A job's check name is `<caller job> / <check-prefix> <job>`: `jaws plan`,
`jaws preview deploy`, `jaws preview remove` and `jaws release` by default, so a
project that requires `plan / jaws plan` is unchanged. A project that calls a
hub's copy has one more level: its own job's name, then the hub's caller's, then
the prefix and the job, for example `plan / plan / example plan` for the caller above.
For plans 06 and 07:
a project's required checks must name that longer form when it switches to the
hub.

## The hub's pull requests

### `platform-ci.yml`: the jobs and their checks

The hub's CI caller calls `platform-ci.yml` on each pull request. Each job reports
its check as `<caller job> / <check>`:

| Job | Check | What it does |
|---|---|---|
| `candidate` | `Platform check` | builds the candidate and checks the hub inside it |
| `foundation` | `Terraform plan` | plans the foundation, as the `infra` plan role |
| `monitoring` | `Monitoring plan` | plans monitoring, once the configuration has a monitoring section |
| `data-access` | `Data access plan` | plans data access, rendered with the base branch's registry |
| `projects` | `Site plan (<project>)`, `Bot plan (<project>)`, `Databricks plan (<project>)` | one plan for each project the configuration onboards |

The first four are the hub's required checks. For a caller job named `ci`,
they are `ci / Platform check`, `ci / Terraform plan`, `ci / Monitoring plan`
and `ci / Data access plan`. A job skipped by its condition passes, as the
monitoring plan is before the configuration has a monitoring section, or for a
fork's pull request. The project plans aren't required, since they come and go
with the projects.

Each plan posts a sticky comment, under the header `terraform-plan`,
`monitoring-plan`, `data-access-plan` or `<site|bot|databricks>-plan-<project>`,
and uploads its `.jaws/` run log. The monitoring plan and the project plans are
skipped while their role doesn't exist yet: monitoring's with a notice, and a
project's with a warning. The foundation apply of the hub release that adds the
monitoring section, or onboards the project, creates the role. A Databricks
project's plan is also skipped while Databricks is disabled, and so is the plan
of a project whose file names another project, as when a project is being
renamed. Data access plans nothing while Databricks has nothing to reconcile,
and doesn't run for Dependabot.

### The candidate

The `candidate` job builds the pull request's `Dockerfile` as the hub's image:
the candidate.

1. `platform-base` reads the `Dockerfile`'s one `FROM`, which must pin the Jaws
   image by tag and digest. It reads it with `jaws platform check`'s own
   pattern, so the check and the build read one `FROM` alike.
2. `platform-base` also asks ECR Public, anonymously, whether the pinned digest
   is still published. ECR Public keeps only the newest Jaws versions until v1,
   so a pin can be pruned while the hub still names it. The job then fails with
   what to do: merge the open upgrade PR, or move the `FROM` line to a recent Jaws
   release.
3. `platform-build` builds it and loads it on the runner. Its labels name the
   pull request's head commit and the Jaws base, and its image ID is the one the
   runner reports.

The candidate is never pushed (ruling 5). An ECR push grant can't be limited by
tag, so a pull request role that could push a candidate could also move
`current`. The job saves the candidate (`docker save`) as this run's artifact
`platform-image`, kept a day. Each plan job loads it with `platform-image`,
given `artifact` and the candidate's `image-id`, which checks the loaded ID and
reaches no registry. So every plan runs with the pull request's configuration
and Jaws pin
([spec 6.3](superpowers/specs/2026-11-22-hub-split-design.md#63-the-images),
[6.5](superpowers/specs/2026-11-22-hub-split-design.md#65-upgrades-and-rollout)):
an upgrade's plans show what it changes everywhere before it merges.

Inside the candidate, offline (`docker run --network none`), the job:

- validates the configuration with `config show`, and discards what it prints,
  since a hub's logs are public;
- runs `jaws platform check`, with the checkout mounted read-only at `/hub`;
- reads the platform's identity and gates with
  `config env --monitoring --databricks --brand --platform`, and the projects
  with `config projects site bot research databricks`. Each plan job builds its
  role from that identity with `platform-role`, and the `projects` job's matrix
  is that list.

### What the check holds

`jaws platform check` fails the pull request, naming the file and both values,
when the hub's pins or identity disagree:

- **One version, two pins** (ruling 11,
  [spec 6.4](superpowers/specs/2026-11-22-hub-split-design.md#64-workflows)).
  Every caller's `Jaws-Platform/jaws/.github/workflows/<name>.yml@<ref>`, the
  `Dockerfile`'s tag and the candidate's own Jaws version are one release. The
  `Dockerfile`'s one `FROM` pins the Jaws image by tag and digest.
- **The identity is literal** (ruling 10). Each caller of a workflow that runs
  the image spells `platform-image`, `account-id` and `name-root`, and a site
  workflow's caller spells `check-prefix` too. Each is a quoted literal equal to
  the configuration's `platform.hub.image`, `aws.account_id`, `context.name_root`
  and `brand.check_prefix`. A project's run can read neither the hub's variables
  nor its configuration before it has a role, so the hub's CI holds each literal
  to the configuration instead.
- **The hub is this repository.** `platform.hub` is set, and its `repository` is
  the repository the check runs in.

### The site plans

The hub plans every site with its candidate too, as the site's plan role. The
site plan roles trust the hub's pull requests for this
([spec 6.5](superpowers/specs/2026-11-22-hub-split-design.md#65-upgrades-and-rollout),
[6.6](superpowers/specs/2026-11-22-hub-split-design.md#66-role-trust)), so a
change to the configuration, or a Jaws upgrade, shows its effect on each site
before it merges. A site still applies on its own next release, through
`site-deploy` at `@live`. The bot, research and Databricks projects are planned
the same way, each as its plan role, and applied by hand.

### The caller

`platform-ci.yml` takes the input `app-client-id` and the secret
`app-private-key`, both optional: the platform's comments App, which posts the
plan comments. Without them, `github-actions` posts. The caller grants
`contents: read`, `id-token: write` (the plan roles) and `pull-requests: write`
(the comments). It passes no identity: the jobs read it from the candidate. A
hub's caller, with placeholder values:

```yaml
name: CI
on:
  pull_request:
    types: [opened, synchronize, reopened]
concurrency:
  group: ci-${{ github.event.pull_request.number }}
  cancel-in-progress: true
permissions: {}
jobs:
  ci:
    permissions:
      contents: read
      id-token: write
      pull-requests: write
    uses: Jaws-Platform/jaws/.github/workflows/platform-ci.yml@vX.Y.Z
    with:
      app-client-id: Iv23liEXAMPLE0000000
    secrets:
      app-private-key: ${{ secrets.COMMENTS_APP_PRIVATE_KEY }}
```

Its `@vX.Y.Z` is one of the pins the check holds to the `Dockerfile`'s tag.

## Releases, current and live

### `platform-release.yml`: the jobs

The hub's release caller calls `platform-release.yml` on each push to `main`.
A release stays gated, as `jaws`'s is
([spec 6.4](superpowers/specs/2026-11-22-hub-split-design.md#64-workflows)):
merges to `main` collect in a Release Please PR, and merging that PR is the
deliberate, reviewed act that releases. Every other push runs Release Please
alone. A release runs these jobs, each reported as `<caller job> / <name>`,
where `<tag>` is the release's tag:

| Job | Name | Needs | What it does |
|---|---|---|---|
| `release-please` | `Release Please` | | opens or updates the release PR with the release App's token, and releases when it merges |
| `image` | `Build the platform image (<tag>)` | `release-please` | builds the release commit and pushes it as `sha-<commit>`, as the `infra` apply role |
| `apply` | `Terraform apply (<tag>)` | `image` | applies the foundation with that build, as the `infra` apply role |
| `current` | `Move current to <tag>` | `image`, `apply` | moves the hub image's `current` tag to the build, as the `infra` apply role |
| `live` | `Move live to <tag>` | `image`, `current` | moves the `live` branch to the release commit, with the mover App's token |
| `monitoring-apply` | `Monitoring apply (<tag>)` | `image`, `apply`, `live` | applies monitoring with the build, after the moves, once the configuration has a monitoring section, as the `monitoring` apply role |

Every job but `release-please` and `live` runs in the hub's `prod`
environment. `live` takes no AWS role, so it enters none.

### The build and its tags

The `image` job checks out the release's tag and builds its `Dockerfile` as a
pull request's candidate is built. `platform-base` reads the pinned Jaws base
and checks that ECR Public still has it, and `platform-build` builds it with
the labels that name the base and the release commit. The job pushes the build
as `<account-id>.dkr.ecr.us-east-1.amazonaws.com/<platform-image>:sha-<commit>`,
a tag that never moves ([the tags](#the-images-tags-and-one-build-per-run)). It
also loads the build on the runner, to read offline whether its configuration
has a monitoring section (`config env --monitoring`), which `monitoring-apply`
waits for.

Every later job takes the build by the digest the `image` job outputs, never
by a tag. That digest is the one ECR has for `sha-<commit>`: a re-run's lookup
finds it, and after a push the job reads it back by the tag. buildx reports a
digest for the push too, but for a build it both loads and pushes, that may be
the loaded manifest's. So the job uses ECR's, and warns, naming both, when
they differ. `apply` and `monitoring-apply` pass the digest to
`platform-image` as `digest`, so they apply the release's configuration while
`current` still names the last release's build. `platform-image` takes `current` when it's
given no digest, so each job that runs or moves the build first stops if the
`image` job's `digest` came out empty, naming the output. The two moves check
its `commit` the same way.

### When `current` and `live` move

`current` moves once the foundation's apply succeeds, and never waits for
monitoring's (ruling 7). The spec's reason for the timing is "the moment the
foundation has created any roles the new configuration names". Monitoring is
applied last, after `live`, once the foundation's apply has succeeded, whatever
the moves did: a failed move doesn't hold it back, and a failed monitoring
apply holds back nothing, as it holds back nothing of `jaws`'s own release. A
failed foundation apply moves nothing: `current`, `live` and `monitoring-apply`
are skipped.

`current` moves first, then `live`. In the seconds between, a project runs the
new build with the old workflow files, never the reverse. `platform-move`
moves both:

- **`current`.** It reads the build's manifest with `aws ecr batch-get-image`,
  then puts it back under the tag `current` with `aws ecr put-image`, by digest.
  When `current` already names the build, as on a re-run, nothing moves and the
  job passes. The step summary says what `current` names:
  "`current` is `<repository>@<digest>` (`sha-<commit>`)".
- **`live`.** It updates the `live` branch through the Git refs API with the
  mover App's token, as a fast-forward only, and the hub's first release
  creates it. A move GitHub refuses, such as one that isn't a fast-forward,
  stops the job, naming `live` and the commit.

### The `live` ruleset and the mover App

Projects call the hub's workflows at `@live`, so `live` decides which workflow
files they run. The hub protects it with a ruleset that restricts updates and
deletions and blocks force pushes. Its only bypass actor is the hub's mover App
(ruling 8): an App with *Contents* and *Workflows* write and *Metadata* read,
installed only on the hub. With *Workflows* write, a move is never refused
across commits that change `.github/workflows/`.

The release App is no bypass actor. It opens the release PR and releases, and
never moves `live`. The `live` job mints the mover App's token from
`live-app-client-id` and the secret `live-app-private-key`, and from nothing
else, and `platform-move` reads the token from its `token` input only.

### When to release

Merge the release PR while the monitoring node runs. With the schedule in
[monitoring](monitoring.md#the-schedule), that is between 08:00 and 24:00 MT.
The node is stopped from 00:00 to 08:00, and a release in that window replaces
it: its monitoring apply reads the stopped node's released public address as a
change.

### Re-running a failed job

A failed job is re-run from the run's page, with "Re-run failed jobs". The
later jobs keep the `image` job's outputs, so a re-run applies and moves the
same build. A re-run of the `image` job finds the build its first attempt
pushed, `sha-<commit>`, and pulls it in place of a second build: the tag never
moves, so a second push would fail. Don't re-run all the jobs: Release Please
would run again, find nothing left to release, and every later job would be
skipped.

The jobs that change something each hold the concurrency group
`platform-release`, as the rollback's job does, and never cancel one in
progress. GitHub runs one job of a group at a time and keeps one pending, so
two of one release's jobs ready together would wait on each other, and a third
could cancel one. Their needs run them in turn instead: `image`, `apply`,
`current`, `live`, then `monitoring-apply`. Across runs the group can still
cancel: when a release and a rollback, or two releases, overlap, a waiting job
can be cancelled rather than failed. Re-run it the same way, or run the
rollback again.

### The caller

`platform-release.yml` takes the identity (`platform-image`, `account-id` and
`name-root`) and `live-app-client-id`, the mover App's client ID, all required.
Its secrets, all required, are `RELEASE_BOT_CLIENT_ID` and
`RELEASE_BOT_PRIVATE_KEY`, the release App's, for Release Please, and
`live-app-private-key`, the mover App's. The caller grants `contents: read` and
`id-token: write`. The release App's token does Release Please's writes, and a
called job can't ask for more than its caller grants.

The caller holds no `platform-release` group: a caller holding the group of a
job it calls would be cancelled as a deadlock. Neither workflow sets a group
at its top either. Every push to `main` runs the release for Release Please, so
a group there would let a push cancel a pending release or rollback.

A hub's caller, with placeholder values:

```yaml
name: Release
on:
  push:
    branches: [main]
permissions: {}
jobs:
  release:
    permissions:
      contents: read
      id-token: write
    uses: Jaws-Platform/jaws/.github/workflows/platform-release.yml@vX.Y.Z
    with:
      platform-image: jaws-platform
      account-id: "123456789012"
      name-root: jaws
      live-app-client-id: Iv23liEXAMPLE0000001
    secrets:
      RELEASE_BOT_CLIENT_ID: ${{ secrets.RELEASE_BOT_CLIENT_ID }}
      RELEASE_BOT_PRIVATE_KEY: ${{ secrets.RELEASE_BOT_PRIVATE_KEY }}
      live-app-private-key: ${{ secrets.DEPLOYMENTS_APP_PRIVATE_KEY }}
```

## Rolling back

### `platform-rollback.yml`

Roll back when a release broke something and its fix can't follow quickly.
The hub's caller runs `platform-rollback.yml` by hand, with the release commit
to go back to. Its one job, `rollback` (`Roll back to <commit>`), runs in `prod`
as the `infra` apply role, and holds the `platform-release` group, so it never
runs beside a release's job.

It moves both, together (ruling 9), so the hub's workflow files and its image
stay at one Jaws release
([spec 6.4](superpowers/specs/2026-11-22-hub-split-design.md#64-workflows):
"the hub's workflow files and its image change together"):

1. `live`, to the commit, by force, since it moves back;
2. then `current`, to that commit's kept build.

That is ruling 7's order for a move backward. In the seconds between, a
project runs the newer build with the older workflow files, never an older
build with newer workflow files. The job mints the mover App's token before
either move. So a key or client ID that's wrong, an App that isn't installed,
or a ruleset that refuses the App stops the job before `current` moves.
Whatever stops it after `live` has moved leaves that same safe pair: run the
rollback again.

It applies nothing. The foundation and monitoring stay as the release being
rolled back applied them. The runs that take `current`, such as the sweep and
the by-hand applies, and every project's next run at `@live`, run the older
build from their next start. To undo what a release applied, release a fix: the
next release moves `current` and `live` forward again, and `live` by a
fast-forward from the rolled-back commit.

Before it moves anything, the job stops on:

- a `commit` that isn't a full SHA, 40 lowercase hex digits;
- a commit that isn't on `main`: "`<commit>` is not on main";
- a commit whose build is gone. The hub image keeps the newest ten `sha-`
  builds, so a rollback reaches the last ten releases: "no build of `<commit>`
  is kept: the newest ten are; roll back to one of them, or release a fix".

### The caller

`platform-rollback.yml` takes the identity, `commit` and `live-app-client-id`,
all required, and the secret `live-app-private-key` only: no release App
secret. Its caller grants the same as the release's, `contents: read` and
`id-token: write`, and holds no `platform-release` group either. A hub's
caller, with placeholder values:

```yaml
name: Roll back
on:
  workflow_dispatch:
    inputs:
      commit:
        description: The release commit to roll back to, its full SHA
        required: true
        type: string
permissions: {}
jobs:
  rollback:
    permissions:
      contents: read
      id-token: write
    uses: Jaws-Platform/jaws/.github/workflows/platform-rollback.yml@vX.Y.Z
    with:
      platform-image: jaws-platform
      account-id: "123456789012"
      name-root: jaws
      commit: ${{ inputs.commit }}
      live-app-client-id: Iv23liEXAMPLE0000001
    secrets:
      live-app-private-key: ${{ secrets.DEPLOYMENTS_APP_PRIVATE_KEY }}
```

## By-hand applies and the sweep

Three more workflows run the hub's image outside a release. Each takes the
identity (`platform-image`, `account-id` and `name-root`, all required), runs
its one job in the hub's `prod` environment, and runs the build the hub image's
`current` tag names: they pass `platform-image` no digest and no artifact, so a
run resolves `current` to a digest once, at its start
([spec 6.4](superpowers/specs/2026-11-22-hub-split-design.md#64-workflows)).
After a rollback, they run the older build from their next start. Their caller
grants `contents: read` and `id-token: write`.

| Workflow | Who runs it | Role | What it does |
|---|---|---|---|
| `platform-bot-apply.yml` | the hub's by-hand caller, with `project`, `destroy` and `consumer-ref` | the project's `apply` role | applies a bot or research project's stack, or destroys it with `destroy` |
| `platform-databricks-apply.yml` | the hub's by-hand caller, with `project` and `action` | the project's `apply` role | `apply`, `destroy` or `doctor` for a Databricks project |
| `platform-sweep.yml` | the hub's schedule and dispatch | the `data-access` `apply` role | `platform apply data-access`: plans, then applies what the plan found |

Run a bot apply after reading the bot plan comment and while the bot is idle: a
change to the instance's AMI, type or user data replaces the instance and ends
the game in progress.

Both applies refuse, before any role is assumed, the platform's own stacks
(`infra`, `monitoring` and `data-access`). They then look the project up in the
build's configuration, offline, and refuse one that isn't a bot or research
project (the bot apply) or a Databricks project (the Databricks apply). The
project's repository comes from that line, and its `jaws.yaml` is read from
there, from its default branch or, for the bot apply, from `consumer-ref`. A
file that names another project stops the run. The Databricks apply refuses an
`action` other than `apply`, `destroy` and `doctor`. Each takes a lock per
project, `bot-apply-<project>` and `databricks-apply-<project>`, and never
cancels a run in progress.

The sweep runs from `main` only, and its runs queue in `data-access-sweep`
without cancelling one another. The hub's sweep starts when `jaws`'s own
stops (plan 07), so exactly one runs.

A hub's caller, with placeholder values:

```yaml
name: Bot apply
on:
  workflow_dispatch:
    inputs:
      project:
        required: true
        type: string
permissions: {}
jobs:
  apply:
    permissions:
      contents: read
      id-token: write
    uses: Jaws-Platform/jaws/.github/workflows/platform-bot-apply.yml@vX.Y.Z
    with:
      platform-image: jaws-platform
      account-id: "123456789012"
      name-root: jaws
      project: ${{ inputs.project }}
```
