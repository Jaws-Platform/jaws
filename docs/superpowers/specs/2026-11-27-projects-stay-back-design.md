# Projects that stay back on an older hub release

**Status.**
- The owner picked this approach on 2026-11-27.
- It is built as its own step before Jaws v1, or before the first hub whose projects have more than one owning team, whichever comes first (the owner's decision of 2026-11-27). Until then, one owner's projects follow `@live` together, which costs little. Nothing in plans 06 and 07 changes for it.
- It amends the hub split's spec ([2026-11-22-hub-split-design.md](2026-11-22-hub-split-design.md)) at goal 3, "upgrading Jaws is one pull request in the hub", and at section 6.4's `@live`.

## Intent

Today every project calls its hub's workflows at `@live`. So a hub release moves every project onto the new Jaws from its next run, and no project can wait.
- **For one owner with a handful of projects,** that is simple and fine.
- **For an organization with many service teams and hundreds of projects,** it does two things:
  - it puts every team on the platform team's schedule;
  - it turns each upgrade into an organization-wide wave of infrastructure changes, rolled out at once and watched.

The owner wants projects to follow their hub by default, and to be able to stay back. In the owner's words: "I just think having the ability for consumer to stay back where possible makes sense." A breaking hub release still moves every project, in the end.

**What stays, because the owner likes it:**
- A hub upgrade applies only the shared layer: the foundation and monitoring.
- Each project's own changes wait for that project's next run.
- The hub's release never waits on, or depends on, any project's success.

## Goals

1. **By default,** a project follows its hub with nothing to set: `@live`, as today.
2. **Staying back.** A project can stay on a hub release, and leave it again, from its own repository, with no hub change.
3. **New releases still reach it.** A project that stays back is offered each newer hub release as a pull request in its own repository.
4. **Compatibility.** The shared layer keeps working for every release a project may stay on, inside a stated support window.
5. **Breaking releases.** A breaking hub release says so, and raises the floor. A project below the floor fails its runs with a message naming the release to move to.
6. **Visibility.** The hub shows which projects stay back, and how far.

## Non-goals

- A version field in the configuration: "I don't think we need, like, a hub version field and a consumer version field."
- Waves the platform team schedules, such as canary projects and rings. They can come later, on top of this.
- Holding back the shared layer. It always runs the hub's newest release.

## Anti-goals

- **Silent drift:** a project far behind, with nobody knowing. That is the problem that started the hub split: every project was pinned at v0.76.0 while Jaws was at v0.78.1.
- **An upgrade held hostage:** a hub upgrade that waits on every project, or is judged by every project's success.

## Constraints

- **One run can't plan every project at scale.** A GitHub Actions workflow run can have at most 256 matrix jobs, so "the upgrade PR plans every project" (spec goal 6) can't hold at enterprise scale.
- **One shared layer per platform.** The CI roles, trust, state, data access and monitoring are applied by the hub's release.
- **Workflows and image agree.** A hub release's workflow files and its image must belong to the same release.
- **Spending.** Each hub image a support window keeps costs about $0.03 a month at today's size. The window's size sets that cost, and it is the owner's to approve.

## Approaches

- **A. Every project follows `@live`** (today's design).
  - For: one version everywhere, so there's no drift, and the shared layer supports one version. One upgrade PR shows every project's plan. A guardrail change reaches every project on its next run. Rollback is one move.
  - Against: every project moves at once, and no team can wait. A team's urgent, unrelated deploy carries the pending infrastructure changes with it. At scale, the upgrade PR outgrows one run, and one project's surprise holds up every other.
- **B. Follow by default, pin to stay back (chosen).**
  - How it works:
    - `@live` stays the default;
    - to stay back, a team replaces `@live` with a hub release tag, for example `@v1.4.0`;
    - Dependabot's `github-actions` updates then offer each newer release as a pull request in that project;
    - switching back to `@live` follows again.
  - For: the default behaves as today. A problem stays with one team, and rollouts can start with pilot projects.
  - Against:
    - the shared layer must support every release in the window, a promise Jaws has to keep and test;
    - the window's images are kept;
    - a guardrail that lives in a project's own stack waits until the project moves, although guardrails in the shared layer apply at once;
    - drift returns, but chosen, visible and bounded.
- **Dropped:**
  - every project pins, with bump PRs by default: the spec dropped this because "the drift returns whenever one sits unmerged", and that holds for every project;
  - a version field in the configuration: the owner doesn't want it;
  - waves run by the platform team: they give teams no say. They can come later, on top of B.

## Decided

- **`@live` is the default,** and stays plan 07's migration target.
- **Staying back is the project's own pin** of a hub release tag. Release Please already tags each hub release.
- **Each hub release's workflow files name that release's own image,** not `current`, so a pinned release runs the image it was built with.
  - Today the project-facing workflows resolve `current`, which is right only at `@live`.
  - This is a backward-compatible change to Jaws's project-facing workflows, for example an optional input naming the image.
- **Newer releases reach pinned projects as Dependabot pull requests** in each project, with nothing new to build.
- **A breaking hub release is a major version,** and it raises the floor.

## Left to decide when this is built

- **The support window:** its size, and whether it counts releases or time. Proposal: the releases the hub image keeps, the newest ten today.
- **The floor:** how a release declares it, and how a project below it fails. Proposal: the hub's workflow compares its caller's ref with the floor when a run starts, and fails naming the release to move to.
- **Visibility:** how the hub reports projects that stay back. A scheduled report, a check, or a table in the hub's README.
- **Testing:** how Jaws tests that the shared layer supports the window.
- **The upgrade PR's plans:** what it plans once projects can stay back. For example, only the projects at `@live`, or a sample when there are more than one run can hold.
