# Jaws as a product, step 1: the hub and the product split: design

Date: 2026-11-22. Status: draft for the owner's review. Nothing described
here exists yet.

## 1. Intent

The owner wants Jaws to be a product other companies can adopt. Today it
can't be: `Jaws-Platform/jaws` mixes the product with the owner's own
platform, so nobody else could use it, and the owner can't use it the way a
customer would.

`Jaws-Platform/jaws` is four things in one repository today:

| What | Where |
| --- | --- |
| The product: the CLI, the stacks, the reusable workflows, the image | `src/`, `stacks/`, `.github/`, `Dockerfile` |
| The owner's platform configuration: accounts, projects, guardrails, DNS, Databricks, monitoring | `config/`, `datasets/` |
| Terraform applied to the owner's account by this repository's CI | `foundation/`, `monitoring/`, `data-access/` |
| Roots only the owner applies, in the management account | `owner-access/`, `billing-export/` |

The configuration is baked into the CLI image (`COPY config /etc/jaws/config`
in the `Dockerfile`). The image lives in a private ECR repository (`jaws-cli`)
in the owner's production account. When a project calls
`Jaws-Platform/jaws/.github/workflows/site-plan.yml@v0.76.0`, that one pin
fixes both the tool's version and the owner's configuration. Every project
caller is pinned at v0.76.0 while Jaws is at v0.78.1.

**Step 1 separates them.** Afterwards the owner uses Jaws exactly as a
multi-organization customer would:

```
Jaws-Platform (the vendor)      jaws: CLI, stacks, workflows, the public image
JWall-Engineering (the hub)     platform: config, datasets, the hub image, the workflows projects call
jwallace145, Braveheart-Chess,  project repos: jaws.yaml plus a few lines calling the hub
Pi-Mathematical-Reasoning,
Prog-Strength
```

**White-label.** A company that adopts Jaws should feel it has built its own
infrastructure tool *with* Jaws, not that it runs *on* Jaws. Its project
teams see the company's name, brand, tags and resource names. Jaws shows up
only where it has to.

**Later steps**, not designed here, in no fixed order: `jaws bootstrap` (a
from-scratch setup for a brand-new customer, which also replaces the owner's
manual management-account roots); a private hub; single-organization and
single-project customers; Jaws's own AWS account.

## 2. Goals, non-goals, anti-goals

**Goals**

1. `Jaws-Platform/jaws` holds nothing of the owner's platform: no account
   IDs, project registry, DNS zone, Databricks IDs, emails, owner names or
   `jwall` branding. The one exception is the infrastructure for Jaws's own
   image (section 6.8). That is the vendor's, not the platform's.
2. A public, versioned Jaws image that anyone can pull without logging in.
   Customers pin it by tag and digest.
3. `JWall-Engineering/platform` (the hub) holds the platform configuration.
   It decides the Jaws version every project runs, and project repos name no
   Jaws version at all. Upgrading Jaws is one pull request in the hub.
4. The hub builds its own image (the Jaws image plus its configuration).
   Every run, in the hub and in every project, uses that image.
5. Everything that runs today keeps running: sites, bots, research projects,
   Databricks workspaces, datasets and data access, monitoring.
6. A hub pull request plans every project, sites included. Today sites plan
   only in their own repositories.
7. White-label hooks (section 6.7): the brand, check names, tags, name root
   and the GitHub App that posts comments come from the hub, with Jaws's as
   the defaults.

**Non-goals**

- Setting up a brand-new customer from nothing (`jaws bootstrap`).
- A private hub.
- Single-organization and single-project customers.
- Jaws's own AWS account. The production account stays shared. If real
  customers arrive, the owner moves everything else out of it, and it
  becomes Jaws's.
