# Jaws as a product, plan 03: platform stacks as product stacks: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the foundation, monitoring and data access stacks generic: they read the platform's configuration and datasets where the CLI does, take their trust, tags and zone from it, and gain the hub's trust and image repository only once the configuration names a hub, so nothing in AWS changes today.

**Architecture:**
- A new `platform` section (`config/platform.yaml`) lists, in order, the repositories whose own workflows plan and apply the platform, each with its two GitHub IDs. The first is the platform's own. An optional `platform.hub` names one of them as the hub, with the private ECR repository of its image. This replaces the repository, the IDs and the alias mechanism in `foundation/context.tf`. The owner's file lists only `Jaws-Platform/jaws`. Plan 07's enabling release adds `JWall-Engineering/platform` second, and the hub.
- Upstream, `Jaws-Platform/terraform-aws-jaws-ci` 0.5.0 lets a role trust other repositories under their own IDs, and lets the ECR policies name several repositories by adding one policy per further repository. A role given one repository keeps its trust policy and its policies byte for byte.
- The foundation and monitoring read the configuration from `var.config_path`, else the image's `/etc/jaws/config`, else the repository's `config/`, as `jaws.settings.default_config_path` does. The foundation reads the `datasets/` beside it, as `jaws.access.infra_root` does. Data access reads only what `jaws access render` renders, so it already reads the CLI's configuration.
- The owner values still written in `foundation/` (the zone, its TXT record, the Repository and Owner tags, the repository's IDs) move into the configuration, unchanged.

**Tech Stack:** Terraform 1.14.7 (`terraform test` with mock providers), the `Jaws-Platform/jaws-ci/aws` and `Jaws-Platform/jaws-lichess-bot/aws` module families, terraform-docs, Python 3.13, uv, Pydantic v2, pytest.

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md), sections 6.1, 6.3, 6.6, 6.10 (step 3) and 2. Roadmap: [2026-11-23-hub-split-00-roadmap.md](2026-11-23-hub-split-00-roadmap.md), row 03.

**Where the work happens:**
- Tasks 1–2 are in `Jaws-Platform/terraform-aws-jaws-ci` (`~/Projects/Jaws-Platform/terraform-aws-jaws-ci`), one branch and PR each, from its `main`.
- Tasks 3–9 are in `jaws`, on `hub-split/03-platform-stacks`, from `main` once plan 01's PR (at least its Tasks 1–2, `src/jaws/product.yaml`) has merged. It ran from `main` at 27b02c8, with plan 01 merged as Jaws-Platform/jaws#314.
- Tasks 3–5 don't need jaws-ci 0.5.0 and can run while Tasks 1–2 are in review. Task 6 waits for the release.

## Global Constraints

- **The repository rules (`AGENTS.md` in each repository):**
  - never push to `main`: one branch, one PR;
  - each commit is one line, `type(scope): subject`, at most 100 characters, with a lowercase imperative subject and no trailing period;
  - only `Co-authored-by:` trailers may follow, after a blank line;
  - the PR title is a valid commit header, and the PR body fills every template section.
- **Scopes.** In `jaws`: `cli`, `foundation`, `monitoring`, `deps`. In `terraform-aws-jaws-ci`: `github-oidc-role`, `ci-plan-role`, `ci-apply-role`, `ci-policies`, `examples`.
- **Never touch real infrastructure.** Never run `terraform apply`, a plan against real state, or `jaws apply|publish|release|destroy`. Run only `terraform test` (mock providers), `terraform validate`, `tflint` and `scripts/test-stack-plans.sh`. CI's plan jobs, which plan with the read-only plan roles, are the only real plans.
- **Nothing in AWS changes when this plan merges.** With the owner's `config/`, the foundation, monitoring and data access plans show no changes: no new trust, no new repository, no role or policy replaced, no state address moved.
  - Every new trust or resource follows from configuration the owner's `config/` doesn't set yet: a second `platform.repositories` entry, or `platform.hub`.
  - Every value moved from code into `config/` is the same value.
  - No resource address changes, so no `moved` block is needed. If one becomes necessary, add it, and prove it with a `terraform test` run.
  - The proof: the `terraform test` runs each task names; the upstream tests in Tasks 1–2, which show one repository gives the old documents; and, at the PR, CI's `Terraform plan` and `Monitoring plan` comments, which must say merging leaves AWS alone.
- **The spec's rules this plan implements, verbatim (6.6):** "During the move these roles trust both repositories." "Site plan roles also gain trust for the hub (6.5)." "Release, task and site apply roles keep trusting only the project's own repository." "No role gains Identity Center or management-account access."
- **The hub image's repository, verbatim (6.3):** "It is pushed to a new private ECR repository in the platform account, named from the hub's configuration (for example `jaws-platform`). It is not `jaws-cli`, so old pins keep working until the last project switches."
- **The anti-goals, verbatim (2):** "Rebuilding or replacing anything stateful: dataset and records buckets, state, the bot instance outside a planned apply, Databricks workspaces." "Any CI role gaining Identity Center or management-account access. Today's rule holds (`tests/test_owner_access.py`, `tests/test_billing_export.py`)."
- **The region stays `us-east-1`,** a product constant (spec 6.7).
- **Off limits.**
  - `owner-access/` and `billing-export/` are not touched.
  - Plan 02, written in parallel, owns these; don't edit them:
    - `src/jaws/report.py`;
    - the `ManagedBy` checks in `stacks/site/variables.tf` and `stacks/bot/variables.tf`;
    - the SSM path constants, `local.secrets_prefix` in `monitoring/main.tf` included;
    - the `Project = jaws` tag.
  - The `module "context"` blocks (`foundation/context.tf:52-63`, `monitoring/config.tf:35-46`) change only where this plan says.
  - Where plans 02 and 03 both add a row (`SECTION_FILES` in `tests/test_settings.py`, the configuration tables in `config/README.md` and `README.md`), keep both rows.
- **Owner values in files.**
  - Never write an owner value outside `config/`. This plan refers to the values it moves by their current path.
  - New tests use these neutral values:
    - `Example-Hub/platform`, owner ID `10000099`, repository ID `20000099`;
    - the hub image `<name_root>-platform` (`jaws-platform`);
    - in the relabelled fixture, `Example-Org/platform`, `example-owner`, `example.com`, `_example-challenge`, `example-token`.
  - The one exception is the hub runs' `override_module` (Task 8). It repeats the account ID that `foundation/tests/foundation.tftest.hcl` already mocks, and plan 01 Task 3 neutralizes it with the rest of that file.
- **The privacy hook.** If a hook refuses to read a file because it holds the owner's email (`tests/conftest.py`, `config/databricks.yaml`, `config/projects.yaml`), stop and ask the owner to make that edit (they can run it with `!`). Never work around the hook.
- **Plan 01 Task 3 is deferred.** The tests still read the owner's `config/` through `tests.conftest.CONFIG_DIR`. When Task 3 lands, `test_a_platform_stack_holds_no_owner_value` (Task 5) moves to the neutral fixture's tests and reads `PLATFORM_CONFIG_DIR`. The neutral fixture then gets neutral values for `platform.repositories`' IDs and for `dns.txt_records`.
- **Before each PR.**
  - In `terraform-aws-jaws-ci`: `scripts/check.sh`.
  - In `jaws`: the `AGENTS.md` checklist, plus `(cd foundation && terraform test)` and `(cd data-access && terraform init -backend=false && terraform test)`.

## Review Focus

