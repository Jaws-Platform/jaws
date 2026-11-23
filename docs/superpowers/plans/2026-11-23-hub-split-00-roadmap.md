# Jaws as a product, step 1: roadmap

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md)

Step 1 is too big for one plan. It touches the CLI, the stacks, the image,
the workflows, a new organization with three repositories, seven project
repositories and the conventions documents. It is split into seven plans.
Each plan merges and works on its own.

The plans are written one at a time, as the monitoring plans were. Each
plan is written once the plans it depends on have merged, from the code as
it stands then, because it builds on files and names those plans create.
Only plan 01 is written so far.

| # | Plan | Repository | Depends on | Spec sections | Status |
|---|---|---|---|---|---|
| 01 | [Product settings](2026-11-23-hub-split-01-product-settings.md): the release's own pins (`src/jaws/product.yaml`); product defaults for everything a platform needn't set; product tests on a neutral platform configuration; checks of the owner's configuration in `tests/platform/` | `jaws` | none | 6.1, 6.2 | written |
| 02 | White-label hooks: the brand section (name, mark, check-name prefix); extra tags; `ManagedBy` checked against the configured value; `name_root` drives SSM paths and the Databricks defaults; neutral bot image labels | `jaws` | 01 | 6.7 | to write after 01 |
| 03 | Platform stacks as product stacks: the foundation, monitoring and data access read the configuration from the image; the hub's identity and the trust list come from the configuration (both repositories during the move); the hub image's ECR repository; site plan roles trust the hub | `jaws` | 01 | 6.1, 6.6, 6.10 (step 3) | to write after 01 |
| 04 | Images and publishing: the generic image, with no configuration inside; `release-infra/` (the ECR Public repository and its push role, scope `publishing`); releases push the generic image to ECR Public, and keep pushing the configuration-baked `jaws-cli` image until cleanup | `jaws` | 01, 03 | 6.3, 6.8 | to write after 03 |
| 05 | Workflows for the hub: project-facing workflows take the hub image and the platform's identity, staying compatible with today's callers; the hub-facing workflows (plan everything including sites; release: build, apply, move `current` and `live`; Bot and Databricks apply; the data-access sweep; the upgrade PR; the pin-agreement check); each run pinned to one image digest | `jaws` | 02, 03, 04 | 6.4, 6.5 | to write after 04 |
| 06 | The hub: JWall-Engineering's `.github`, `jwall-engineering-branding` and `platform`, holding the configuration split from `jaws`, `datasets/`, the `Dockerfile`, the caller workflows, `owner/` with its guards, the scopes and the conventions. `tests/platform/` moves here | `JWall-Engineering/*` | 05 released | 6.1, 6.9, 6.12, 7 | to write after 05 |
| 07 | Migration and cleanup: the enabling release, the configuration freeze, the acceptance plans, the takeover, the seven project switches, the conventions documents, and the product cleanup (`config/` and owner values out, the guard widened, `jaws-cli` and the old trust retired) | `jaws`, `platform`, project repositories, `repository-template` | 06 | 6.10, 6.11 | to write after 06 |

02 and 03 can run in parallel once 01 has merged.

## Owner steps along the way

- **During plan 04:** apply `release-infra/` with admin credentials, then
  request the ECR Public registry alias in the console. AWS reviews requests
  within a few days, so request it as soon as the repository exists.
- **Before plan 06:**
  - create the GitHub organization `JWall-Engineering`;
  - create its release bot `jwall-engineering-release-bot` and its
    comments App `jwall-engineering-comments`;
  - provide the branding artwork.
- **During plan 07:**
  - keep the configuration freeze, from creating the hub until takeover;
  - merge each project repository's switch PR in its own organization.
