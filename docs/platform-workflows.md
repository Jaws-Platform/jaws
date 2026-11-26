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
and checks the ID of what it loads from there: a build with another ID is
pulled again.

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