1. **The image's configuration without its datasets.** A run that finds `/etc/jaws/config` but no `/etc/jaws/datasets` would plan to remove every onboarded dataset. Expected: the plan stops and names the path. Task 4, `stops_without_the_datasets_registry`.
2. **A new repository listed first.** During the move the hub goes after `Jaws-Platform/jaws`. Adding it must only widen the trust: the first repository's subjects stay first and unchanged, and no tag moves. Task 7, `a_second_repository_is_trusted_alongside_the_first`.
3. **A hub the roles don't trust.** A `platform.hub.repository` that isn't in `platform.repositories` is refused by the CLI and by the plan, before any site plan role trusts it. Task 3, `test_a_malformed_platform_section_is_refused`, and Task 7, `refuses_a_hub_it_does_not_trust`.
4. **A hub image the apply role can't create.** `foundation/manage` manages only `<name_root>-*` repositories. Another name, or `ecr.repository`'s, must fail at validation and at plan, not in the release's apply. Task 3, `test_the_hub_image_has_its_own_repository_under_the_name_root`, and Task 8, `refuses_a_hub_image_outside_the_name_root`.
5. **Ten managed policies a role.** With a hub, the infra apply role goes from 5 to 8 policies and the monitoring apply role from 8 to 9; the other roles gain one. Every role stays within IAM's default ten. Task 8, `a_hub_keeps_every_role_within_ten_policies`.

## Rulings

Calls this plan makes where the spec is silent, each with the later plan that takes it up:

1. **Config shape.** `platform.repositories` is an ordered list of `{repository, owner_id, repository_id}`, and `platform.hub` is `{repository, image}`. A rename, a transfer and a move are all the same thing: a second entry with its own IDs. That generalizes the alias mechanism, whose aliases share one repository ID.
2. **The first repository is the platform's own.** It names the Repository tag of the foundation and monitoring, the zone's comment and the roles' descriptions.
   - So the enabling release (plan 07) adds the hub second. It only widens trust, and the hub's acceptance plans show no Repository tag change.
   - Dropping the first entry at cleanup moves the Repository tag, the zone's comment and the roles' descriptions to the hub.
3. **Upstream first.** jaws-ci 0.4.0 can't trust a second repository under its own IDs, and each ECR policy names one repository. jaws-ci 0.5.0 adds both (Tasks 1–2), as `AGENTS.md` requires for module inputs.
   - A further ECR repository gets a policy of its own, not a wider one. One `ecr/pull` naming two repositories would need a new description ("…from one repository" would be false). An IAM policy's description can't change in place, so the policy would be replaced.
4. **Site plan roles trust only the hub** (`platform.hub.repository`), and only once `platform.hub` is set. Release, task, preview and site apply roles take nothing new.
5. **With a hub, every CI role pulls the hub image,** since every run uses it (spec 6.3, 6.4).
   - Roles without `ecr/pull` get it on the hub image.
   - Site roles keep `jaws-cli` and add the hub image.
   - The infra apply role, which pushes `jaws-cli` today, is the hub's release role. It pushes both and pulls both.
6. **The hub image's repository** is built like `jaws-cli`'s, with the `ecr-repository` module and its defaults (immutable tags, keep 20 `v*` images).
   - How `current` moves (a mutable tag needs a tag-mutability exclusion upstream) and how long commit tags live belong to plan 05, which designs those tags.
   - Nothing creates the repository before plan 07's enabling release, so plan 05 can change its inputs first.
7. **Shipping the stacks in the image belongs to plan 04,** which owns the `Dockerfile` and the size budget. The foundation needs the Databricks provider, which the `Dockerfile` says would put the image over budget.
   - The stacks stay where they are (`foundation/`, `monitoring/`, `data-access/`).
   - Plan 04 copies them to `/opt/jaws/stacks/<name>`, without `backend/`.
   - The hub image needs `datasets/` at `/etc/jaws/datasets` (plans 04, 06).
