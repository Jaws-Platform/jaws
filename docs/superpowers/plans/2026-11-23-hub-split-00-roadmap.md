# Jaws as a product, step 1: roadmap

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md)

Step 1 is too big for one plan. It touches the CLI, the stacks, the image,
the workflows, a new organization with three repositories, seven project
repositories and the conventions documents. It is split into seven plans.
Each plan merges and works on its own.

The plans are written one at a time, as the monitoring plans were. Each
plan is written once the plans it depends on have merged, from the code as
it stands then, because it builds on files and names those plans create.
Plans 01–05 are written so far.

| # | Plan | Repository | Depends on | Spec sections | Status |
|---|---|---|---|---|---|
| 01 | [Product settings](2026-11-23-hub-split-01-product-settings.md): the release's own pins (`src/jaws/product.yaml`); product defaults for everything a platform needn't set; product tests on a neutral platform configuration; checks of the owner's configuration in `tests/platform/` | `jaws` | none | 6.1, 6.2 | merged in #314 and #318 |
| 02 | [White-label hooks](2026-11-23-hub-split-02-white-label.md): the brand section (name, mark, check-name prefix); the platform's own tags (`context.tags`); `ManagedBy` checked against the configured value; `name_root` drives the monitoring secrets, the Databricks defaults and the platform's own `Project`; the bot image's engine labels under the platform's zone; hands plan 05 the `check-prefix` input (`jaws config env --brand`) and plan 06 the hub's `brand` (its `SECTION_FILES` entry and README row) | `jaws` | 01 | 6.7 | merged in #324 |
| 03 | [Platform stacks as product stacks](2026-11-23-hub-split-03-platform-stacks.md): the foundation, monitoring and data access read the configuration from the image; the hub's identity and the trust list come from the configuration (both repositories during the move); the hub image's ECR repository; site plan roles trust the hub | `jaws` | 01 | 6.1, 6.6, 6.10 (step 3) | merged in #316; its upstream half shipped as Jaws-Platform/terraform-aws-jaws-ci v0.5.0 (PRs #24, #26, release #25) |
| 04 | Images and publishing: the generic image, with no configuration inside; `release-infra/` (the ECR Public repository and its push role, scope `publishing`); ship the platform stacks in the image (`/opt/jaws/stacks/<name>`, without `backend/`), and the datasets beside the configuration (the image's datasets directory, `/etc/jaws/datasets`, must contain `README.md`, or the foundation refuses to plan while Databricks is ready); releases push the generic image to ECR Public, and keep pushing the configuration-baked `jaws-cli` image until cleanup | `jaws` | 01, 03 | 6.3, 6.8 | merged in #317 |
| 05 | Workflows for the hub: project-facing workflows take the hub image and the platform's identity, staying compatible with today's callers; the hub-facing workflows (plan everything including sites; release: build, apply, move `current` and `live`; Bot and Databricks apply; the data-access sweep; the upgrade PR; the pin-agreement check); the hub image's tags (`current`'s mutability, the commit tags' lifecycle), and the hub's backends from `state`; each run pinned to one image digest | `jaws` | 02, 03, 04 | 6.4, 6.5 | in its pull request (#323) |
| 06 | The hub: JWall-Engineering's `.github`, `jwall-engineering-branding` and `platform`, holding the configuration split from `jaws`, `datasets/`, the `Dockerfile`, the caller workflows, `owner/` with its guards, the scopes and the conventions. `tests/platform/` moves here | `JWall-Engineering/*` | 05 released | 6.1, 6.9, 6.12, 7 | to write after 05. From plan 04: the hub's `Dockerfile` is the `jaws-cli` stage on the public image; the retention risk (ECR Public keeps the newest ten versions, so a hub more than ten releases behind can't build), with two remedies to choose between: an upgrade PR on every Jaws release, or mirroring the pinned base image into the hub's own ECR repository (plan 04, "For plan 06"); `tests/platform/test_release_infra.py` stays in `jaws` when `tests/platform/` moves, because it checks a `jaws` folder. From plan 05: the hub's callers (`docs/platform-workflows.md`) spell `platform-image`, `account-id`, `name-root` and, for the site callers, `check-prefix`; the release and rollback callers spell `live-app-client-id` and pass the mover App's key; no caller sets a concurrency group named `platform-release`, and no caller of the sweep or the by-hand applies sets `data-access-sweep`, `bot-apply-<project>` or `databricks-apply-<project>`, at its top or on its job (GitHub cancels a caller that holds a called job's group as a deadlock, and `jaws`'s own `data-access.yml`, `bot-apply.yml` and `databricks-apply.yml` hold theirs at their top, so a caller modelled on them drops that block); the hub's required checks are `<caller job> / Platform check`, `Terraform plan`, `Monitoring plan` and `Data access plan`; the upgrade runs hourly |
| 07 | Migration and cleanup: the enabling release, the configuration freeze (which must allow the enabling release's one config edit, adding the hub's identity to `config/platform.yaml`; owner to confirm), the acceptance plans, the takeover, the seven project switches, the conventions documents, and the product cleanup (`config/` and owner values out, the guard widened, `jaws-cli` and the old trust retired) | `jaws`, `platform`, project repositories, `repository-template` | 06 | 6.10, 6.11 | to write after 06. From plan 04: cleanup removes the `jaws-cli` stage and the release's `image` job; `tests/platform/test_release_infra.py`'s checks against `config/` become literals; the owner-values guard exempts `release-infra/`, and takes up what the public image carries (plan 04, Review Focus 5). From plan 05: remove today's mode from the project-facing workflows and the `jaws` action's `config/` steps; retire `scripts/projects.sh`, `scripts/databricks-credentials.sh` and `scripts/data-access-sweep.sh`; each switch PR updates the project's required checks, which gain a level (`<project job> / <hub job> / <prefix> plan`) |

02 and 03 can run in parallel once 01 has merged.

## Owner steps along the way

- **During plan 04:** the owner hand-off, steps 1–4, in
  [the plan](2026-11-23-hub-split-04-images.md#owner-hand-off-after-the-pr-merges)
  (the `publish` environment, applying `release-infra/`, the repository
  variables, the required check). The image is published under the registry's
  default alias: no custom alias for now (the owner's decision of 2026-11-27).
- **Before plan 06:**
  - create the GitHub organization `JWall-Engineering`;
  - create its release App `jwall-engineering-releases` (plan 05's ruling 8,
    in place of spec 7's `jwall-engineering-release-bot`) and its comments
    App `jwall-engineering-comments`;
  - provide the branding artwork.
- **Before plan 05's releases (plan 05, hand-off 1):** keep the old pins' image
  alive. Every project's pin, `@v0.76.0`, pulls `jaws-cli:v0.76.0`, and
  `jaws-cli` keeps only the newest `ecr.keep_release_images` release images, so
  at about four releases a day it expires before plan 07's switches. Raise
  `ecr.keep_release_images` in `config/tool.yaml` (a config change still allowed
  before the freeze), or merge the projects' Dependabot bumps to a recent tag.
- **With plan 06 (plan 05, hand-off 3):** the Apps and rulesets the hub needs, in
  [the plan](2026-11-24-hub-split-05-workflows.md): the comments App
  `jwall-engineering-comments`, the upgrade App `jwall-engineering-upgrades` if
  ruling 12 is confirmed, the mover App `jwall-engineering-deployments`, the
  `live` ruleset and the `prod` environment on `platform`, which holds the mover
  App's key, and the secrets the hub's callers read.
- **During plan 07:**
  - keep the configuration freeze, from creating the hub until takeover;
  - merge each project repository's switch PR in its own organization.
