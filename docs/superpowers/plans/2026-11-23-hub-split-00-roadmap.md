# Jaws as a product, step 1: roadmap

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md)

Step 1 is too big for one plan. It touches the CLI, the stacks, the image,
the workflows, a new organization with three repositories, seven project
repositories and the conventions documents. It is split into seven plans.
Each plan merges and works on its own.

The plans are written one at a time, as the monitoring plans were. Each
plan is written once the plans it depends on have merged, from the code as
it stands then, because it builds on files and names those plans create.
Plans 01–06 are written so far.

| # | Plan | Repository | Depends on | Spec sections | Status |
|---|---|---|---|---|---|
| 01 | [Product settings](2026-11-23-hub-split-01-product-settings.md): the release's own pins (`src/jaws/product.yaml`); product defaults for everything a platform needn't set; product tests on a neutral platform configuration; checks of the owner's configuration in `tests/platform/` | `jaws` | none | 6.1, 6.2 | merged in #314 and #318 |
| 02 | [White-label hooks](2026-11-23-hub-split-02-white-label.md): the brand section (name, mark, check-name prefix); the platform's own tags (`context.tags`); `ManagedBy` checked against the configured value; `name_root` drives the monitoring secrets, the Databricks defaults and the platform's own `Project`; the bot image's engine labels under the platform's zone; hands plan 05 the `check-prefix` input (`jaws config env --brand`) and plan 06 the hub's `brand` (its `SECTION_FILES` entry and README row) | `jaws` | 01 | 6.7 | merged in #324 |
| 03 | [Platform stacks as product stacks](2026-11-23-hub-split-03-platform-stacks.md): the foundation, monitoring and data access read the configuration from the image; the hub's identity and the trust list come from the configuration (both repositories during the move); the hub image's ECR repository; site plan roles trust the hub | `jaws` | 01 | 6.1, 6.6, 6.10 (step 3) | merged in #316; its upstream half shipped as Jaws-Platform/terraform-aws-jaws-ci v0.5.0 (PRs #24, #26, release #25) |
| 04 | Images and publishing: the generic image, with no configuration inside; `release-infra/` (the ECR Public repository and its push role, scope `publishing`); ship the platform stacks in the image (`/opt/jaws/stacks/<name>`, without `backend/`), and the datasets beside the configuration (the image's datasets directory, `/etc/jaws/datasets`, must contain `README.md`, or the foundation refuses to plan while Databricks is ready); releases push the generic image to ECR Public, and keep pushing the configuration-baked `jaws-cli` image until cleanup | `jaws` | 01, 03 | 6.3, 6.8 | merged in #317 |
| 05 | Workflows for the hub: project-facing workflows take the hub image and the platform's identity, staying compatible with today's callers; the hub-facing workflows (plan everything including sites; release: build, apply, move `current` and `live`; Bot and Databricks apply; the data-access sweep; the upgrade PR; the pin-agreement check); the hub image's tags (`current`'s mutability, the commit tags' lifecycle), and the hub's backends from `state`; each run pinned to one image digest | `jaws` | 02, 03, 04 | 6.4, 6.5 | merged in #323, released in v0.82.0 |
| 06 | The hub: JWall-Engineering's `.github`, `jwall-engineering-branding` and `platform`, holding the configuration split from `jaws`, `datasets/`, the `Dockerfile`, the caller workflows, `owner/` with its guards, the scopes and the conventions. `tests/platform/` moves here | `JWall-Engineering/*` | 05 released | 6.1, 6.9, 6.12, 7 | done: JWall-Engineering/platform (released v0.1.0 and v0.2.0, tags only; the freeze began on 2026-11-27 when the hub's configuration PR, #6, merged). Carried over to the rows below, and kept for the record. From plan 04: the hub's `Dockerfile` is the `jaws-cli` stage on the public image; the retention risk (ECR Public keeps the newest ten versions, so a hub more than ten releases behind can't build), with two remedies to choose between: an upgrade PR on every Jaws release, or mirroring the pinned base image into the hub's own ECR repository (plan 04, "For plan 06"); `tests/platform/test_release_infra.py` stays in `jaws` when `tests/platform/` moves, because it checks a `jaws` folder. From plan 05: the hub's callers (`docs/platform-workflows.md`) spell `platform-image`, `account-id`, `name-root` and, for the site callers, `check-prefix`; the release and rollback callers spell `live-app-client-id` and pass the mover App's key; no caller sets a concurrency group named `platform-release`, and no caller of the sweep or the by-hand applies sets `data-access-sweep`, `bot-apply-<project>` or `databricks-apply-<project>`, at its top or on its job (GitHub cancels a caller that holds a called job's group as a deadlock, and `jaws`'s own `data-access.yml`, `bot-apply.yml` and `databricks-apply.yml` hold theirs at their top, so a caller modelled on them drops that block); the hub's required checks are `<caller job> / Platform check`, `Terraform plan`, `Monitoring plan` and `Data access plan`; the upgrade runs hourly |
| 07 | Migration and cleanup: the enabling release, the configuration freeze (which must allow the enabling release's one config edit, adding the hub's identity to `config/platform.yaml`; owner to confirm), the acceptance plans, the takeover, the seven project switches, the conventions documents, and the product cleanup (`config/` and owner values out, the guard widened, `jaws-cli` and the old trust retired) | `jaws`, `platform`, project repositories, `repository-template` | 06 | 6.10, 6.11 | to write after 06. From plan 06 (its "For plan 07"): the enabling release's one config edit is the hub's `platform` lines, verbatim; plan 07's acceptance counts the plans that actually ran, since a green `platform / Monitoring plan` or project plan can be a skip (Jaws v0.82.0 assumes the role with `continue-on-error` and then skips with a notice or warning), by their comments, or by confirming that no "could not assume" annotation appears, read value-free through `--json`; reconsider requiring `platform / Monitoring plan` for that reason; plan 07's first task is the hub follow-up from plan 06's final review: case-insensitive Jaws-call detection, with `*.yaml` and `.github/actions/**` (m4, m19); one interface test over every `CALLERS` entry, the hub's own included, with the required inputs passed, the hub's two calls checked against `platform-ci.yml`'s and `platform-upgrade.yml`'s interfaces, and the triggers pinned (m14, m15, m20); `REQUIRED_PLATFORM_CHECKS` tied to `platform-ci.yml`'s job names (Minor 1); the owner guard also matching `owner/` and `.github/actions/**` (Minor 4); tflint pinned (Minor 5); ruff from Jaws's lock documented under "Upgrading Jaws" (Minor 6); whether an upgrade is releasable, given that `chore(deps)` cuts no release (Minor 7); authenticated ECR Public pulls in the release's image job and the PR candidates (the 429 finding); masking the account in Jaws's `platform-ci` and `platform-role`; "sealed" widened to every caller that spells the account, and every bump commit; once the roles trust the hub, require `platform / Terraform plan`, `Monitoring plan` and `Data access plan` (`REQUIRED_PLATFORM_CHECKS`, `scripts/apply-repo-settings.sh`, and drop the PR template's expected-red line); at takeover, add the applying callers (`release.yml` and `rollback.yml` pass `live-app-client-id` as a literal and `LIVE_APP_PRIVATE_KEY`, the `prod` environment's secret), delete the hub's `tests/platform/test_freeze.py`, and open the `Organization` PR; the callers' tests hold a strict `CALLERS` list, which the applying callers must join; a switched project calls `JWall-Engineering/platform/.github/workflows/<name>.yml@live`, a site passes `app-private-key: ${{ secrets.COMMENTS_APP_PRIVATE_KEY }}`, and its checks read `<project job> / <hub job> / jwall …`; cleanup also removes `owner-access/` and `billing-export/` and the moved checks. "Projects that stay back" is settled before v1, or before a hub's second owning team (design PR #338). From plan 04: cleanup removes the `jaws-cli` stage and the release's `image` job; `tests/platform/test_release_infra.py`'s checks against `config/` become literals; the owner-values guard exempts `release-infra/`, and takes up what the public image carries (plan 04, Review Focus 5). From plan 05: remove today's mode from the project-facing workflows and the `jaws` action's `config/` steps; retire `scripts/projects.sh`, `scripts/databricks-credentials.sh` and `scripts/data-access-sweep.sh`; each switch PR updates the project's required checks, which gain a level (`<project job> / <hub job> / <prefix> plan`) |

02 and 03 can run in parallel once 01 has merged.

## Owner steps along the way

- **During plan 04:** the owner hand-off, steps 1–4, in
  [the plan](2026-11-23-hub-split-04-images.md#owner-hand-off-after-the-pr-merges)
  (the `publish` environment, applying `release-infra/`, the repository
  variables, the required check). The image is published under the registry's
  default alias: no custom alias for now (the owner's decision of 2026-11-27).
- **Before plan 06 (done):**
  - create the GitHub organization `JWall-Engineering`;
  - create its release App `jwall-engineering-releases` (plan 05's ruling 8,
    in place of spec 7's `jwall-engineering-release-bot`) and its comments
    App `jwall-engineering-comments`;
  - provide the branding artwork.

  The hub keeps its three Apps (comments, upgrades and deployments), and the
  mover App's key is `LIVE_APP_PRIVATE_KEY`, a secret of the `prod`
  environment.
- **Before plan 05's releases (plan 05, hand-off 1) (done):** keep the old pins'
  image alive. `jaws-cli` keeps only the newest `ecr.keep_release_images`
  release images, so a stale pin's image expires before plan 07's switches. The
  three sites are at v0.81.0, and D7's Dependabot bumps carry on (see "During
  plan 07"). Raising `ecr.keep_release_images` is no longer an option: H8's
  freeze forbids the config change.
- **With plan 06 (plan 05, hand-off 3) (done):** the Apps and rulesets the hub needs, in
  [the plan](2026-11-24-hub-split-05-workflows.md): the comments App
  `jwall-engineering-comments`, the upgrade App `jwall-engineering-upgrades` if
  ruling 12 is confirmed, the mover App `jwall-engineering-deployments`, the
  `live` ruleset and the `prod` environment on `platform`, which holds the mover
  App's key, and the secrets the hub's callers read.
- **During plan 07:**
  - keep the configuration freeze, from creating the hub until takeover (plan 06's
    H8: no change to `config/` or `datasets/` in either repository, except the
    enabling release's edit; pin bumps carry on; the owner's folders are applied
    only from the hub's `owner/`);
  - before the switches, install the comments App on the three site
    repositories and set `COMMENTS_APP_PRIVATE_KEY` on each (plan 06's H6);
  - D7's standing duty, until each project switches: merge its Dependabot bump
    of the pin, so the image behind the pin stays alive;
  - merge each project repository's switch PR in its own organization.

  For plan 07 (from plan 06's final review):

  - `test_the_platform_s_apps_are_spelled_once` gains Deployments' client ID;
  - D3's `Organization` PR updates `test_the_platform_keeps_its_names`.