8. **Where the stacks read.**
   - The configuration: `var.config_path` (a caller's `JAWS_CONFIG`, passed as `TF_VAR_config_path`), else `/etc/jaws/config` when it holds `.yaml` files, else the repository's `config/`.
   - The datasets: `var.datasets_path`, else `datasets/` beside the configuration.
   - This follows `default_config_path` and `infra_root`.
9. **Backends stay outside the stacks.** `backend "s3" {}` is already generic.
   - `backend/prod.hcl` stays the owner's, for jaws's own runs. `tests/test_foundation_workflows.py` checks it (the backend-bucket check); plan 01 Task 3 may later move that check.
   - The hub's runs build their backend from `state` (plan 05).
10. **data-access changes nothing.** It reads only what `jaws access render` renders. Whether `access render` should also refuse a missing registry, as the foundation now does, is a question for plan 05, which moves the sweep into the hub image.
11. **The zone's own TXT records move to `dns.txt_records`** in `config/sites.yaml`, with `dns.zone`. The Owner tag reads `context.owner`. `Project = jaws` stays: white-label tags are plan 02's.

---

### Task 1: jaws-ci: a role trusts other repositories under their own IDs

In `Jaws-Platform/terraform-aws-jaws-ci`, branch `trust-other-repositories`.

**Files:**
- Modify: `modules/github-oidc-role/variables.tf` (add after `repository_alias_owner_ids`, :69-88), `modules/github-oidc-role/main.tf:1-24` (`repositories`, `subject_prefixes`, the comment)
- Modify: `modules/ci-plan-role/variables.tf` (after :52-56), `main.tf:16-33`, `outputs.tf`
- Modify: `modules/ci-apply-role/variables.tf` (after :52-56), `main.tf` (`module "role"`), `outputs.tf`
- Modify: `variables.tf` (after :22-27) and `main.tf` (`module "plan"`, `module "apply"`) at the root
- Test: `modules/github-oidc-role/tests/github_oidc_role.tftest.hcl`, `modules/ci-plan-role/tests/ci_plan_role.tftest.hcl`, `modules/ci-apply-role/tests/ci_apply_role.tftest.hcl`
- Regenerate: the `README.md` of each changed module, and the root's (terraform-docs)

**Interfaces:**
- Produces:
  - `variable "additional_repositories"` in `github-oidc-role`, `ci-plan-role`, `ci-apply-role` and the root, each passing it down:
    - type `list(object({ repository = string, owner_id = optional(string), repository_id = optional(string) }))`, default `[]`;
    - the description: "Other repositories whose workflows may assume the role, each trusted exactly like `repository` under its own IDs, for example the repository a platform's workflows are moving to. With both IDs, an entry is also trusted in GitHub's immutable subject form."
  - The subject order: the classic prefix of `repository`, of each alias, then of each additional repository; then the immutable prefixes in the same order. An entry without IDs has no immutable subject. With `additional_repositories = []` the list is exactly 0.4.0's.
  - `output "assume_role_policy"` in `ci-plan-role` and `ci-apply-role`: `module.role.assume_role_policy`, the trust policy JSON, so a caller can test it.
  - The validations, each with its own `error_message`:
    - every `repository` matches the existing `owner/repo` pattern;
    - none repeats `repository`, an alias or another entry;
    - IDs are digits and are set together.

- [ ] **Step 1: Write the failing tests** in `github_oidc_role.tftest.hcl`. Use the file's `example-org/example`, with the IDs `trust_policy_with_ids` uses:

```hcl
run "another_repository_is_trusted_under_its_own_ids" {
  command = plan

  variables {
    owner_id                = "35950238"
    repository_id           = "1420037633"
    subjects                = ["pull_request"]
    additional_repositories = [{ repository = "acme/platform", owner_id = "10000099", repository_id = "20000099" }]
  }

  assert {
    condition = jsondecode(aws_iam_role.this.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == [
      "repo:example-org/example:pull_request",
      "repo:acme/platform:pull_request",
      "repo:example-org@35950238/example@1420037633:pull_request",
      "repo:acme@10000099/platform@20000099:pull_request",
    ]
    error_message = "another repository adds its subjects after the repository's, under its own owner and repository IDs"
  }
}
```

Then add these runs:
- `another_repository_without_ids_is_trusted_in_the_classic_form_only`: an entry `{ repository = "acme/platform" }`, with the repository's IDs set. Expected: three subjects, the entry's classic one second.
- `rejects_another_repository_that_repeats_the_repository`: `[{ repository = "example-org/example" }]`, with `expect_failures = [var.additional_repositories]`.
- `rejects_another_repository_with_one_id`: `owner_id` only, expecting the same failure.
- `rejects_a_malformed_other_repository`: `repository = "platform"`, expecting the same failure.

In `ci_plan_role.tftest.hcl`, add `trusts_another_repository_for_pull_requests_only`. It passes the same `acme/platform` entry through `ci-plan-role`, whose file's repository is `example-org/guitar`, and asserts the four `pull_request` subjects on `output.assume_role_policy`. It also checks `output.assume_role_policy == module.role.assume_role_policy`. In `ci_apply_role.tftest.hcl`, add `trusts_another_repository_for_the_environment_only`, with `environment:prod` subjects.

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/check.sh modules/github-oidc-role modules/ci-plan-role modules/ci-apply-role`
Expected: FAIL, with `An argument named "additional_repositories" is not expected here`.

- [ ] **Step 3: Implement the variable, the subjects and the output.** In `main.tf` of `github-oidc-role`, extend `subject_prefixes` with two more `concat` arguments: the additional classic prefixes after `local.repositories`', and their immutable ones (entries with IDs only) after the existing immutable list. Update the comment above it. Add the pass-through lines and the output to the role modules and the root, then regenerate the READMEs with `terraform-docs --config .terraform-docs.yml <dir>`.

- [ ] **Step 4: Run them and watch them pass**

Run: `scripts/check.sh`
Expected: PASS, and every existing run passes unchanged. That shows a role without other repositories keeps its trust policy.

- [ ] **Step 5: Commit, one module each, and open the PR**

```bash
git commit -m "feat(github-oidc-role): trust other repositories under their own ids"
git commit -m "feat(ci-plan-role): trust other repositories and expose the trust policy"
git commit -m "feat(ci-apply-role): trust other repositories and expose the trust policy"
git commit -m "feat(examples): pass other trusted repositories through the root module"
gh pr create --title "feat(github-oidc-role): trust other repositories under their own ids" --body-file <file>
```

---

### Task 2: jaws-ci: the ECR policies take several repositories

In `Jaws-Platform/terraform-aws-jaws-ci`, branch `ecr-several-repositories`.

**Files:**
- Modify: `modules/ci-policies/variables.tf`, which covers:
  - the `ecr` validation (:100-103);
  - the `policy_inputs` description (:112);
  - the `ecr` type (:131-133).
- Modify: `modules/ci-policies/main.tf:147-161` (`ecr_pull`, `ecr_push`)
- Modify: `modules/ci-policies/outputs.tf:4-34` (`local.created`)
- Modify: the `policy_inputs` description of each role module, wherever it says `ecr = { repository_arn }`
- Test: `modules/ci-policies/tests/ci_policies.tftest.hcl`
- Regenerate: the READMEs it changes

**Interfaces:**
- Produces:
  - `policy_inputs.ecr = { repository_arn = optional(string), repository_arns = optional(list(string)) }`. An `ecr/*` policy needs exactly one of the two, and `repository_arns` must not be empty.
  - The first repository is `ecr/pull` (`<name_root>-<project>-ci-<role>-ecr-pull`), unchanged. The n-th, from n = 2, is `ecr/pull-<n>` (`…-ecr-pull-<n>`), a policy of its own made by the same `./ecr/pull` leaf. `ecr/push` works the same way.
  - These keys appear in `arns`, `names` and `documents`, and so in every role module's `policy_arns`.
  - The leaves are unchanged, descriptions included: each policy still covers one repository.

- [ ] **Step 1: Write the failing tests** in `ci_policies.tftest.hcl`. Each run sets `role = "plan"`, `policies = ["ecr/pull"]` and `policy_inputs = { ecr = … }`. The ARNs are the file's `arn:aws:ecr:us-east-1:123456789012:repository/acme-technologies-sites`, plus `…/acme-technologies-platform`.
- `ecr_pull_of_one_repository`: `repository_arn = <sites>`. It asserts nothing; the next run compares with it.
- `a_list_of_one_repository_is_the_policy_of_repository_arn`: `repository_arns = [<sites>]`. It asserts `output.documents == run.ecr_pull_of_one_repository.documents && output.names == run.ecr_pull_of_one_repository.names`.
- `each_further_repository_gets_a_policy_of_its_own`: `repository_arns = [<sites>, <platform>]`. It asserts:
  - `keys(output.arns) == ["ecr/pull", "ecr/pull-2"]`;
  - `output.names["ecr/pull-2"] == "acme-technologies-guitar-ci-plan-ecr-pull-2"`;
  - each document's `Statement[1].Resource` is its own ARN.
- `push_takes_several_repositories_the_same_way`: the apply role, `ecr/push`, two ARNs. Expected keys: `["ecr/push", "ecr/push-2"]`.
- `rejects_ecr_with_both_forms` and `rejects_an_empty_repository_list`: `expect_failures = [var.policies]`.

- [ ] **Step 2: Run them and watch them fail**

Run: `scripts/check.sh modules/ci-policies`
Expected: FAIL. `repository_arns` isn't an attribute of `ecr`.

- [ ] **Step 3: Implement it.**
- Add `local.ecr_repository_arns`: `repository_arns`, else `[repository_arn]`, else `[]`.
- `module.ecr_pull` and `module.ecr_push` keep their addresses and take its first element.
- Add `module "ecr_pull_extra"` and `module "ecr_push_extra"`, each with `for_each` over `{ for i, arn in slice(arns, 1, length(arns)) : tostring(i + 2) => arn }` when the policy is requested.
- Name them `"${local.names["ecr/pull"]}-${each.key}"` (and the push equivalent), and add them to `local.created` as `"ecr/pull-${n}"`.

- [ ] **Step 4: Run them and watch them pass**

Run: `scripts/check.sh`
Expected: PASS. `creates_only_requested_policies` and `every_policy_fits_the_managed_policy_size_limit` pass unchanged.

- [ ] **Step 5: Commit and open the PR**

```bash
git commit -m "feat(ci-policies): grant ecr pull and push on more than one repository"
gh pr create --title "feat(ci-policies): grant ecr pull and push on more than one repository" --body-file <file>
```

**Owner gate before Task 6:** merge Task 1's and Task 2's PRs, then the Release Please PR, so that one release, 0.5.0, carries both. If they land in two releases, Task 6 pins the later one.

---

### Task 3: the `platform` section and the zone's TXT records in the configuration

**Files:**
- Create: `config/platform.yaml`
- Modify: `config/sites.yaml`. Move the `txt_records` map and its comment from `foundation/dns.tf:25-34` under `dns.txt_records`, unchanged. Its value stays in `dns.tf` until Task 5.
- Modify: `src/jaws/settings.py`, which covers:
  - new classes after `ContextSection` (:187-197);
  - `DnsSection` (:199-201);
  - the `Settings` fields (:857-875), and a validator after `_monitoring_domain_in_the_zone`.
- Modify: `tests/test_settings.py` (`SECTION_FILES`, :31-42, gains `"platform": "platform.yaml"`; new tests)
- Modify: `config/README.md` (the table, :10-19) and `README.md` (the table in "The tool configuration", :384-394)
- Regenerate: `foundation/tests/fixtures/*.yaml`

**Interfaces:**
- Produces, the configuration's shape:

```yaml
platform:
  repositories:                    # at least one, each once, in order: the first is the platform's own
    - repository: <owner>/<name>   # as GitHub's OIDC subject spells it
      owner_id: "<digits>"         # quoted, like config/projects.yaml's IDs
      repository_id: "<digits>"
  hub:                             # optional
    repository: <owner>/<name>     # one of platform.repositories
    image: <name_root>-<name>      # an ECR repository name; not ecr.repository
dns:
  txt_records:                     # optional, default {}: "@" or a lowercase name relative to dns.zone
    <name>: [<1 to 255 characters, no double quote>, ...]
```

- Produces, in `jaws.settings`:
  - `class PlatformRepository(_Section)`: `repository: str`, `owner_id: str`, `repository_id: str`, with the patterns of the shape above;
  - `class PlatformHub(_Section)`: `repository: str`, `image: str` (`EcrSection.repository`'s pattern);
  - `class PlatformSection(_Section)`: `repositories: tuple[PlatformRepository, ...] = Field(min_length=1)`, `hub: PlatformHub | None = None`;
  - `Settings.platform: PlatformSection` (required);
  - `DnsSection.txt_records: dict[str, tuple[str, ...]] = {}`.
- The messages, verbatim:
  - "platform.repositories: {repository} is listed twice; each repository is trusted once"
  - "platform.hub.repository {repository} is not one of platform.repositories; the hub is trusted under its entry's IDs"
  - "platform.hub.image {image} must be named {name_root}-…: the foundation's apply role manages only {name_root}-* repositories"
  - "platform.hub.image {image} is ecr.repository's; the hub image needs its own repository"
  - "dns.txt_records: {name!r} must be @ or a lowercase record name relative to {zone}"
  - "dns.txt_records.{name} needs at least one string of 1 to 255 characters without double quotes"

- [ ] **Step 1: Write the failing tests** in `tests/test_settings.py`, with the file's `_load_raw` and this constant:

```python
#: A second platform repository: neutral values no other file holds.
SECOND = {"repository": "Example-Hub/platform", "owner_id": "10000099", "repository_id": "20000099"}


def test_the_platform_lists_its_own_repository_and_no_hub(settings: Settings) -> None:
    assert [r.repository for r in settings.platform.repositories] == ["Jaws-Platform/jaws"]
    assert settings.platform.hub is None
    assert settings.dns.txt_records  # moved from foundation/dns.tf


def test_a_second_repository_and_a_hub_are_read(tmp_path: Path) -> None:
    raw = fixture_config()
    raw["platform"]["repositories"].append(SECOND)
    raw["platform"]["hub"] = {"repository": "Example-Hub/platform", "image": "jaws-platform"}
    platform = _load_raw(tmp_path, raw).platform
    assert platform.repositories[1] == PlatformRepository(**SECOND)
    assert platform.hub == PlatformHub(repository="Example-Hub/platform", image="jaws-platform")


@pytest.mark.parametrize(
    ("platform", "message"),
    [
        ({"repositories": []}, r"platform\.repositories"),
        ({"repositories": [SECOND, SECOND]}, r"Example-Hub/platform is listed twice"),
        ({"repositories": [{**SECOND, "owner_id": 10000099}]}, r"owner_id"),
        ({"repositories": [{**SECOND, "repository": "platform"}]}, r"repository"),
        (
            {
                "repositories": [SECOND],
                "hub": {"repository": "Other-Org/platform", "image": "jaws-platform"},
            },
            r"platform\.hub\.repository Other-Org/platform is not one of platform\.repositories",
        ),
    ],
)
def test_a_malformed_platform_section_is_refused(
    tmp_path: Path, platform: dict[str, Any], message: str
) -> None:
    raw = {**fixture_config(), "platform": platform}
    with pytest.raises(ConfigError, match=message):
        _load_raw(tmp_path, raw)
```

Then add:
- `test_the_hub_image_has_its_own_repository_under_the_name_root`. `SECOND` is listed and named as the hub, and two cases each expect `ConfigError` matching `platform\.hub\.image`:
  - an image without the `<name_root>-` prefix, `platform`;
  - `ecr.repository`'s own name, read from `fixture_config()` in the test body.
- `test_the_zone_s_own_txt_records_are_checked`, parametrized. It expects `ConfigError` matching `dns\.txt_records` for:
  - a name under the zone, built from `raw["dns"]["zone"]`;
  - an uppercase name;
  - an empty list;
  - a string holding `"`.

  It accepts `{"@": ["v=spf1 -all"]}`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_settings.py -v`
Expected: FAIL. `PlatformRepository` can't be imported, and `test_every_section_is_in_its_file` fails on the new layout.

- [ ] **Step 3: Implement the models and validators.**
- `PlatformSection` has a `model_validator(mode="after")` for the "listed twice" and "not one of" messages.
- `Settings._hub_image_has_its_own_repository` handles the two image messages. It reads `context.name_root` and `ecr.repository`.
- `DnsSection` has an `after` validator for the TXT messages. The name pattern is the hosted-zone module's: `^[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?(\.[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?)*$`, and a name may not be the zone or end in `.<zone>`.

- [ ] **Step 4: Create `config/platform.yaml`**

Copy the repository from `local.context.repository` in `foundation/context.tf:21`. Copy its IDs from `local.github` (:41-44), quoted. Write one header line and this comment:

```yaml
# The repositories whose own workflows plan and apply this platform, and its hub.

platform:
  # Each role those workflows assume trusts every repository listed (the
  # foundation's own, monitoring's, data access's, and each bot, research and
  # Databricks project's plan and apply roles), under its own IDs:
  #   gh api repos/<owner>/<name> --jq '{id, owner_id: .owner.id}'
  # The first is the platform's own: the Repository tag of its stacks, the
  # zone's comment and the roles' descriptions name it. A move, a rename or a
  # transfer lists the new repository after it, then drops the old one once the
  # new one has run a release. IAM compares names case-sensitively: spell them
  # as GitHub does.
  repositories:
    - repository: Jaws-Platform/jaws
      owner_id: "<local.github.owner_id>"
      repository_id: "<local.github.repository_id>"
  # hub: one of the repositories above, whose pull requests also plan every
  # site, and the private ECR repository its image is pushed to (<name_root>-*).
```

If `fixture_config()` (`tests/conftest.py`) doesn't build on `config/`, add the same section there. The privacy hook rule applies.

- [ ] **Step 5: Docs and fixtures**
- `config/README.md`: the row `` [`platform.yaml`](platform.yaml) | `platform` | The repositories whose own workflows plan and apply the platform, which its roles trust, and the hub ``, and in `sites.yaml`'s row, "the hosted zone sites live in, and its own TXT records".
- `README.md`'s table gets the same rows.
- Run `uv run python -m tests.test_foundation_fixtures`.

- [ ] **Step 6: Run everything that reads the configuration**

Run: `uv run ruff format --check && uv run ruff check && uv run mypy && uv run pytest -q`
Expected: PASS.

Run: `(cd foundation && terraform init -backend=false && terraform test) && (cd monitoring && terraform test)`
Expected: PASS. Neither stack reads the new keys yet.

- [ ] **Step 7: Commit**

```bash
git add config src/jaws/settings.py tests/test_settings.py README.md foundation/tests/fixtures
git commit -m "feat(cli): describe the platform's repositories and its hub in the configuration"
```

---

### Task 4: the foundation and monitoring read the configuration and datasets where the CLI does

**Files:**
- Modify: `foundation/config.tf:1-22` (the header, `variable "config_path"`'s description, a new `variable "datasets_path"`, the path locals) and `foundation/config.tf:55-78` (a precondition)
- Modify: `foundation/databricks.tf:166` (`directory = local.datasets_path`)
- Modify: `monitoring/config.tf:1-14`, `monitoring/variables.tf`
- Create: `tests/test_platform_stacks.py`
- Test: `foundation/tests/foundation.tftest.hcl`, `monitoring/tests/monitoring.tftest.hcl`

**Interfaces:**
- Produces, in both stacks:
  - `local.image_config_path = "/etc/jaws/config"`;
  - `local.in_image = length(fileset(local.image_config_path, "*.yaml")) > 0`;
  - `local.config_path`: `var.config_path` if set, else `local.image_config_path` when `local.in_image`, else `"${path.module}/../config"`.
- Produces, in the foundation only:
  - `variable "datasets_path"` (string, default null);
  - `local.datasets_path`: `var.datasets_path` if set, else `"${dirname(trimsuffix(local.config_path, "/"))}/datasets"`. That is `/etc/jaws/datasets` in the image, the repository's `datasets/` from a checkout, and the directory beside any other `config_path`.
- Callers (plans 04, 05) pass `JAWS_CONFIG` as `TF_VAR_config_path`, and `$JAWS_INFRA_ROOT/datasets` as `TF_VAR_datasets_path`.

- [ ] **Step 1: Write the failing tests**

In `foundation/tests/foundation.tftest.hcl`, add a file-level block after the mocks:

```hcl
# The fixtures are single files under tests/fixtures/, which has no datasets/:
# every run reads the repository's registry unless it says otherwise.
variables {
  datasets_path = "../datasets"
}
```

and these runs:

```hcl
run "reads_its_configuration_and_datasets_from_the_repository_outside_the_image" {
  command = plan

  variables {
    datasets_path = null
  }

  # path.module is "." under terraform test, and dirname() cleans "./.." to "..".
  assert {
    condition     = !local.in_image && local.config_path == "./../config" && local.datasets_path == "../datasets"
    error_message = "without /etc/jaws/config the stack reads config/ and the datasets/ beside it, at the repository root, as the CLI reads ./config"
  }
}

run "the_datasets_are_beside_a_configuration_given_elsewhere" {
  command = plan

  variables {
    config_path   = "tests/fixtures/awaiting-host.yaml"
    datasets_path = null
  }

  # No dataset is onboarded before the host's URL is recorded, so the missing registry stops nothing.
  expect_failures = [check.shared_host_url]

  assert {
    condition     = local.datasets_path == "tests/fixtures/datasets"
    error_message = "config_path is where a caller's JAWS_CONFIG points, and the registry is the datasets/ beside it (jaws.access.infra_root)"
  }
}

```

Then add these runs:
- `a_configuration_directory_may_end_in_a_slash`: `config_path = "../config/"` and `datasets_path = null`. It asserts `local.datasets_path == "../datasets"`.
- `stops_without_the_datasets_registry`: `datasets_path = "tests/fixtures/no-datasets"`, a path that must not exist, with `expect_failures = [data.aws_caller_identity.current]`.

In `monitoring/tests/monitoring.tftest.hcl`, add `reads_its_configuration_from_the_repository_outside_the_image`. It asserts `!local.in_image && local.config_path == "./../config"`.

In `tests/test_platform_stacks.py`, open with a docstring saying where the platform's stacks find their configuration, then:

```python
@pytest.mark.parametrize("stack", ["foundation", "monitoring"])
def test_a_stack_looks_for_the_image_s_configuration_where_the_cli_does(stack: str) -> None:
    text = (REPO_ROOT / stack / "config.tf").read_text()
    assert re.findall(r'image_config_path\s*=\s*"([^"]+)"', text) == [str(IMAGE_CONFIG_PATH)]


def test_data_access_reads_only_what_the_cli_renders() -> None:
    """data-access/'s variables are `jaws access render`'s, from the CLI's configuration and datasets."""
    for path in sorted((REPO_ROOT / "data-access").glob("*.tf")):
        text = path.read_text()
        assert not any(word in text for word in ("yamldecode", "../config", "../datasets")), (
            path.name
        )
```

- [ ] **Step 2: Run them and watch them fail**

Run: `(cd foundation && terraform test) ; (cd monitoring && terraform test) ; uv run pytest tests/test_platform_stacks.py -v`
Expected: FAIL. `datasets_path` isn't a declared variable, `local.in_image` doesn't exist, and no `image_config_path` is found.

- [ ] **Step 3: Implement the locals, the variable and the precondition.** Add the precondition to `data.aws_caller_identity.current`:
- condition: `!(local.databricks_enabled && local.databricks_host_recorded) || fileexists("${local.datasets_path}/README.md")`;
- error_message: "The onboarded datasets are not at ${local.datasets_path} (no README.md there): planned without them, every onboarded dataset would be removed. Set datasets_path (TF_VAR_datasets_path), or keep datasets/ beside the configuration."

Point `module.dataset_registry`'s `directory` at `local.datasets_path`. Each variable's description names the order it resolves in, and `JAWS_CONFIG`. Copy the same `config_path` resolution into `monitoring/config.tf`.

- [ ] **Step 4: Run them and watch them pass**

Run: `(cd foundation && terraform test) && (cd monitoring && terraform test) && uv run pytest tests/test_platform_stacks.py -v`
Expected: PASS, every existing run included.

- [ ] **Step 5: Commit**

```bash
git add foundation/config.tf foundation/databricks.tf foundation/tests/foundation.tftest.hcl tests/test_platform_stacks.py
git commit -m "feat(foundation): read the configuration and datasets where the cli reads them"
git add monitoring
git commit -m "feat(monitoring): read the configuration where the cli reads it"
```

---

### Task 5: the foundation's own values come from the configuration

**Files:**
- Create: `foundation/platform.tf`
- Modify: `foundation/context.tf:1-50`. The header changes, and so do these values: `repository`, `repository_tag` and `owner` in `local.context`, and `local.github`. Its `module "context"` block is untouched.
- Modify: `foundation/dns.tf:1-46` (the header, `zone_name`, `txt_records`, a new `zone_comment` local used by `module.zone`)
- Modify: `foundation/outputs.tf:11-19` (two descriptions), `foundation/oidc.tf:1-18` (the comment)
- Modify: `monitoring/config.tf:41` (`repository`)
- Modify: `tests/test_foundation_fixtures.py:30-33` (`_relabelled`), `docs/tagging.md:74-77`
- Test: `foundation/tests/foundation.tftest.hcl`, `monitoring/tests/monitoring.tftest.hcl`, `tests/test_platform_stacks.py`
- Regenerate: `foundation/tests/fixtures/*.yaml`

**Interfaces:**
- Consumes: `platform.repositories`, `dns.txt_records`, `context.owner` (Task 3).
- Produces:
  - `local.platform_repositories = local.tool_config.platform.repositories`;
  - `local.platform_repository = local.platform_repositories[0]` (in `platform.tf`).
  - The `local.context` values:
    - `repository` and `repository_tag` are `local.platform_repository.repository`;
    - `owner` is `local.account.context.owner`.
  - `local.github` is `{ owner_id = local.platform_repository.owner_id, repository_id = local.platform_repository.repository_id }`, as strings.
  - In `dns.tf`:
    - `local.zone_name = local.tool_config.dns.zone`;
    - `local.txt_records = try(local.tool_config.dns.txt_records, {})`;
    - `local.zone_comment`, the comment `module.zone` takes today.
  - In `monitoring/config.tf`, `repository = local.tool_config.platform.repositories[0].repository`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_foundation_fixtures.py`, `_relabelled` sets values no code spells:

```python
def _relabelled(config: dict[str, Any]) -> dict[str, Any]:
    """Values no code spells: the stacks must take them from the file."""
    config["context"]["managed_by"] = "jaws-relabelled"
    config["context"]["owner"] = "example-owner"
    config["platform"]["repositories"][0]["repository"] = "Example-Org/platform"
    config["dns"]["zone"] = "example.com"
    config["dns"]["txt_records"] = {"_example-challenge": ["example-token"]}
    return config
```

Regenerate the fixtures. In `foundation.tftest.hcl`, rename `takes_its_managed_by_from_the_configuration` to `takes_its_identity_from_the_configuration`. Keep its assertion and add:

```hcl
  assert {
    condition     = module.context.tags["Repository"] == "Example-Org/platform" && module.context.tags["Owner"] == "example-owner"
    error_message = "the Repository tag is the first of platform.repositories, and Owner is context.owner"
  }

  assert {
    condition     = local.zone_name == "example.com" && local.zone_comment == "jaws: zone owned by Example-Org/platform; records owned by project repos"
    error_message = "the zone is dns.zone, and its comment names the platform's own repository"
  }

  assert {
    condition     = jsonencode(local.txt_records) == jsonencode({ "_example-challenge" = ["example-token"] })
    error_message = "the zone's own TXT records are dns.txt_records"
  }
```

In `the_repository_is_trusted_under_its_name_only`, the first assertion compares `local.context.repository`, `local.github.owner_id` and `local.github.repository_id` with `local.platform_repository`'s fields. The IDs are strings now; Task 7 replaces this run.

In `monitoring.tftest.hcl`, add `takes_its_identity_from_the_configuration`. It uses `config_path = "../foundation/tests/fixtures/relabelled.yaml"` and asserts the tags `Repository = "Example-Org/platform"`, `Owner = "example-owner"` and `ManagedBy = "jaws-relabelled"`.

In `tests/test_platform_stacks.py`, add this guard:

```python
def _owner_values() -> set[str]:
    """What identifies the owner in config/:
    - every account ID;
    - the zone, its ID, its TXT names and values;
    - context.owner;
    - the platform repositories' IDs.
    Not context.organization (Jaws-Platform, the vendor's name) or repository
    names: module sources share them."""


@pytest.mark.parametrize("stack", ["foundation", "monitoring", "data-access"])
def test_a_platform_stack_holds_no_owner_value(stack: str) -> None:
    for path in sorted((REPO_ROOT / stack).glob("*.tf")):
        found = sorted(value for value in _owner_values() if value in path.read_text())
        assert not found, (
            f"{path.relative_to(REPO_ROOT)} holds values from config/ that identify the owner"
        )
```

`_owner_values()` reads `load_settings(CONFIG_DIR, environ={})`. The message names the file only, never the values.

- [ ] **Step 2: Run them and watch them fail**

Run: `(cd foundation && terraform test) ; (cd monitoring && terraform test) ; uv run pytest tests/test_platform_stacks.py tests/test_foundation_fixtures.py -v`
Expected: FAIL. The tags, zone and records are still literals, and the guard names `context.tf`, `dns.tf` and `outputs.tf`.

- [ ] **Step 3: Implement the locals.**
- Create `platform.tf`, with a header that says what `platform.repositories` is to this stack and why its order matters.
- Rewrite the `dns.tf` header without the owner's names. The GitHub Pages explanation now lives in `config/sites.yaml`.
- The `hosted_zone_*` output descriptions say "the platform's zone (config/sites.yaml `dns.zone`)".
- The `oidc.tf` comment: the account's one GitHub OIDC provider is created by hand at bootstrap (README.md, "Bootstrap"); every stack shares it and this one only reads it; it grants nothing by itself.
- `docs/tagging.md:74-77`: the foundation's `Organization`, `Repository`, `Owner` and `ManagedBy` come from `context` and the first of `platform.repositories`, and `Project` is `jaws`.

- [ ] **Step 4: Run them and watch them pass**

Run: `(cd foundation && terraform test) && (cd monitoring && terraform test) && uv run pytest -q`
Expected: PASS. The default runs' tag, zone and break-glass assertions are unchanged, so the owner's values are the same.

- [ ] **Step 5: Commit**

```bash
git add foundation tests/test_foundation_fixtures.py tests/test_platform_stacks.py docs/tagging.md
git commit -m "refactor(foundation): take the zone, its records and the tags from the configuration"
git add monitoring
git commit -m "refactor(monitoring): take the repository tag from the configuration"
```

---

### Task 6: pin jaws-ci 0.5.0

Wait until `curl -s https://registry.terraform.io/v1/modules/Jaws-Platform/jaws-ci/aws/versions | jq -r '.modules[0].versions[].version'` lists `0.5.0`.

**Files:**
- Modify: the 15 `version = "0.4.0"` lines under `Jaws-Platform/jaws-ci/aws` sources, which are:
  - `foundation/ci-roles.tf` (4);
  - `foundation/bots.tf` (4);
  - `foundation/monitoring.tf` (2);
  - `foundation/databricks.tf` (2);
  - `foundation/projects.tf` (3).
- Modify: the `Jaws-Platform/jaws-ci/aws` entry in `src/jaws/product.yaml`; `tests/test_product.py:14`

**Interfaces:**
- Produces: every jaws-ci module block at `0.5.0`, with `additional_repositories`, `assume_role_policy` and `repository_arns` available (Tasks 1–2).

- [ ] **Step 1: Make the test fail.** Set `tests/test_product.py:14` to expect `"0.5.0"`.

Run: `uv run pytest tests/test_product.py tests/test_versions.py -v`
Expected: FAIL. The release file and the pins say `0.4.0`.

- [ ] **Step 2: Bump the 15 pins and the release file**

- [ ] **Step 3: Install the modules without touching the providers.** Don't pass `-upgrade`: it would move the providers in the lock file.

Run: `(cd foundation && terraform init -backend=false && terraform validate && terraform test) && git diff --exit-code foundation/.terraform.lock.hcl`
Expected: PASS, every existing run unchanged, and no lock file diff.

Run: `uv run pytest tests/test_product.py tests/test_versions.py -v`
Expected: PASS.

- [ ] **Step 4: Commit.** If Dependabot opened its own bump for `foundation/`, close it: it misses `src/jaws/product.yaml`.

```bash
git add foundation/*.tf src/jaws/product.yaml tests/test_product.py
git commit -m "chore(deps): bump jaws-ci to 0.5.0 in the foundation and the release pins"
```

---

### Task 7: the platform's roles trust its repositories, and the site plan roles trust its hub

**Files:**
- Modify: `foundation/platform.tf` (new locals), `foundation/oidc.tf` (a `lifecycle` block on `data.aws_iam_openid_connect_provider.github`)
- Modify: `foundation/context.tf`. Drop `repository`, `repository_aliases` and `repository_alias_owner_ids`, with their comment, from `local.context`, and drop `local.github`.
- Modify: the ten blocks of `TOOL_ROLES`, which are:
  - `foundation/ci-roles.tf:59-172` (four);
  - `foundation/bots.tf:85-134` (two);
  - `foundation/monitoring.tf:103-151` (two);
  - `foundation/databricks.tf:291-334` (two).
- Modify: `foundation/projects.tf:83-102` (`site_ci_plan`)
- Modify: `tests/test_repository_trust.py` (rewritten), `tests/test_bots_registry.py:127` and `:621`, `tests/test_foundation_fixtures.py` (three fixtures)
- Modify: `README.md:582` (the CI roles' trust), `config/README.md` (a section, "The platform's repositories")
- Test: `foundation/tests/foundation.tftest.hcl`
- Regenerate: `foundation/tests/fixtures/*.yaml`

**Interfaces:**
- Consumes: `local.platform_repositories`, `local.platform_repository` (Task 5); `additional_repositories` and `assume_role_policy` (Task 1).
- Produces, in `platform.tf`:
  - `local.platform_trust = { repository, owner_id, repository_id, additional_repositories }`: the first entry's fields, and `slice(local.platform_repositories, 1, length(local.platform_repositories))`;
  - `local.hub = try(local.tool_config.platform.hub, null)`;
  - `local.hub_trust`: `[for r in local.platform_repositories : r if r.repository == local.hub.repository]`, or `[]` without a hub.
- Produces, in `tests/test_foundation_fixtures.py`:
  - `HUB_REPOSITORY = {"repository": "Example-Hub/platform", "owner_id": "10000099", "repository_id": "20000099"}`;
  - `HUB = {"repository": "Example-Hub/platform", "image": "jaws-platform"}`;
  - the fixtures `two-repositories.yaml` (appends `HUB_REPOSITORY`), `hub.yaml` (that, plus `platform.hub = HUB`) and `hub-not-trusted.yaml` (`platform.hub = HUB` only). Task 8 adds a fourth.
- Each `TOOL_ROLES` block's trust becomes these four lines, replacing today's five:

```hcl
  repository              = local.platform_trust.repository
  owner_id                = local.platform_trust.owner_id
  repository_id           = local.platform_trust.repository_id
  additional_repositories = local.platform_trust.additional_repositories
```

and `site_ci_plan` gains `additional_repositories = local.hub_trust`. No other role block gets the argument.

- [ ] **Step 1: Write the failing tests**

`tests/test_repository_trust.py` keeps `TOOL_ROLES` and `_role_modules()`. Its docstring says the roles take `platform.repositories` rather than aliases. Its tests are:
- `test_the_roles_that_trust_the_platform_s_repositories_are_the_tools_own`: the modules whose `repository` is `local.platform_trust.repository` are exactly `TOOL_ROLES`.
- `test_each_of_them_trusts_every_platform_repository`: each has `owner_id`, `repository_id` and `additional_repositories` from `local.platform_trust`, and no `repository_aliases` or `repository_alias_owner_ids`.
- `test_a_site_plan_role_also_trusts_the_hub`: `site_ci_plan`'s `additional_repositories` is `local.hub_trust`.
- `test_other_roles_trust_only_their_own_repository`: every other role module has no `additional_repositories` and no alias argument.

`test_every_alias_owner_id_belongs_to_an_alias` goes. In `tests/test_bots_registry.py`, `:127` expects `local.platform_trust.owner_id`, and `:621` expects `repository = local.platform_trust.repository`.

In `foundation.tftest.hcl`, `the_repository_is_trusted_under_its_name_only` becomes:

```hcl
run "the_platform_repository_is_trusted_as_before" {
  command = plan

  assert {
    condition     = local.platform_trust.repository == "Jaws-Platform/jaws" && length(local.platform_trust.additional_repositories) == 0 && length(local.hub_trust) == 0
    error_message = "config/platform.yaml lists Jaws-Platform/jaws alone, and names no hub"
  }

  assert {
    condition = jsondecode(module.infra_ci_plan.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == [
      "repo:${local.platform_repository.repository}:pull_request",
      "repo:${split("/", local.platform_repository.repository)[0]}@${local.platform_repository.owner_id}/${split("/", local.platform_repository.repository)[1]}@${local.platform_repository.repository_id}:pull_request",
    ]
    error_message = "with one repository the plan role trusts its pull requests in both subject forms and nothing else: the trust policy jaws-ci 0.4.0 built"
  }

  assert {
    condition     = alltrue([for key, role in module.site_ci_plan : length(jsondecode(role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"]) == 2])
    error_message = "without a hub a site's plan role trusts only its own repository"
  }
}
```

Then add these runs:
- `a_second_repository_is_trusted_alongside_the_first`, with `two-repositories.yaml`. It asserts:
  - `module.infra_ci_plan`'s subjects are the first repository's classic subject, `repo:Example-Hub/platform:pull_request`, the first's immutable subject, then `repo:Example-Hub@10000099/platform@20000099:pull_request`;
  - every other plan role of `TOOL_ROLES` contains that last subject (the pattern below), and every apply role contains `repo:Example-Hub@10000099/platform@20000099:environment:prod`;
  - `module.context.tags["Repository"] == local.platform_repository.repository`, and every site plan role still has 2 subjects.
- `the_hub_plans_every_site`, with `hub.yaml`. Each site plan role has 4 subjects, including the hub's immutable `pull_request` subject. Each site apply role still has 2.
- `refuses_a_hub_it_does_not_trust`, with `hub-not-trusted.yaml` and `expect_failures = [data.aws_iam_openid_connect_provider.github]`.

The pattern for a group of roles:

```hcl
condition = alltrue([
  for policy in concat(
    [module.data_access_ci_plan.assume_role_policy],
    [for role in module.monitoring_ci_plan : role.assume_role_policy],
    [for key, role in module.bot_ci_plan : role.assume_role_policy],
    [for key, role in module.databricks_ci_plan : role.assume_role_policy],
  ) : contains(jsondecode(policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"], "repo:Example-Hub@10000099/platform@20000099:pull_request")
])
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run python -m tests.test_foundation_fixtures && (cd foundation && terraform test) ; uv run pytest tests/test_repository_trust.py tests/test_bots_registry.py -v`
Expected: FAIL. `local.platform_trust` doesn't exist, and the wiring tests find `local.context.repository`.

- [ ] **Step 3: Implement the locals, the wiring and the precondition.** The precondition on `data.aws_iam_openid_connect_provider.github`:
- condition: `local.hub == null ? true : length(local.hub_trust) == 1`;
- error_message: "platform.hub.repository (config/platform.yaml) is not one of platform.repositories: the hub's pull requests are trusted under its entry's IDs, so list it there."

Use the conditional rather than `||`: the stack accepts Terraform 1.11, so don't rely on `||` skipping its right-hand side.

- [ ] **Step 4: Docs**
- `README.md:582` becomes one paragraph. Every role this repository's workflows assume trusts the repositories in `platform.repositories` (`config/platform.yaml`), today `Jaws-Platform/jaws` alone. That covers these two, the monitoring and data access roles, and each bot, research and Databricks project's plan and apply roles. With `platform.hub`, each site's plan role also trusts the hub's pull requests. The audience stays pinned to `sts.amazonaws.com`.
- `config/README.md` gets the section "The platform's repositories", the procedure for a move, a rename or a transfer:
  1. add the new repository second, with its IDs; the next release trusts both;
  2. name it in `platform.hub` when its image and site plans are wanted;
  3. drop the old first entry once the new one has run a release. The Repository tag, the zone's comment and the roles' descriptions follow the new first entry.

- [ ] **Step 5: Run everything**

Run: `(cd foundation && terraform validate && terraform test) && uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add foundation tests README.md config/README.md
git commit -m "feat(foundation): trust the platform's repositories, and the hub for site plans"
```

---

### Task 8: the hub image's repository, and who pulls and pushes it

**Files:**
- Modify: `foundation/ecr.tf` (the header, new locals, `module "hub_image"`, `check "hub_image_repository_arn_matches"`), `foundation/oidc.tf` (a second precondition)
- Modify: `foundation/ci-roles.tf:45-48` (`local.infra_ci.ecr`) and its four role blocks; `foundation/bots.tf:85-177`; `foundation/monitoring.tf:103-151` (and the "Eight managed policies" comment); `foundation/databricks.tf:291-334`; `foundation/projects.tf:76-78` (`local.project_ci[*].ecr`)
- Modify: `tests/test_bots_registry.py:575-578` (`_hcl_list` accepts `concat(` before the list, as `_policies` does), `tests/test_foundation_fixtures.py` (one fixture), `README.md:349` (the `ecr.tf` row)
- Test: `foundation/tests/foundation.tftest.hcl`
- Regenerate: `foundation/tests/fixtures/*.yaml`

**Interfaces:**
- Consumes: `local.hub` (Task 7), `repository_arns` (Task 2).
- Produces, in `ecr.tf`:
  - `local.hub_image_repository_arn`: `"arn:aws:ecr:${local.region}:${data.aws_caller_identity.current.account_id}:repository/${local.hub.image}"`, or null;
  - `local.hub_image_pull`: `["ecr/pull"]` with a hub, else `[]`;
  - `local.hub_image_ecr`: `{ repository_arns = [local.hub_image_repository_arn] }` with a hub, else null;
  - `local.image_repository_arns`: `concat([local.sites_image_repository_arn], <the hub's ARN, if any>)`.
- Produces `module "hub_image"`:
  - `count = local.hub == null ? 0 : 1`;
  - source `Jaws-Platform/jaws-lichess-bot/aws//modules/ecr-repository` at `0.1.4`, with `version` on the line after `source` (`tests/test_versions.py` reads pins that way);
  - `name = local.hub.image`;
  - `depends_on = [module.infra_ci_apply]`, for `sites_image`'s reason.
- Produces the check, `alltrue([for m in module.hub_image : m.arn == local.hub_image_repository_arn])`.
- For plans 04–07: the hub image's repository is `platform.hub.image`. `<name_root>-infra-ci-apply` pushes it, and every CI role pulls it.
- The roles:

| Module blocks | `policies` | `policy_inputs.ecr` |
|---|---|---|
| `infra_ci_plan`, `data_access_ci_plan`, `data_access_ci_apply`, `monitoring_ci_plan`, `monitoring_ci_apply`, `bot_ci_plan`, `bot_ci_apply`, `bot_ci_release`, `bot_ci_task`, `databricks_ci_plan`, `databricks_ci_apply` | today's list, then `local.hub_image_pull`, inside `concat(…)` | `local.hub_image_ecr` (`bot_ci_release` gains `policy_inputs = { ecr = local.hub_image_ecr }`) |
| `infra_ci_apply` | today's list, then `local.hub_image_pull` | `local.infra_ci.ecr`, now `{ repository_arns = local.image_repository_arns }` |
| `site_ci_plan`, `site_ci_preview`, `site_ci_apply` | unchanged (`ecr/pull` already) | `local.project_ci[key].ecr`, now `{ repository_arns = local.image_repository_arns }` |

The second precondition on `data.aws_iam_openid_connect_provider.github`:
- condition: `local.hub == null ? true : startswith(local.hub.image, "${local.context.name_root}-") && local.hub.image != local.account.ecr.repository`;
- error_message: "platform.hub.image (config/platform.yaml) must be named ${local.context.name_root}-*, the only repositories the foundation's apply role may create, and must not be ecr.repository's: the CLI image keeps its own."

- [ ] **Step 1: Write the failing tests**

Add the fixture `hub-image-outside-the-name-root.yaml`: `hub.yaml`'s changes with `platform.hub.image = "platform"`. Regenerate the fixtures.

Every run whose fixture sets `platform.hub` takes this block, with that fixture's image name. That includes Task 7's `the_hub_plans_every_site` and `refuses_a_hub_it_does_not_trust`, and this task's refusal run. Under a mock provider the module's `arn` isn't known during the plan, so `check.hub_image_repository_arn_matches` can't be evaluated and fails the run, as `sites_image`'s would without its file-level override. The mocked account is `mock_data "aws_caller_identity"`'s at the top of the file:

```hcl
  override_module {
    target = module.hub_image
    outputs = {
      arn = "arn:aws:ecr:us-east-1:<the mocked account_id>:repository/jaws-platform"
    }
  }
```

Then add these runs:
- `no_hub_image_without_a_hub`, on the default configuration. It asserts:
  - `length(module.hub_image) == 0 && local.hub_image_repository_arn == null`;
  - `!contains(keys(module.infra_ci_plan.policy_arns), "ecr/pull")`;
  - `toset(keys(module.infra_ci_apply.policy_arns)) == toset(["tfstate/write", "foundation/read", "foundation/manage", "ecr/push", "databricks/read"])`;
  - every `module.site_ci_plan` role's keys are `toset(["tfstate/read", "static-site/read", "ecr/pull"])`.
- `a_hub_gets_its_image_repository`, with `hub.yaml`. It asserts:
  - `length(module.hub_image) == 1`, and `local.hub_image_repository_arn == "arn:aws:ecr:us-east-1:${local.account_id}:repository/jaws-platform"`: the platform account, never the management account;
  - every role module's `policy_arns` has `ecr/pull`. Concat the fifteen blocks' `keys(policy_arns)` (lists of strings, so the element types agree), the way Task 7 concats trust policies;
  - every site role's has `ecr/pull-2`, and `module.infra_ci_apply.policy_arns` has `ecr/push-2` and `ecr/pull-2`.
- `a_hub_keeps_every_role_within_ten_policies`, with `hub.yaml`. Every role module's `length(policy_arns) <= 10`.
- `refuses_a_hub_image_outside_the_name_root`, with `expect_failures = [data.aws_iam_openid_connect_provider.github]`.

- [ ] **Step 2: Run them and watch them fail**

Run: `(cd foundation && terraform test)`
Expected: FAIL. `module.hub_image` isn't declared, and the hub runs find no `ecr/pull` on the tool roles.

- [ ] **Step 3: Implement the locals, the module, the check, the precondition and the role inputs** from the Interfaces table. Update `_hcl_list`, then the `ecr.tf` row in `README.md`: "The ECR repositories for the infra CLI image (`ecr` in `config/tool.yaml`) and, with a hub, for the hub image (`platform.hub.image`), and who pulls and pushes them".

- [ ] **Step 4: Run them and watch them pass**

Run: `(cd foundation && terraform validate && terraform test) && uv run pytest -q`
Expected: PASS. `no_hub_image_without_a_hub` and every existing run show that without a hub nothing changes.

- [ ] **Step 5: Commit**

```bash
git add foundation tests README.md
git commit -m "feat(foundation): create the hub image's repository and let every ci role pull it"
```

---

### Task 9: open the pull request

- [ ] **Step 1: Commit the plan, and its rulings to the roadmap.**
- Row 03's status becomes "in its pull request".
- Row 04 adds "ship the platform stacks in the image (`/opt/jaws/stacks/<name>`, without `backend/`), and the datasets beside the configuration".
- Row 05 adds "the hub image's tags (`current`'s mutability, the commit tags' lifecycle), and the hub's backends from `state`".

```bash
git add docs/superpowers/plans/2026-11-23-hub-split-03-platform-stacks.md docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md
git commit -m "docs(foundation): add plan 03 of the hub split and its rulings to the roadmap"
```

- [ ] **Step 2: Run the full `AGENTS.md` checklist,** plus `(cd foundation && terraform test)` and `(cd data-access && terraform init -backend=false && terraform test)`.
Expected: every command passes. `tests/test_owner_access.py` and `tests/test_billing_export.py` pass unchanged.

- [ ] **Step 3: Push the branch and open the PR**
- Title: `feat(foundation): take the platform's trust, hub and identity from the configuration`.
- Body: `.github/pull_request_template.md`, with every section filled in. It links the spec, this plan, and jaws-ci 0.5.0's two PRs. Under Summary and Why it says nothing in AWS changes (no owner hand-off), and that jaws-ci 0.5.0 was released before Task 6.

```bash
gh pr create --title "feat(foundation): take the platform's trust, hub and identity from the configuration" --body-file <file>
```

Expected: CI passes. The `Terraform plan` and `Monitoring plan` comments say merging leaves AWS alone. The data access plan shows no changes.