- Jaws-Platform's own repositories as a customer of Jaws.
- Projects choosing environments from the account registry (#294).
- Renaming the owner's resources: they keep the `jaws-` name root.
- A configurable platform region. It stays `us-east-1` in step 1
  (section 6.7).

**Anti-goals**

- Rebuilding or replacing anything stateful: dataset and records buckets,
  state, the bot instance outside a planned apply, Databricks workspaces.
  Every plan during the migration shows no changes except tag updates.
- Projects pinning their own Jaws version again.
- Any CI role gaining Identity Center or management-account access. Today's
  rule holds (`tests/test_owner_access.py`, `tests/test_billing_export.py`).
- A window where a project's CI is broken. Old pins keep working until that
  project switches.
- Owner values creeping back into the product after the split. A test
  guards against it.

## 3. How it works today (facts the design rests on)

- **Configuration loading.** `settings.py` reads `JAWS_CONFIG`, else
  `/etc/jaws/config` (baked into the image), else `./config`. The sections
  and their files are in `config/README.md`.
- **The image.** The `Dockerfile` bakes in `config/`. It installs the
  Terraform version from `config/terraform.yaml` and vendors `stacks/site`
  and `stacks/bot` with their modules and providers. The Databricks stacks
  are not in the image because of its size budget. Their workflows run the
  CLI with `uv` from a checkout of this repository.
- **The composite action** (`.github/actions/jaws/action.yml`) reads
  `config/aws.yaml` and `config/tool.yaml` at the action's own commit. It
  uses them to refuse a role in the wrong account and to find the ECR
  repository. It runs `IMAGE_TAG`, which Release Please bumps.
- **Reusable workflows projects call** (all at `@v0.76.0`):
  - `site-plan`, `site-preview`, `site-deploy`, `site-release-please`: the
    three sites under `jwallace145`.
  - `remote-task`: `braveheart`, `braveheart-selfplay` and
    `braveheart-trainer`.
  - `container-release`: `braveheart-lichess-bot`.

  `remote-task` and `container-release` run the CLI with `uv` and
  `--config .jaws-tool/config`. Role ARNs come from `jaws config env`
  (account, name root, state bucket, ECR repository).
- **Central workflows in this repository.**
  - `ci.yml`, on every pull request, plans the foundation, monitoring and
    data access, every bot and research project, and every Databricks
    project.
  - `release-please.yml`, on release, applies the foundation and monitoring,
    then builds and pushes the CLI image.
  - `bot-apply.yml` and `databricks-apply.yml` are run by hand.
  - `data-access.yml` plans on pull requests and sweeps every 15 minutes.

  `scripts/projects.sh` lists projects from `config/projects.yaml` for the
  matrices.
- **Who the roles trust.**
  - The foundation's own roles trust this repository: `jaws-infra-ci-*`, the
    monitoring and data-access roles, and every bot and research project's
    plan and apply roles. They use `foundation/context.tf`: `repository`,
    `owner_id` 359185083, `repository_id` 1420037633, plus an alias
    mechanism meant for renames and transfers.
  - Release, task and site roles trust the project's own repository,
    through the immutable OIDC subject built from the IDs in
    `config/projects.yaml`.
  - Site plan roles trust only the site's repository today.
- **Owner values hard-coded in the product**, beyond `config/`:
  - `foundation/context.tf`: repository, owner, IDs.
  - `foundation/dns.tf` and `foundation/outputs.tf`: `jwall.engineering`.
  - `src/jaws/report.py`: `PRODUCT = "Jaws"`, `PRODUCT_MARK = "🦈"`.
  - The CLI's help text: "a jwall.engineering site".
  - The `Dockerfile` label: "Provisions jwall.engineering infrastructure".
  - `src/jaws/kinds/lichess_bot/Dockerfile`: `engineering.jwall.*` labels.
  - SSM paths under `/jaws/` in the CLI.
  - The owner's name and email in `owner-access/main.tf`.
  - The docs.
- **The region.** `us-east-1` is hard-coded widely:
  - `local.region` in `foundation/context.tf` and `monitoring/config.tf`;
  - the composite action's default and `aws-region` in every workflow;
  - the `metastore_name` default in `settings.py`;
  - the constants in `databricks_names.py`.

  Some regions are fixed by AWS rather than chosen: Cost Explorer and
  Pricing (`costs.py`, `tasks.py`), and ECR Public.
- **`ManagedBy` is checked, not just stamped.** The site and bot stacks
  accept only `JAWS` (`stacks/site/variables.tf`, `stacks/bot/variables.tf`).
- **Tests read the real `config/`** (`tests/conftest.py` `CONFIG_DIR`;
  about 21 test files). The foundation's test fixtures are regenerated from
  it.
- **GitHub.** The organizations are on GitHub Free with no Enterprise. A
  private repository can share workflows only with repositories of the same
  owner. That is why the hub is public for now.

## 4. Decisions the owner made

1. **Multi-organization first.** The hub is `JWall-Engineering/platform`.
   Projects stay in their own organizations.
2. **The hub decides the version.** Projects name none.
3. **The hub is public for now.** A private hub is a later step.
4. **The hub builds its own image:** the Jaws image plus its
   configuration. Projects run that image (approach B in section 5).
5. **Jaws's public image lives in ECR Public, in the production account.**
   The owner prefers AWS to GitHub's registry. The account becomes Jaws's if
   real users arrive, so the address stays stable.
6. **Jaws's release infrastructure lives in Jaws-Platform**: the ECR Public
   repository and the one role that pushes to it. It is a folder in `jaws`
   that only the owner applies.
7. **`owner-access/` and `billing-export/` move into the hub** as folders
   only the owner applies. CI never runs them, and the rules and tests that
   keep CI away move with them. `jaws bootstrap` replaces them later.
8. **White-label,** with this line:
   - The company's, set in the hub, with Jaws's as the default:
     - the name and mark on PR comments and step summaries, and the check
       names;
     - the GitHub App that posts comments;
     - the name root of every resource and secret;
     - the `Organization` and `ManagedBy` tags, plus any tags to stamp on
       everything (new);
     - the hub image's name.
   - Jaws's, where needed:
     - the project file stays `jaws.yaml`;
     - comments keep a small "built with Jaws vX.Y.Z" line;
     - the hub image records which Jaws release it is built from.
9. **Step 1 moves the owner's platform in place.** Bootstrap is later.
10. **JWall-Engineering follows the organization conventions,** with three
    repositories: `.github`, `jwall-engineering-branding` and `platform`.
    - Only `platform` holds the platform.
    - The branding repository holds JWall Engineering's logo, avatar and
      banner. The white-labeled comments and the App logos use them.
11. **The conventions documents are updated as part of this work**
    (section 6.11).
12. **Commit scopes** are as in section 6.12.

## 5. Approaches considered

The question was how a run in a project repository gets the hub's
configuration and the Jaws version the hub chose.

- **A. Hub workflows hand the hub's configuration to Jaws's workflows.**
  Each hub workflow file pins `Jaws-Platform/jaws/...@vX.Y.Z`. Jaws's
  workflow checks out the hub's `config/` and runs the public image with it
  mounted through `JAWS_CONFIG`. It is closest to today's workflows. But
  every run reads the hub repository, and going private later means
  replacing that read.
- **B. The hub builds its own image with the configuration inside
  (chosen).** The hub's `Dockerfile` starts from the Jaws image and adds
  `config/`. Its CI pushes the result to ECR in the platform account, and
  every run pulls it.
  - What runs is one sealed artifact, as it is today. Runs never read the
    hub repository, and the project roles can already pull from that ECR.
    So most of the private hub comes for free.
  - The costs: two pins must agree (the hub workflows' `@vX.Y.Z` and the
    `Dockerfile`'s base image). A guardrail change waits for an image build.
    And every customer runs an image pipeline, which Jaws provides as a
    reusable workflow.
- **Dropped.**
  - Projects calling Jaws's workflows directly with the hub named as an
    input: each project would pin a version again.
  - A bot that writes the version into every project repository: an upgrade
    becomes one PR per project, and the drift returns whenever one sits
    unmerged.

## 6. Design

### 6.1 What lives where

**`Jaws-Platform/jaws` (the product)**

- `src/jaws/`, with every project-specific default removed.
- Every stack: `stacks/site`, `stacks/bot`, `stacks/databricks-*`, and the
  platform's own stacks: the foundation, monitoring and data access. These
  are already driven by configuration. The few hard-coded owner values move
  into the hub's configuration. They become stacks the image ships and the
  hub's CI applies, like the project stacks.
- The reusable workflows (section 6.4), the composite action, the
  `Dockerfile` for the public image, and the docs.
- Tests that run against fixture configurations, never the owner's.
- The product-owned settings that are tied to a release: the Terraform
  version and the module family pins (today in `config/terraform.yaml`).
  The image is built with them, so they belong to the release.
- The release infrastructure folder (section 6.8).

**`JWall-Engineering/platform` (the hub)**

- `config/`: the hub-owned sections (section 6.2).
- `datasets/`.
- A short `Dockerfile` (section 6.3).
- `.github/workflows/`: the project-facing workflows projects call, and
  the hub's own CI. Each file is a few lines that call Jaws's reusable
  workflows.
- `owner/owner-access/` and `owner/billing-export/`, moved unchanged
  (section 6.9).
- A README for project teams, which replaces `docs/consumer-note.md`'s role.
- It follows the owner's repository and organization conventions
  (`~/Projects/Common/Repository/`). The conventions documents stay where
  they are.

The organization also has the two repositories every organization gets
under the conventions:

- `.github`: the profile, listing every repository and App.
- `jwall-engineering-branding`: the brand's published assets.

**Project repositories**

- `jaws.yaml`, unchanged.
- Callers of the hub's project-facing workflows, at `@live` (section 6.4).

### 6.2 Splitting the configuration

The rule:

- A value the platform's owner chooses, or that identifies their accounts,
  organizations, people or brand, belongs to the hub.
- A value tied to how a Jaws release works is a product default. The hub
  may override it only where a platform has a real reason to.

Section by section, as a starting point. The builder settles the rest by
the rule.

| Today | Goes to |
| --- | --- |
| `aws` (accounts, `primary`, `admin_role_arn`) | hub |
| `projects` | hub |
| `terraform.version`, `library.families` | product (the image is built with them) |
| `terraform.lock_timeout`, `plan_timeout` | product defaults |
| `state` (bucket, region, key template) | hub |
| `tool` (log level and format), `plan.comment_max_bytes` | product defaults |
| `context` (`name_root`, `organization`, `owner`, `managed_by`) | hub, under the new white-label section (6.7) |
| `ecr` (`jaws-cli`) | replaced by the hub image's repository (6.3) |
| `bot` (zones, AMI pins, records prefix) | hub. `health_log_pattern` and `health_seconds` are lichess-bot defaults the hub may override |
| `tasks` (toolchain, images, limits, cost cap) | hub: these are the central guardrails |
| `databricks`, `monitoring` | hub |
| `dns` | hub |
| `sync` (cache headers) | product defaults |

The hub's CI validates its configuration inside the image it just built.
That way a configuration the pinned release can't read fails the pull
request, before anything merges. Each Jaws release's notes list any
configuration change it requires.

### 6.3 The images

**Jaws's image (the product):**

- Generic: no configuration inside.
- Published by `jaws`'s release workflow to
  `public.ecr.aws/<alias>/jaws:vX.Y.Z`, with the role from section 6.8.
- ECR Public keeps the newest `JAWS_PUBLIC_IMAGE_KEEP` versions (default 10)
  until v1.
- `jaws`'s CI keeps the build, offline smoke test and size budget it has
  today.

**The hub's image:**

```dockerfile
FROM public.ecr.aws/<alias>/jaws:v0.79.0@sha256:<digest>
COPY config/ /etc/jaws/config/
COPY datasets/ /etc/jaws/datasets/
```

- Labels record the Jaws release and digest it is built from, and the hub
  commit.
- It is pushed to a new private ECR repository in the platform account,
  named from the hub's configuration (for example `jaws-platform`). It is
  not `jaws-cli`, so old pins keep working until the last project switches.
  `jaws-cli` is retired after that.
- Each build is tagged with the hub commit. A `current` tag points at the
  build that is live.
- A run resolves `current` to a digest once, at its start, and uses that
  digest for every step, so a merge mid-run can't mix two configurations.
  The comment footer names the digest's hub commit.
- Rolling back means pointing `current` at an earlier build: a hub
  workflow, run by hand.
- A hub pull request builds a candidate image from the PR's configuration
  and Jaws pin. Every plan in that PR runs with the candidate.

### 6.4 Workflows

**Jaws's reusable workflows** come in two groups:

- **Project-facing:** `site-plan`, `site-preview`, `site-deploy`,
  `site-release-please`, `remote-task`, `container-release`.
  - They take the hub image's repository and the platform's identity as
    inputs: the account ID and the name root, which a run needs to build its
    role ARN before it can pull anything.
  - They stop reading `config/` from a Jaws checkout.
- **Hub-facing:**
  - hub CI: validate, then plan the foundation, monitoring, data access,
    every bot and research project, every Databricks project, and every
    site;
  - hub release: build and push the image, apply the foundation and
    monitoring, then move `current` and `live`;
  - Bot apply and Databricks apply, by hand;
  - the data-access sweep;
  - the version bump (below).

**The hub's workflow files** are callers. Each pins
`Jaws-Platform/jaws/.github/workflows/<name>.yml@vX.Y.Z` and passes the
hub's identity and image. Projects call the project-facing ones:
`JWall-Engineering/platform/.github/workflows/site-plan.yml@live`.

- The calls nest three levels deep: project, hub, Jaws. Each caller grants
  the permissions the next level needs (`id-token: write`,
  `pull-requests: write`).

**Releases stay gated, as today.** Today nothing reaches AWS without a
human merging a Release Please pull request. The hub keeps that rule.

- Merges to the hub's `main` collect in a release PR.
- Merging the release PR:
  1. builds the image;
  2. applies the foundation, then monitoring;
  3. moves the image's `current` tag;
  4. moves a `live` branch, which only the release job may update, to the
     release commit.
- Projects call the hub at `@live`, not `@main`. So the hub's workflow
  files and its image change together, at the moment the foundation has
  created any roles the new configuration names.
- The data-access sweep and the by-hand applies use `current`.

**One version, two pins.**

- The hub's workflow files and its `Dockerfile` name the same Jaws release.
  A check in the hub's CI fails any PR where they disagree.
- An upgrade is one PR that bumps them all. A small scheduled hub workflow,
  provided by Jaws, opens it when a new Jaws release appears. Dependabot
  would split the image and workflow bumps into separate PRs.

**Runs that use `uv` from source.** `container-release` needs Docker on the
runner, and the Databricks stacks aren't in the image. These runs still need
the product source at exactly the pinned version, and configuration only
from the hub image. The builder chooses how: copy `/etc/jaws/config` out of
the pulled image, run inside the image, or move the Databricks stacks into
the image.

**Comments.** The hub's own GitHub App posts them, under JWall
Engineering's name and avatar.

- It is a new App, `jwall-engineering-comments`, owned by the
  organization, following the organization conventions: one App per
  purpose, owned by the organization.
- `jaws-platform-comments` stays Jaws-Platform's.
- A caller in another organization can't read the hub's secrets. So each
  onboarded owner installs the App and holds its key: as organization
  secrets in an organization, and as repository secrets under the
  `jwallace145` account.
- Comments fall back to `github-actions` when no App is configured, as
  today.

### 6.5 Upgrades and rollout

- A Jaws upgrade is a hub PR. Its plans run with the candidate image for
  every stack and every project, so the reviewer sees what the upgrade
  changes everywhere before merging.
- The hub's release applies the foundation and monitoring.
- Bots, research projects and Databricks workspaces are applied by hand
  from the hub, as they are from `jaws` today.
- Sites apply on their own next release, through `site-deploy` at `@live`.
- A guardrail change is one hub PR. Today it is a config PR, a release,
  then a pin bump in the project (`docs/research-projects.md`).
- Planning sites from the hub is new. The site plan roles gain trust for
  the hub's pull requests.

### 6.6 Role trust

- Every role that trusts `Jaws-Platform/jaws` today moves to trusting
  `JWall-Engineering/platform`:
  - `jaws-infra-ci-*`;
  - the monitoring and data-access roles;
  - the bot and research projects' plan and apply roles.
- The hub repository's identity (owner, name and the two numeric IDs)
  moves from `foundation/context.tf` into the hub's configuration.
- During the move these roles trust both repositories. The trust on
  `Jaws-Platform/jaws` is dropped once the hub has run a release. The
  existing alias mechanism assumes the same repository name under another
  owner, so it needs generalizing. The builder decides how.
- Site plan roles also gain trust for the hub (6.5).
- Release, task and site apply roles keep trusting only the project's own
  repository.
- No role gains Identity Center or management-account access.

### 6.7 White-label

A new hub configuration section (the builder names it, for example
`brand`) holds:

- **Name and mark** for comments and step summaries. They replace
  `PRODUCT` and `PRODUCT_MARK` in `src/jaws/report.py`. The mark can be an
  emoji, as Jaws's is, or an image at one of the branding repository's
  published paths.
- **A check-name prefix** for the workflows' job names (job names accept
  inputs).
- **`name_root`**, already configuration. It drives every name, including
  the SSM paths that are hard-coded under `/jaws/` today.
- **`Organization`** for the platform's own stacks. Projects keep deriving
  theirs from their GitHub owner.
- **`ManagedBy`**, already `context.managed_by`. The site and bot stacks
  check that it equals `JAWS`. That check becomes a check that it equals
  the configured value.
- **Extra tags** stamped on everything. A project file can't set or
  override them, like `Organization` and `ManagedBy` today.

Jaws keeps:

- the project file name `jaws.yaml`;
- a "built with Jaws vX.Y.Z" line in the comment footer;
- the hub image's labels naming its Jaws release.

Things no project team sees stay Jaws's: the CLI's name and the image's
internal paths (`/opt/jaws`, `/etc/jaws`).

User branding baked into the product becomes neutral. One example is the
bot image's `engineering.jwall.*` labels.

**The region stays `us-east-1` in step 1,** as a product constant.

- Making it a hub setting means threading it through every stack and
  workflow. That gains the owner nothing, since the owner's platform is in
  `us-east-1`.
- Regions AWS fixes (Cost Explorer, Pricing, ECR Public) stay constants
  either way.
- A configurable region comes in a later step, for customers elsewhere.

The owner's hub:

- sets JWall Engineering's name, mark and app;
- keeps `name_root: jaws`, since renaming means rebuilding;
- keeps `ManagedBy: JAWS` through step 1, so no switch PR shows tag
  changes. Changing it later is its own rollout. Every resource is retagged
  in place: sites on their next deploy, bots on their next Bot apply.

### 6.8 Jaws's release infrastructure (the vendor's)

- A folder in `jaws` (for example `release-infra/`) that only the owner
  applies, in the production account. It follows the same pattern and
  guards as `owner-access/`. It holds:
  - the ECR Public repository `jaws`;
  - one role, trusted only for `Jaws-Platform/jaws` release runs, that may
    push to that repository and prune it, and nothing else (the owner's
    decision of 2026-11-23).
- Its state goes in the platform's state bucket, under its own prefix.
- The role's ARN is a repository variable in `jaws`. No account ID appears
  in code outside this folder.
- After the split, this role is `jaws`'s only access to AWS. Its plans and
  stack tests already run against mock providers.
- A custom registry alias (for example `jaws`) is optional. The owner
  decided on 2026-11-27 not to request one for now, so the image is published
  under the registry's default alias. If one is requested later, AWS reviews
  it within a few days, and the default alias keeps working beside it.

### 6.9 The owner's folders in the hub

- `owner/owner-access/` and `owner/billing-export/` move unchanged. Their
  state stays in the management account's owner-only bucket.
- The guards move into the hub's CI: no CI role, workflow or state prefix
  names them, and no CI role holds Identity Center permissions.
- `admin_role_arn` stays in the hub's `aws` configuration, for the
  hardened bucket policies.
- `jaws bootstrap` replaces both folders in a later step.

### 6.10 Migration, in place

The builder plans the steps. These constraints and this order hold:

1. **A backward-compatible Jaws release.** It includes:
   - the CLI's configuration from the hub image;
   - the workflows' new inputs;
   - the white-label hooks with Jaws's defaults;
   - the platform stacks made generic;
   - the public image in ECR Public.

   Today's callers are unaffected.
2. **The owner creates the hub** (section 7).
3. **An enabling `jaws` release,** still applied by `jaws`, as today.
   - It adds the hub's trust to the roles in 6.6.
   - It creates the hub image's ECR repository, with its push and pull
     grants.
   - Its plan has real changes, by design. The hub can't assume any role
     before this release.
4. **The hub's configuration** is today's, split per 6.2. The hub's image
   builds, and the hub's CI plans every existing stack and project.
   - Every one of those plans shows no changes apart from tag updates
     (`Repository`, `Organization`).
   - This is the acceptance test, and the gate for takeover.
5. **The hub takes over:**
   - releases apply the foundation and monitoring;
   - the data-access sweep;
   - Bot apply and Databricks apply.

   The same workflows in `jaws` are switched off at the same time, so
   exactly one sweeper runs.
6. **Projects switch one at a time** to the hub at `@live`: the three
   sites, `braveheart`, `braveheart-selfplay`, `braveheart-trainer` and
   `braveheart-lichess-bot`.
   - Each switch's PR plan shows no changes.
   - Old pins keep their baked-in configuration, so a hub change doesn't
     reach a project until it switches. Switch soon after the hub goes live.
7. **Clean up the product:**
   - `config/`, the owner's folders and every owner value leave `jaws`;
   - tests use fixture configurations;
   - a test fails on owner values in product sources (account IDs, `jwall`,
     owner names and emails);
   - `jaws-cli` and the trust on `Jaws-Platform/jaws` are retired.

**The configuration is frozen from step 2 until takeover (step 5).**

- Until then there are two copies of it, and `jaws`'s copy is still the
  one its releases apply.
- No change goes into `config/` or `datasets/` in either repository during
  that window. So the copies can't drift, and the acceptance plans stay
  meaningful.
- In-flight changes, such as setting `monitoring.cost.protect_raw: true`,
  land before step 2 or after step 5.
- Keep the window short.

The foundation's state key doesn't change. The hub applies the same root
module, shipped in the image, against the same backend, so no state moves.
Any change of resource address needs `moved` blocks.

### 6.11 The conventions documents

Both documents in `jwallace145/repository-template`
(`~/Projects/Common/Repository/`) describe how a project uses Jaws, and
this work makes parts of them wrong. Rewrite them in the same change set:

- **`organization-conventions.md`, "Cloud infrastructure with Jaws":**
  - Onboarding is a change to the hub's `config/projects.yaml`, not
    `jaws`'s.
  - The MUST that no organization keeps its own Terraform gets one
    exception: the hub's `owner/` folders, until `jaws bootstrap` replaces
    them.
- **`organization-conventions.md`, the checklist and the Apps:**
  organizations that use Jaws install the hub's comments App
  (`jwall-engineering-comments`), not `jaws-platform-comments`.
- **`repository-conventions.md`, "Cloud infrastructure with Jaws":**
  - A repository calls the hub's workflows at `@live` and names no Jaws
    version. Dependabot doesn't bump anything.
  - Whatever the workflows end up needing from a project repository
    (variables, secrets) is documented there. If the hub derives role ARNs,
    the repository variables that hold them go away.
- What they say about `jaws.yaml` stays as it is.

### 6.12 Commit scopes

- **`platform`:** `config` (accounts, projects, guardrails, brand),
  `datasets`, `image` (the `Dockerfile`), `workflows`, `owner` (the
  `owner/` folders), `repo`, `deps` (which also covers Jaws upgrades),
  `release`.
- **`jaws`:** a new `publishing` scope for the release infrastructure
  folder. At cleanup, `config` and `datasets` are retired, and `access` and
  `monitoring` drop the folders that moved out.

## 7. Owner hand-offs

These need the owner's credentials or the GitHub and AWS consoles.

- Create the GitHub organization `JWall-Engineering`.
- Set the organization up by its conventions' checklist:
  - the release bot `jwall-engineering-release-bot`, owned by the
    organization, with its organization secrets;
  - `jwall-engineering-branding`, with the artwork. The organization
    picture and the App logos are set from its avatar.
  - `.github`, with the profile.
- Create `platform` and apply the repository conventions, including the
  `main` ruleset and the `prod` environment.
- Create the GitHub App `jwall-engineering-comments`, owned by
  `JWall-Engineering`. Install it for every onboarded owner, and set its
  client ID and key where each owner's callers can read them (6.4).
- Apply the release infrastructure folder (6.8), and request the ECR Public
  alias.
- Merge each project repository's switch PR, in its own organization.

## 8. Left to the builder

- The classification of every configuration key, by the rule in 6.2.
- Names: configuration sections, the white-label section, the hub image
  repository, the hub's workflow files, the `live` branch.
- How the `uv`-from-source runs get their configuration (6.4).
- Whether a hub PR's candidate image is pushed under a PR tag or passed
  between jobs.
- Architectures, and the image's size budget.
- The upgrade-PR mechanism, as long as one PR bumps every pin.
- How the docs split between the product and the hub's README.
- How to generalize the trust alias mechanism (6.6).

## 9. Calls made in writing this up, for the owner to check

- The hub keeps release-gated applies. Projects call it at `@live`, a
  branch its release moves together with the image's `current` tag.
- The hub image goes to a new ECR repository, and `jaws-cli` stays until
  the last project switches.
- A run pins `current` to its digest at the start.
- The owner's folders sit under `owner/` in the hub.
- The release infrastructure's state lives in the platform's state bucket,
  under its own prefix.
- A Jaws-provided scheduled workflow opens upgrade PRs, rather than
  Dependabot.
- The "built with Jaws" footer line stays on.
- The owner's hub keeps the `jaws` name root.
- The migration's order (6.10): an enabling `jaws` release comes first.
  The hub's acceptance plans are then the gate for takeover. "No changes but
  tags" applies to those plans and to the project switches, not to the
  enabling release.
- The configuration is frozen from creating the hub until takeover.
- The region stays `us-east-1`, as a product constant, in step 1.
- The owner's hub keeps `ManagedBy: JAWS` through step 1.
- Comments come from a new `jwall-engineering-comments` App.
  `jaws-platform-comments` stays Jaws-Platform's.
- The conventions documents stay where they are, and the hub follows them.
