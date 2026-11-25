# Jaws as a product, plan 04: images and publishing: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Jaws's image with every stack and no configuration inside, and publish every release of it to ECR Public through a new owner-applied `release-infra/`, keeping the newest ten there until v1. Keep pushing the configuration-baked `jaws-cli` image, so every existing pin keeps working.

**Architecture:**
- One `Dockerfile`, two targets.
  - `generic` is the default target. It holds the CLI, a pinned Terraform and every stack: `stacks/*`, and the platform's `foundation/`, `monitoring/` and `data-access/`. The stacks come without their backends or tests, with modules and providers vendored, so a run needs the network only for its backend and APIs. The image holds no configuration.
  - `jaws-cli` is `generic` plus this repository's `config/` at `/etc/jaws/config` and `datasets/` at `/etc/jaws/datasets`. That is the shape of every platform's image, the hub's included.
- Each release pushes `jaws-cli:<tag>` as today. A tag cut before this plan has no `jaws-cli` stage, so re-publishing it builds its only image, as it always did.
- `release-infra/` is a new root that only the owner applies, like `billing-export/`.
  - It holds the ECR Public repository `jaws`, and `release-infra-publish`: a role that only this repository's `publish` environment can assume, and that may push to and prune only `jaws`.
  - Its state sits in the platform's state bucket under `project=release-infra/`. IAM keeps every CI role out of that prefix, since each may reach only its own state key. The bucket policy alone does not: it exempts the bucket's admins, the foundation's apply role among them, so only a reviewed foundation change could open the prefix (ruling 8).
- Once the owner has applied it and set two repository variables, each release also pushes `generic` to `public.ecr.aws/<alias>/jaws:<tag>`. Until then, that job skips with a notice.
- After each publish, the job prunes the public repository to the newest `JAWS_PUBLIC_IMAGE_KEEP` release versions by semver (default 10), and never deletes the tag it just pushed. ECR Public has no lifecycle policies. `all` keeps every version, which the owner sets at v1 (ruling 14).

**Tech Stack:** Docker BuildKit (named targets); GitHub Actions (`docker/build-push-action@v7`, `aws-actions/configure-aws-credentials@v6`, `aws-actions/amazon-ecr-login@v2` with `registry-type: public`); the AWS CLI's `ecr-public` commands, for pruning; Terraform 1.14.7 (`terraform test` with mock providers); the AWS provider `~> 6.0` (`aws_ecrpublic_repository`); `Jaws-Platform/jaws-ci/aws//modules/github-oidc-role` and `Jaws-Platform/jaws-foundation/aws//modules/context`, at their `src/jaws/product.yaml` versions (0.6.0 and 0.2.0 today); Python 3.13 and pytest; Node's test runner (commitlint).

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md), sections 6.3, 6.8, 6.10 (step 1), 6.12, 2, and 4 (decisions 5 and 6). Roadmap: [2026-11-23-hub-split-00-roadmap.md](2026-11-23-hub-split-00-roadmap.md), row 04. Plan 03's ruling 7 hands this plan the stacks in the image and the size budget. The owner's retention decision of 2026-11-23 (ruling 14) sets how long ECR Public keeps a release, and lets the role prune.

**Where the work happens:** `jaws`, on `hub-split/04-images`, the branch of draft PR #317. It was cut from ef89d7a and holds only this plan, so rebase it onto `main` before Task 1: 0cd5825 or later, where plans 01 and 03 have merged (#314, #316 and #318) and v0.80.1 is released. One branch, one PR.

## Global Constraints

- **The repository rules (`AGENTS.md`):**
  - never push to `main`: one branch, one PR;
  - each commit is one line, `type(scope): subject`, at most 100 characters, with a lowercase first letter and no trailing period;
  - only `Co-authored-by:` trailers may follow, after a blank line;
  - the PR title is a valid commit header, and the PR body fills every template section.
- **Scopes.** `cli` for Tasks 1–3, 5 and 6; `repo` for adding the new scope and for Task 7's roadmap commit; `publishing` for Task 4. The spec, verbatim (6.12): "**`jaws`:** a new `publishing` scope for the release infrastructure folder."
- **Never touch real infrastructure.**
  - Never run `terraform apply`, a plan against real state, `jaws apply|publish|release|destroy`, `docker push`, or an `aws ecr-public` command.
  - Run only `terraform test` (mock providers), `terraform validate`, `tflint`, `scripts/test-stack-plans.sh`, and local `docker build` and `docker run` (`--network none` for smoke tests).
- **Nothing in AWS changes when this plan merges.**
  - No `.tf` file in `foundation/`, `monitoring/` or `data-access/` changes: the image ships them as they are. So CI's `Terraform plan`, `Monitoring plan` and `Data access plan` must say merging leaves AWS alone.
  - CI never applies `release-infra/`: only the owner does.
  - Nothing pushes to ECR Public until the owner has applied `release-infra/` and set `JAWS_PUBLISH_ROLE_ARN` and `JAWS_PUBLIC_IMAGE`. Nothing deletes from it but the prune step, after a publish.
- **Old pins keep working.** The spec's anti-goal, verbatim (2): "A window where a project's CI is broken. Old pins keep working until that project switches."
  - The composite action doesn't change, and still runs `jaws-cli:<its own tag>`.
  - Every release still pushes `jaws-cli:<tag>` with `config/` baked in.
  - Re-publishing any tag (`release-please.yml`'s `workflow_dispatch`) builds that tag's own image for `jaws-cli`.
- **Jaws's image, verbatim (6.3):** "Generic: no configuration inside." "Published by `jaws`'s release workflow to `public.ecr.aws/<alias>/jaws:vX.Y.Z`, with the role from section 6.8." "`jaws`'s CI keeps the build, offline smoke test and size budget it has today."
- **The release infrastructure, verbatim (6.8):** "the ECR Public repository `jaws`;" "one role, trusted only for `Jaws-Platform/jaws` release runs, that may push to that repository and nothing else." "Its state goes in the platform's state bucket, under its own prefix." "The role's ARN is a repository variable in `jaws`. No account ID appears in code outside this folder."
  - The owner's decision of 2026-11-23 widens the role to push to that repository and prune it, and nothing else (ruling 14).
- **Spending, as the owner decided on 2026-11-23** (ruling 14):
  - **ECR Public.** Pruning keeps ten images of about 265 MB each, about 2.7 GB. Even eleven at the 300 MiB budget (a re-published older tag beside the ten) stay under 3.5 GB. That is far inside ECR Public's always-free 50 GB, so nothing is paid.
  - **`all` is a spending decision too.** Each release adds about 265 MB that no other release shares: release builds have no cache, every file gets a fresh mtime, and the providers float. At today's pace, about 6 releases a day, `all` would fill the free 50 GB in about a month. The owner sets it at v1, once the pace and the consumers are known.
  - **The private `jaws-cli` repository grows by about 1 GiB, about $0.10 a month,** from the first release after this plan merges until cleanup retires it. Each image is about 54 MiB larger on amd64 (the platform stacks and their providers), and the 20 images it keeps share no layers. The owner accepted this.
- **The region** stays `us-east-1`, a product constant (spec 6.7). ECR Public's API exists only there.
- **Owner values in files.**
  - `release-infra/` is the one folder that may spell these: the production account's ID, the platform's state bucket, and the GitHub IDs of `Jaws-Platform/jaws`.
  - This plan names them by their paths: `aws.accounts[aws.primary].account_id` in `config/aws.yaml`, `state.bucket` in `config/terraform.yaml`, and `platform.repositories[0]` in `config/platform.yaml`.
  - Only `tests/platform/` reads `config/`, through `PLATFORM_CONFIG_DIR` (`tests/platform/test_isolation.py` checks). Every other test reads the neutral fixture `tests/fixtures/platform/` (`repo_config()`, `CONFIG_DIR`). `tests/platform/test_no_owner_values.py` fails on any owner value in `src/jaws/`, `tests/`, `foundation/tests/` or `monitoring/tests/`.
  - A failing check never prints an owner value. It calls `pytest.fail(..., pytrace=False)` with a message that names the field, as `tests/platform/test_state_backends.py` does.
  - New tests use neutral values: account `123456789012`, `public.ecr.aws/example-alias/jaws`.
- **The privacy hook.**
  - If a hook refuses a command because a file holds the owner's email, stop and ask the owner to run it (they can, with `!`). Never work around the hook.
  - `tests/conftest.py` is never edited. Importing its helpers (`REPO_ROOT`, `repo_config`, `onboarded`, `PLATFORM_CONFIG_DIR`) is fine.
  - If the hook refuses the local `docker build --target jaws-cli`, which copies `config/`, leave that target to CI.
- **Off limits.**
  - `owner-access/` and `billing-export/`.
  - Plan 02's files: `src/jaws/report.py`, the `ManagedBy` checks in `stacks/site/variables.tf` and `stacks/bot/variables.tf`, the SSM path constants, and `src/jaws/kinds/lichess_bot/Dockerfile`'s labels.
  - This plan owns the root `Dockerfile`, its labels included.
- **Before the PR,** run the `AGENTS.md` checklist, then `(cd release-infra && terraform init -backend=false && terraform validate && terraform test)`, then the smoke commands of Tasks 2 and 3 against a local `docker build --platform linux/amd64`.

## Review Focus

1. **Re-publishing a tag cut before this plan.** Each of them, v0.80.1 and earlier, has one image with `config/` baked in and no `jaws-cli` stage: v0.76.0, for example, which the projects pin (spec 3). Expected: `jaws-cli` gets that tag's own image, built as before, and ECR Public gets nothing. Tests: Task 2, `test_the_jaws_cli_job_builds_jaws_cli_or_an_old_tag_s_only_image`; Task 5, `test_a_tag_without_the_generic_image_is_never_published`.
2. **A release before publishing is set up, or when it is half set up.** Expected:
   - with neither variable set, the release goes on and `jaws-cli` is pushed. The public job is skipped with a notice, and never enters the `publish` environment;
   - with one variable, or a malformed one (`JAWS_PUBLIC_IMAGE_KEEP` included), the check fails and names it, before anything is pushed. `jaws-cli` is still pushed.

   Tests: Task 5, `test_without_the_variables_publishing_is_skipped_with_a_notice`, `test_a_half_set_or_malformed_variable_fails_the_check` and `test_the_public_job_runs_only_when_the_check_says_so`.
3. **A tag that is already public.** ECR Public tags are mutable, and customers pin tag and digest. Expected: a published tag is never replaced, and a registry error stops the job rather than pushing. Tests: Task 5, `test_a_published_tag_is_never_replaced` and `test_a_registry_error_stops_the_publish`.
4. **The public image run with no configuration.** Expected: exit 2, with a message naming `JAWS_CONFIG` and `/etc/jaws/config`, not today's "tool configuration not found at config". Tests: Task 1, `test_without_a_configuration_the_cli_says_where_it_looks`; Task 2's smoke step.
5. **The owner's files in the public image.** `backend/prod.hcl` names the owner's state bucket, and the stacks' `tests/` hold fixtures generated from the owner's configuration. Expected: the generic image holds no `/etc/jaws`, `backend/`, `tests/`, `.tftest.hcl` or state. Tests: Task 2, `test_the_generic_image_holds_no_configuration`; Task 3, `test_the_build_context_keeps_backends_lock_files_and_stack_tests_out`, and the smoke step "the generic image ships no backend, stack test or state".
   - Accepted, for plan 07's guard: the package METADATA embeds `README.md`, which is already public. A local build can carry gitignored files (`foundation/tfplan`, `data-access/terraform.tfvars.json`), but only CI's clean checkouts are ever pushed.
6. **Pruning deletes public images.** Expected, after each publish:
   - the newest N `vX.Y.Z` versions by semver stay, and so does the tag just pushed, wherever it falls;
   - the other versions go by tag, and untagged images by digest, unless an index could refer to them;
   - other tags stay;
   - `all` skips the step;
   - the role may delete only in `jaws`.

   Tests: Task 6, `test_it_keeps_the_newest_n_release_versions_by_semver`, `test_it_never_deletes_the_tag_just_published`, `test_untagged_images_stay_while_an_index_could_refer_to_them` and `test_each_publish_prunes_the_repository_with_the_push_role`; Task 4, `the_role_may_push_and_prune_that_repository_and_nothing_else`.

## Rulings

Calls this plan makes where the spec is silent, with the later plan that takes each up. Ruling 14 is the owner's decision of 2026-11-23. Rulings 5 (the 300 MiB budget), 9 (the `publish` environment), 11 (`JAWS_PUBLIC_IMAGE` set only once the alias is approved) and 15 (`Owner = Jaws-Platform`) stand as written.

1. **One `Dockerfile`, two targets.**
   - `generic` is the default; `jaws-cli` is `generic` plus `config/` and `datasets/`.
   - `jaws-cli` is built the way the hub's image will be (plan 06): `FROM <JAWS_PUBLIC_IMAGE>:vX.Y.Z@sha256:…`, then `COPY config/ /etc/jaws/config/` and `COPY datasets/ /etc/jaws/datasets/`.
   - The release builds each target in its own job, one per role.
2. **Tags cut before this plan.** Each has one image, with `config/` baked in. Re-published, it goes to `jaws-cli` as before, and never to ECR Public.
   - The `jaws-cli` job tells the two kinds of tag apart by the line `FROM generic AS jaws-cli` in the tag's `Dockerfile`.
   - The public job looks for a stage named `generic` instead. So it keeps working when cleanup (plan 07) removes the `jaws-cli` stage.
3. **Every stack ships,** the Databricks stacks included.
   - Their providers already come with the foundation's, so they add under 1 MiB. Plan 05 may then run Databricks plans inside the image (spec 6.4's third option); whether it does is plan 05's call.
   - No stack ships its `backend/` or `tests/`. A platform's runs write their backend from `state` (plan 05).
   - The helper scripts the platform's runs use today (`scripts/databricks-credentials.sh`, `scripts/data-access-sweep.sh`) are not in the image. Plan 05 adds what its runs need.
4. **Providers resolve at build time, as today.** Lock files stay out of the image.
   - Each stack's init takes the newest provider its constraints allow. Today that is one version of each provider, and CI fails if two appear.
   - The platform stacks may therefore run newer providers than `jaws`'s own CI, never older ones. Plan 07's acceptance plans would show any change a provider brings.
5. **The size budget stays, at 300 MiB rather than 250.**
   - Measured with this plan's `Dockerfile`: 283 MiB compressed for linux/amd64. The platform stacks add about 54 MiB: CI measures today's image, without them, at 229 MiB.
   - Spec 8 leaves the value to the builder.
   - Images stay linux/amd64 only, as today.
6. **Without a configuration, the CLI names where it looks.** That is the first thing a user of the public image sees.
7. **`release-infra/` reads nothing outside its folder,** since it outlives `config/` (spec 6.10, step 7).
   - It spells the account, the state bucket and the repository's IDs itself. Tests check them against `config/` while `config/` exists.
   - Plan 01 Task 3 has landed (#318), so those checks live in `tests/platform/test_release_infra.py` and read `PLATFORM_CONFIG_DIR`, as `tests/platform/test_state_backends.py` does. `tests/test_release_infra.py` checks the rest against nothing but the folder.
   - Plan 07 turns those checks into literals, and its owner-values guard exempts this folder.
8. **Its state prefix needs no foundation change.** IAM keeps every CI role out of `project=release-infra/`: `tfstate/read` and `tfstate/write` grant each role only its own state key.
   - The hardened bucket policy does not keep them out by itself. It exempts the bucket's admins, and the foundation's apply role is one of them; that role also holds `s3:PutBucketPolicy` (jaws-ci's `foundation/manage`). So only a reviewed foundation change could open the prefix, or, after takeover, a reviewed hub change.
   - A project registered under the key `release-infra` would get the prefix, which is tested.
9. **The role** comes from jaws-ci's `github-oidc-role`, with one inline policy.
   - Its name, `release-infra-publish`, stays outside `jaws-*`. The platform's apply role manages every `jaws-*` role, so after the split the hub could otherwise rewrite the vendor's role.
   - It trusts a new GitHub environment, `publish`, which only the public image job enters. `prod` also runs the 15-minute data-access sweep and the by-hand applies.
10. **The repository is a plain `aws_ecrpublic_repository`,** with `prevent_destroy`.
    - No module family has an ECR Public module. `owner-access/state.tf` is the precedent for plain resources in an owner-only root.
    - `prevent_destroy`, because every customer pins it.
11. **Two repository variables.**
    - `JAWS_PUBLISH_ROLE_ARN`, the role.
    - `JAWS_PUBLIC_IMAGE`, the address `public.ecr.aws/<alias>/jaws`. The alias is known only once AWS approves it. With the address in a variable, the role never reads it: its one read, `DescribeImages`, is for pruning.
    - With both unset, the public job skips with a notice. With only one set, or a malformed one, the check fails.
    - A third, `JAWS_PUBLIC_IMAGE_KEEP`, is optional (ruling 14). The check fails on a malformed one too, before the push.
12. **A published tag is never replaced,** because ECR Public has no tag immutability. An anonymous registry check runs before each push, so a re-publish only fills in a tag that is missing. A pruned tag counts as missing.
13. **The public job needs only Release Please,** not the account or the applies. So it needs no change when cleanup takes `config/` and the applies out of `jaws`.
14. **Every release publishes, and ECR Public keeps the newest ten until v1.** The owner's decision of 2026-11-23, verbatim: "Let's just start with a public ECR repository that we publish all new releases to and we only need to maintain like 10 versions during development and then we can update configs after cutting our first major release or something where we actually maintain all versions. There's no need to save really any of these development images while JAWS is pre-v1 release so we can just keep the last 10 or so with a config value that we eventually update to store all versions when we actually have consumers and establish maintenance and usage contracts with them of course to maintain all released versions."
    - **The prune.** ECR Public has no lifecycle policies, so the public job prunes after each publish, in a step run with the push role (Task 6).
      - It keeps the newest N release versions (`vX.Y.Z`) by semver, and the tag it just pushed wherever it falls.
      - It deletes the other versions by tag, and untagged images by digest. It leaves other tags alone.
    - **N** is the repository variable `JAWS_PUBLIC_IMAGE_KEEP`, default `10`.
      - `all` skips the step and keeps every version. The owner sets it at v1, once Jaws has consumers with maintenance contracts.
      - Anything but a whole number of at least 1, or `all`, fails the check before the push, and the script refuses it too.
    - **The role** gains `ecr-public:DescribeImages` and `ecr-public:BatchDeleteImage` on `jaws`, and nothing else. That widens spec 6.8's "may push to that repository and nothing else" to pushing and pruning, by the same decision.
    - **The selection is `scripts/prune_public_images.py`, not inline shell.** It is data logic: semver order, the tag just pushed, untagged images, the batch limit. Python states each rule directly, and unit tests feed it `describe-images` JSON with no AWS and no fake. Shell would need `jq` and `sort -V`, whose ordering and quoting are harder to read and to test. One test runs the step's remaining shell against a fake `aws`.
    - At today's pace, a version is pruned within about two days. That matters to the hub, not to this plan: see "For plan 06".
15. **The tags of `release-infra/`'s resources are Jaws's own:** `Organization` and `Owner` are `Jaws-Platform`, `Project` is `jaws`. The folder names no person.

## For plan 06: the retention risk

At today's pace, about 6 releases a day, keeping ten means a version is pruned within about two days.

- If the hub falls more than N releases behind, the base image its `Dockerfile` pins (`FROM public.ecr.aws/<alias>/jaws:vX.Y.Z@sha256:…`) is gone, and its next build fails. Every hub pull request and release builds the hub's image (spec 6.3), so the hub can't ship even a configuration change until it upgrades.
- Images it already built keep working: its own ECR repository holds their layers.
- Plan 06 chooses one of two remedies:
  1. **The hub gets an automatic upgrade PR on every Jaws release,** so it trails only by the PRs it hasn't merged. Plan 05 builds the upgrade-PR workflow (spec 9); this runs it on each release, not only on its schedule.
  2. **The hub mirrors its pinned base image into its own ECR repository,** and builds `FROM` the mirror, so pruning never reaches it.
- Until the hub exists nothing pins the public image, so nothing breaks before plan 06.

## Owner hand-off (after the PR merges)

Merging changes nothing in AWS. The next release pushes `jaws-cli` and skips the public image with a notice. Then, in this order:

1. **Create the GitHub environment `publish`** in `Jaws-Platform/jaws`, with its deployment branches set to `main` only.
   - Create it first. A job that names a missing environment creates it unprotected, and the publishing role trusts this environment.
   - Nothing enters `publish` before step 4.
2. **Apply `release-infra/`** with the production account's admin profile, `jaws-prod` (docs/owner-access.md):

   ```sh
   aws sso login --profile jaws-prod
   export AWS_PROFILE=jaws-prod
   cd release-infra
   terraform init -backend-config=backend/prod.hcl
   terraform plan -out=tfplan    # 3 to add: the repository jaws, the role, its inline policy
   terraform apply tfplan
   ```

3. **Request the registry alias `jaws`** in the ECR Public console (Public registry, Settings, Edit). AWS reviews it within a few days. If `jaws` is taken, pick another.
4. **Once the alias is approved and primary, set the two repository variables.** Setting them only then means the first public address is the one that lasts.
   - Refresh the state first. Step 2 recorded `repository_uri` under the registry's default alias.
   - Check that the address names the approved alias. If it still names the default one, stop: the alias isn't primary yet.

   ```sh
   terraform apply -refresh-only        # reads the repository's address under the primary alias
   terraform output -raw repository_uri # public.ecr.aws/<alias>/jaws, with the approved alias
   gh variable set JAWS_PUBLIC_IMAGE --body "$(terraform output -raw repository_uri)"
   gh variable set JAWS_PUBLISH_ROLE_ARN --body "$(terraform output -raw role_arn)"
   ```

   - Leave `JAWS_PUBLIC_IMAGE_KEEP` unset: each publish then keeps the newest ten release versions (ruling 14).

5. **Make the new check required:** run `scripts/apply-repo-settings.sh`.
6. **Watch the next release.** It publishes `public.ecr.aws/<alias>/jaws:<tag>`, its summary prints the address with the digest, and its prune step keeps the newest ten. Check the image anonymously with `docker pull`.
   - To publish the current release sooner, run the Release workflow with its tag. Its public job publishes the image.
   - Its `jaws-cli` job then fails on the tag that repository already holds, as re-publishing an existing tag always has (its tags are immutable).
7. **Later, at v1,** once Jaws has consumers and maintenance contracts with them, keep every version: `gh variable set JAWS_PUBLIC_IMAGE_KEEP --body all`. The prune step is then skipped, and storage grows by about 265 MB a release (Global Constraints, "Spending").

---

### Task 1: Without a configuration, the CLI says where it looks

**Files:**
- Modify: `src/jaws/settings.py`: a constant after `LOCAL_CONFIG_PATH`, and a check in `load_settings`
- Create: `tests/test_config_location.py`. It is a new file, not `tests/test_settings.py`: plan 02 appends to that one, and its email-like strings may trip the privacy hook.

**Interfaces:**
- Produces: `jaws.settings.NO_CONFIGURATION: str`.
  - It is built once, at import:

    ```python
    NO_CONFIGURATION = (
        f"no tool configuration: {ENV_CONFIG_PATH} is not set, and neither {IMAGE_CONFIG_PATH} "
        f"nor ./{LOCAL_CONFIG_PATH} exists. The Jaws image holds none of its own: run your "
        f"platform's image, which adds it at {IMAGE_CONFIG_PATH}, or set {ENV_CONFIG_PATH}"
    )
    ```

  - `load_settings(None, ...)` raises `ConfigError(NO_CONFIGURATION)` only when no configuration can be found: `JAWS_CONFIG` is unset, `IMAGE_CONFIG_PATH` isn't a directory, and `./config` doesn't exist.
  - A path that was given (`--config` or `JAWS_CONFIG`) and doesn't exist keeps today's message, "tool configuration not found at {path}". That holds for `JAWS_CONFIG=config` too, the default's own name.

- [ ] **Step 1: Write the failing tests** in `tests/test_config_location.py`

It imports `ConfigError` from `jaws.errors`, `NO_CONFIGURATION` and `load_settings` from `jaws.settings`, and `jaws.settings` itself, to patch `IMAGE_CONFIG_PATH`.

```python
def test_without_a_configuration_the_cli_says_where_it_looks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JAWS_CONFIG", raising=False)
    monkeypatch.setattr(jaws.settings, "IMAGE_CONFIG_PATH", tmp_path / "no-image-config")
    with pytest.raises(ConfigError) as raised:
        load_settings(environ={})
    assert str(raised.value) == NO_CONFIGURATION
    assert "JAWS_CONFIG" in NO_CONFIGURATION and "/etc/jaws/config" in NO_CONFIGURATION


@pytest.mark.parametrize("given", ["missing", "config"])
def test_a_configuration_given_but_missing_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, given: str
) -> None:
    """JAWS_CONFIG=config is a path given, though it is also the default's name."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JAWS_CONFIG", given)
    with pytest.raises(ConfigError, match=re.escape(f"tool configuration not found at {given}")):
        load_settings(environ={})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_config_location.py -v`
Expected: FAIL, because `NO_CONFIGURATION` can't be imported from `jaws.settings`.

- [ ] **Step 3: Add the constant and the check.** In `load_settings`, before reading the document, raise `ConfigError(NO_CONFIGURATION)` only when all three hold: no `path` was given and `JAWS_CONFIG` is unset; `IMAGE_CONFIG_PATH` isn't a directory; and `LOCAL_CONFIG_PATH` doesn't exist.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_config_location.py -v && uv run pytest -q && uv run mypy`
Expected: PASS. The whole suite runs without naming `tests/test_settings.py`, which the privacy hook may refuse.

- [ ] **Step 5: Commit**

```bash
git add src/jaws/settings.py tests/test_config_location.py
git commit -m "feat(cli): say where a configuration is looked for when none is found"
```

---

### Task 2: One `Dockerfile`, two images: `generic` and `jaws-cli`

**Files:**
- Modify: `Dockerfile`: the header comment, and stage 3, the runtime stage, which becomes `generic`, followed by the `jaws-cli` stage and the final stage
- Modify: `.github/workflows/release-please.yml`: the `workflow_dispatch` input's description, and the `image` job
- Modify: `.github/workflows/ci.yml`: the `image` job ("Image build and smoke test")
- Create: `tests/workflow_steps.py`, `tests/test_cli_image.py`
- Modify: `README.md`, in six places, each named in Step 7 by its section and wording. Line numbers drift as tasks land, so locate every edit by its content.

**Interfaces:**
- Consumes: `NO_CONFIGURATION` (Task 1), in the smoke step.
- Produces, in the `Dockerfile`:
  - `FROM python:${PYTHON_VERSION}-alpine AS generic`: today's runtime stage, without `COPY config /etc/jaws/config`;
  - `FROM generic AS jaws-cli`, with exactly `COPY config /etc/jaws/config` and `COPY datasets /etc/jaws/datasets`;
  - a last stage of only `FROM generic`, so a plain `docker build .` builds the generic image.
- Produces, in CI: `jaws:ci` (the default target) and `jaws:ci-cli` (`--target jaws-cli`).
- Produces, in the release's `image` job: a step `id: target` that writes `target=jaws-cli`, or `target=` for a tag without that stage. `docker/build-push-action` takes `target: ${{ steps.target.outputs.target }}`. An empty target means the `Dockerfile`'s last stage.
- Produces, in `tests/workflow_steps.py` (Tasks 4 to 6 use it too):
  - `WORKFLOWS = REPO_ROOT / ".github" / "workflows"`;
  - `def job(workflow: str, name: str) -> dict[str, Any]`;
  - `def uses(job: Mapping[str, Any], action: str) -> dict[str, Any]`: the job's one step whose `uses` starts with `action`;
  - `def run_step(workflow: str, job_name: str, step_id: str, *, cwd: Path, env: Mapping[str, str], fakes: Mapping[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], str]`.
    - It runs the step's `run` script with `bash -e -c` in `cwd`, as Actions does.
    - The environment is `os.environ` plus `env`, plus `GITHUB_OUTPUT` pointing at a fresh file under `cwd`.
    - Each `fakes` entry (name → script) becomes an executable in `cwd / ".bin"`, put first on `PATH`.
    - It returns the result and what the step wrote to `GITHUB_OUTPUT`.

    The pattern is `tests/test_jaws_action.py`'s `_resolve`.

- [ ] **Step 1: Write the failing tests** in `tests/test_cli_image.py`

The module docstring says this: there are two targets; `generic` is Jaws's image, with no configuration inside (spec 6.3); `jaws-cli` adds `config/` and `datasets/` where the CLI and the platform stacks look; the release builds `jaws-cli` for a tag that has the stage, and a tag cut before it gets its only image.

```python
DOCKERFILE = REPO_ROOT / "Dockerfile"
#: A tag cut before the generic image: one stage, config/ baked in (v0.80.1 and earlier).
OLD_DOCKERFILE = 'FROM python:3.13-alpine\nCOPY config /etc/jaws/config\nENTRYPOINT ["jaws"]\n'


def _stages() -> list[tuple[str, list[str]]]:
    """Each stage's FROM line and its instructions, continuation lines joined,
    comments and blank lines dropped."""


def _stage(name: str) -> list[str]:
    """The instructions of the stage whose FROM line ends in `AS <name>`."""


def test_the_default_target_is_the_generic_image() -> None:
    assert _stages()[-1] == ("FROM generic", [])


def test_the_generic_image_holds_no_configuration() -> None:
    assert not [
        i
        for i in _stage("generic")
        if "/etc/jaws" in i or i.split()[:2] in (["COPY", "config"], ["COPY", "datasets"])
    ]


def test_jaws_cli_adds_the_configuration_and_the_datasets_beside_it() -> None:
    """Where the CLI looks (IMAGE_CONFIG_PATH, and jaws.access.infra_root's datasets/)
    and where the foundation looks (local.datasets_path, beside its config_path)."""
    assert "FROM generic AS jaws-cli" in [line for line, _ in _stages()]
    assert _stage("jaws-cli") == [
        f"COPY config {IMAGE_CONFIG_PATH}",
        f"COPY datasets {IMAGE_CONFIG_PATH.parent / 'datasets'}",
    ]


@pytest.mark.parametrize(("dockerfile", "target"), [("current", "jaws-cli"), ("old", "")])
def test_the_jaws_cli_job_builds_jaws_cli_or_an_old_tag_s_only_image(
    tmp_path: Path, dockerfile: str, target: str
) -> None:
    text = DOCKERFILE.read_text() if dockerfile == "current" else OLD_DOCKERFILE
    (tmp_path / "Dockerfile").write_text(text)
    result, output = run_step(
        "release-please.yml", "image", "target", cwd=tmp_path, env={"TAG": "v0.76.0"}
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == [f"target={target}"]
    build = uses(job("release-please.yml", "image"), "docker/build-push-action")
    assert build["with"]["target"] == "${{ steps.target.outputs.target }}"
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_cli_image.py -v`
Expected: FAIL. There is no stage named `generic`, and the `image` job has no step `target`.

- [ ] **Step 3: Split the `Dockerfile`'s runtime stage** per the Interfaces.
  - The header comment names both targets and gives both build commands (with and without `--target jaws-cli`).
  - In `generic`, the `org.opencontainers.image.description` label becomes "Jaws: the CLI, a pinned Terraform and every stack, with their modules and providers vendored. A platform's image adds the platform's configuration."
    - It names no path: `_stages()` joins the `LABEL` into one instruction of `generic`, and `test_the_generic_image_holds_no_configuration` refuses any instruction there that holds `/etc/jaws`.
    - `jaws-cli` inherits the label, so it must be true of both images.
  - The `jaws-cli` stage's comment says three things: it is what today's callers run (the composite action pulls `jaws-cli:<tag>`); it has the shape of every platform's image; and it goes with `config/` at cleanup (spec 6.10, step 7).

- [ ] **Step 4: Point the release's `image` job at the target**
  - The job's name becomes `Publish jaws-cli (${{ needs.release-please.outputs.tag_name || inputs.tag }})`.
  - After the checkout, add a step named "Choose the target (jaws-cli, or the only image of a tag cut before it)", with `id: target`.
    - If `grep -qx 'FROM generic AS jaws-cli' Dockerfile`, it writes `target=jaws-cli`.
    - Otherwise it writes `target=`, and emits `::notice::$TAG predates the generic image: building its only image, config/ baked in, as before`.
  - `docker/build-push-action` takes `target: ${{ steps.target.outputs.target }}`.
  - The dispatch input's description becomes "Re-publish the images of an existing release tag (for example v0.76.0)".

- [ ] **Step 5: Build and smoke-test both images in CI's `image` job.** The job keeps its name, a required check.
  - After the step that reads the Terraform version (`id: config`), there are two `docker/build-push-action` steps, each with `push: false`, `load: true` and today's `build-args` (the terraform stage refuses an empty `TERRAFORM_VERSION`):
    - the generic image: no target, `tags: jaws:ci`, with today's `cache-from` and `cache-to`;
    - then `target: jaws-cli`, `tags: jaws:ci-cli`, `cache-from: type=gha`.
  - The smoke steps:

| Step name | Image | Passes when |
|---|---|---|
| Smoke test (the generic image holds no configuration) | `jaws:ci` | `docker run --rm --network none --entrypoint sh jaws:ci -c 'test ! -e /etc/jaws'` exits 0 |
| Smoke test (without a configuration, the CLI says where it looks) | `jaws:ci` | `docker run --rm --network none jaws:ci config show 2>&1` exits 2, and its output contains `JAWS_CONFIG` and `/etc/jaws/config`. The message is on stderr, hence `2>&1`. Wrap it in `set +e` and check both in one `[[ … ]]` that emits `::error::` |
| Smoke test (the jaws-cli image holds the configuration and the datasets where the CLI and the stacks look) | `jaws:ci-cli` | `test -f /etc/jaws/datasets/README.md && ls /etc/jaws/config/*.yaml` exits 0. The foundation refuses to plan without that README while Databricks is ready |
| Smoke test (validate a fixture site offline, inside the image) | `jaws:ci` | today's step, unchanged. Since #318 it mounts the neutral fixture configuration at `JAWS_CONFIG`, so it shows that the generic image works once it is given one |
| the Terraform-version and botocore smoke tests | `jaws:ci` | as today |

- [ ] **Step 6: Run the tests, then the smoke commands locally**

Run: `uv run pytest tests/test_cli_image.py tests/test_foundation_workflows.py -v`
Expected: PASS, every existing image test included.

Run:

```bash
TV=$(yq -r .terraform.version src/jaws/product.yaml)
docker build --build-arg "TERRAFORM_VERSION=$TV" -t jaws:ci .
docker run --rm --network none --entrypoint sh jaws:ci -c 'test ! -e /etc/jaws' && echo "no /etc/jaws"
docker run --rm --network none jaws:ci config show; echo "exit $?"
```

Expected: `no /etc/jaws`, then the `NO_CONFIGURATION` message and `exit 2`. Leave `--target jaws-cli` to CI if the privacy hook refuses it.

- [ ] **Step 7: Docs** (`README.md`)
  - **The CLI section** ("Jaws: the `jaws` CLI", the sentence "It ships as a versioned image in the account's private ECR repository (`jaws-cli`)"). It ships as two images, both built from the `Dockerfile` and pushed by each release:
    - the generic image, with no configuration, public at `public.ecr.aws/<alias>/jaws` (link to "Jaws's public image", which Task 5 writes);
    - `jaws-cli`, the same image with this repository's `config/` and `datasets/`, in the account's private ECR repository. Site repositories run `jaws-cli`.
  - **The build command** (the `docker build … -t jaws:local .` line in that section). It builds the generic image. Add the same command with `--target jaws-cli -t jaws-cli:local`.
  - **The `Dockerfile` row of the Layout table.** "The CLI images: `generic`, the default target (the CLI, a pinned Terraform, the stacks with modules and providers vendored, no configuration), and `jaws-cli`: `generic` plus `config/` at `/etc/jaws/config` and `datasets/` at `/etc/jaws/datasets`".
  - **The tool configuration** ("The tool configuration: `config/`"). Instead of "the image bakes it at `/etc/jaws/config`": "a platform's image holds it at `/etc/jaws/config` (`jaws-cli` holds this repository's; the generic image holds none)".
  - **The image check** (CI/CD's `Image build and smoke test` item). "builds both images, checks that the generic one holds no configuration and says where it looks for one, validates a fixture site offline inside it with the neutral fixture configuration mounted at `JAWS_CONFIG`, checks that `jaws-cli` holds the configuration and the datasets, checks the Terraform version and enforces the compressed-size budget".
  - **The release paragraph** ("Releases, applies and the image": "Merges to `main` accumulate in a Release Please PR…"). The `image` job builds the `jaws-cli` target; for a tag cut before it, the tag's only image.

- [ ] **Step 8: Commit**

```bash
git add Dockerfile .github/workflows/release-please.yml .github/workflows/ci.yml tests/workflow_steps.py tests/test_cli_image.py README.md
git commit -m "feat(cli): build a generic image and the jaws-cli image from one dockerfile"
```

---

### Task 3: Every stack ships in the image

**Files:**
- Modify: `Dockerfile`: in the `build` stage, the stack copies (`COPY stacks/site …`, `COPY stacks/bot …`), the init loop (`RUN for stack in site bot`) and their comment. The comment that the Databricks stacks are left out goes. The header comment's stack list, which Task 2 wrote, follows.
- Modify: `.dockerignore`
- Modify: `.github/workflows/ci.yml` (the `image` job: three smoke steps, and the budget)
- Modify: `tests/test_cli_image.py`
- Modify: `src/jaws/product.yaml` (the header comment), and `README.md` (the Layout table's `Dockerfile` row and CI/CD's `Image build and smoke test` item, as Task 2 left them)

**Interfaces:**
- Consumes: `_stage()` (Task 2); `jaws.stack.IMAGE_STACKS_ROOT` (`/opt/jaws/stacks`) and `IMAGE_PLUGIN_DIR` (`/opt/jaws/plugins`).
- Produces, in the `build` stage:
  - `COPY stacks /opt/jaws/stacks`, then one `COPY <stack> /opt/jaws/stacks/<stack>` for each of `foundation`, `monitoring` and `data-access`;
  - one `RUN for … in /opt/jaws/stacks/*/` loop, with today's body: `terraform init -backend=false`, `terraform providers mirror /opt/jaws/plugins`, removing `.terraform/providers`, and pruning `.git`, `examples`, `tests` and `docs` from `.terraform/modules`.
  - The image then holds `site`, `bot`, `databricks-account`, `databricks-workspace`, `foundation`, `monitoring` and `data-access` under `/opt/jaws/stacks`, every one of them initialized.
- Produces, in `.dockerignore`:
  - `foundation` comes out;
  - `tests` becomes `**/tests`;
  - `**/backend` goes in;
  - `**/.terraform.lock.hcl` stays, so each provider resolves once, at build time (ruling 4).
- Produces: `MAX_COMPRESSED_MB: "300"`.

**Measured** with this `Dockerfile`, by `docker save | gzip -1`:
- 283 MiB compressed for linux/amd64;
- the mirror holds one version each of aws, databricks, time and archive;
- every stack initializes offline and validates in the image;
- the Databricks stacks add under 1 MiB.

- [ ] **Step 1: Write the failing tests** in `tests/test_cli_image.py`

```python
#: The platform's own stacks, at the repository root; the project stacks are stacks/*.
PLATFORM_STACKS = ("foundation", "monitoring", "data-access")


def test_the_image_ships_every_stack_where_the_cli_looks() -> None:
    build = _stage("build")
    assert f"COPY stacks {IMAGE_STACKS_ROOT}" in build
    assert all(f"COPY {s} {IMAGE_STACKS_ROOT}/{s}" in build for s in PLATFORM_STACKS)
    loops = [i for i in build if i.startswith("RUN for ")]
    assert len(loops) == 1
    assert f"{IMAGE_STACKS_ROOT}/*/" in loops[0]
    assert f"terraform providers mirror {IMAGE_PLUGIN_DIR}" in loops[0]
    project_stacks = {p.name for p in (REPO_ROOT / "stacks").iterdir()}
    assert not set(PLATFORM_STACKS) & project_stacks, (
        "a platform stack would shadow a project stack"
    )


def test_the_build_context_keeps_backends_lock_files_and_stack_tests_out() -> None:
    """backend/prod.hcl names the owner's state bucket, and the stacks' tests/ hold
    fixtures generated from the owner's configuration: neither may reach the public image."""
    ignored = set((REPO_ROOT / ".dockerignore").read_text().split())
    assert {
        "**/backend",
        "**/tests",
        "**/.terraform",
        "**/.terraform.lock.hcl",
        "owner-access",
    } <= ignored
    assert not ignored & {"stacks", *PLATFORM_STACKS, "config", "datasets", "src"}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_cli_image.py -v`
Expected: the two new tests FAIL. `COPY stacks /opt/jaws/stacks` is missing, and `.dockerignore` still excludes `foundation`.

- [ ] **Step 3: Copy the stacks and initialize them all** per the Interfaces, then update `.dockerignore`.
  - The comment above the copies says three things:
    - every stack ships, without its backend (a platform's runs write their own from `state`) and without its tests;
    - lock files stay out, so each stack's init takes the newest provider its constraints allow, and the mirror holds each provider once (CI checks);
    - run-time init is offline, from the vendored modules and the mirror.
  - The header comment names every stack the image now holds.

- [ ] **Step 4: Add three smoke steps to CI's `image` job, and raise the budget.** The three go after "Smoke test (the image's Terraform is the release's, and the release file ships)" and before "Image size budget", so they run once both images are built.

| Step name | Passes when |
|---|---|
| Smoke test (every stack initializes offline and validates, as the CLI runs it) | in `jaws:ci` with `--network none`, for each `/opt/jaws/stacks/*/`: copy it to `mktemp -d`, then `terraform init -backend=false -input=false -no-color -plugin-dir=/opt/jaws/plugins`, then `terraform validate -no-color`. A failure emits `::error::<stack> …` |
| Smoke test (one version of each provider in the mirror) | `docker run --rm --network none --entrypoint find jaws:ci /opt/jaws/plugins -name '*.zip' \| xargs -n1 dirname \| sort \| uniq -d` prints nothing. Otherwise emit `::error::` naming the directories: "align the stacks' provider constraints" |
| Smoke test (the generic image ships no backend, stack test or state) | `find /opt/jaws/stacks -path '*/.terraform' -prune -o \( -name backend -o -name tests -o -name '*.tftest.hcl' -o -name '*.tfstate*' \) -print`, run in `jaws:ci`, prints nothing |
| Image size budget | `MAX_COMPRESSED_MB: "300"`. Its comment: what a consumer downloads; the aws provider archive alone is about 170 MB, and the platform stacks add about 54 MB. The step checks `jaws:ci` and `jaws:ci-cli` in a loop, and lists both sizes in the summary |

- [ ] **Step 5: Run the tests, then the amd64 build and its smoke commands locally**

Run: `uv run pytest tests/test_cli_image.py tests/test_versions.py -v`
Expected: PASS.

Run (under emulation on Apple Silicon, about 4 minutes):

```bash
docker build --platform linux/amd64 --build-arg "TERRAFORM_VERSION=$(yq -r .terraform.version src/jaws/product.yaml)" -t jaws:ci .
docker run --rm --network none --entrypoint find jaws:ci /opt/jaws/plugins -name '*.zip' | xargs -n1 dirname | sort | uniq -d
echo "$(( $(docker save jaws:ci | gzip -1 | wc -c) / 1024 / 1024 )) MiB"
```

Expected: no duplicate, and about 283 MiB. Then run the offline init-and-validate loop and the leak check from Step 4: every stack passes, and nothing is found.

- [ ] **Step 6: Docs**
  - **`src/jaws/product.yaml`'s header:** the image vendors the modules of every stack it ships, `stacks/*` and the platform's `foundation/`, `monitoring/` and `data-access/`.
  - **`README.md`, the Layout table's `Dockerfile` row:** the generic image holds every stack: `stacks/*` and the platform's own, without backends.
  - **`README.md`, CI/CD's `Image build and smoke test` item:** add "initializes and validates every stack inside it offline, checks the mirror holds one version of each provider, and that no backend or stack test ships"; the budget is 300 MiB.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile .dockerignore .github/workflows/ci.yml tests/test_cli_image.py src/jaws/product.yaml README.md
git commit -m "feat(cli): ship every stack in the image, the platform's own included"
```

---

### Task 4: `release-infra/`, the ECR Public repository and the role that publishes to it

**Files:**
- Modify: `commitlint.config.mjs` (`SCOPES`), `CONTRIBUTING.md` (the "Scopes" table), `tools/commitlint/scopes.test.mjs`
- Create in `release-infra/`: `versions.tf`, `providers.tf`, `backend.tf`, `main.tf`, `outputs.tf`, `README.md`, `.terraform.lock.hcl` (from `terraform init`), `backend/prod.hcl` and `tests/release_infra.tftest.hcl`
- Create: `tests/test_release_infra.py`, and `tests/platform/test_release_infra.py` for its checks against `config/`
- Modify: `tests/workflow_steps.py` (three helpers), `tests/platform/test_owner_rules.py` (the reserved keys)
- Modify: `.github/workflows/ci.yml` (a `release-infra-stack` job after `billing-export-stack`), `scripts/apply-repo-settings.sh` (the required checks), `.pre-commit-config.yaml` (a pre-push hook; `release-infra` added to the pytest hook's `files`), `.dockerignore`
- Modify: `tests/test_versions.py` (`_stack_files`), `tests/test_hooks.py` (`expected`, in `test_the_slow_checks_run_before_a_push`)
- Modify: `AGENTS.md` (the rule "Shared modules come from the Terraform Registry", the "Before opening a PR" checklist, the `owner-access/` paragraph, and "Things that need the owner"); `README.md` ("Shared modules from the Terraform Registry", and the Layout table); `CONTRIBUTING.md` ("Local setup" and "Updating the shared modules"); `src/jaws/product.yaml` (the header comment)

**Interfaces:**
- Produces: the scope `publishing`, after `monitoring` in `SCOPES`. Its value is the plain string "release-infra/: Jaws's ECR Public repository and the role that publishes the image to it", like its neighbours. CONTRIBUTING's table gets the row after `monitoring`'s: `` | `publishing` | `release-infra/`: Jaws's ECR Public repository and the role that publishes the image to it | ``.
- Produces, in `release-infra/main.tf`:
  - `local.account_id`: the production account, copied from `aws.accounts[aws.primary].account_id`.
  - `local.repository = { name = "Jaws-Platform/jaws", owner_id = "…", repository_id = "…" }`, with the IDs copied from `platform.repositories[0]`, quoted.
  - `local.environment = "publish"`.
  - `data "aws_caller_identity" "current"`, with a postcondition. The condition is `self.account_id == local.account_id`. The error message is "These credentials belong to account ${self.account_id}, but Jaws's release infrastructure lives in the production account, ${local.account_id}: apply it with the owner's admin profile there (release-infra/README.md)." Mark it `# tflint-ignore: terraform_unused_declarations`, as in `billing-export/config.tf`.
  - `data "aws_iam_openid_connect_provider" "github"`, with `url = "https://token.actions.githubusercontent.com"`.
  - `resource "aws_ecrpublic_repository" "jaws"`:
    - `repository_name = "jaws"`;
    - `catalog_data` holds a one-line `description` and a `usage_text`: pin a release by tag and digest in your platform's `Dockerfile`, and add `config/` at `/etc/jaws/config/` and `datasets/` at `/etc/jaws/datasets/`. It also holds `architectures = ["x86-64"]` and `operating_systems = ["Linux"]`;
    - `lifecycle { prevent_destroy = true }`.
  - `module "publish_role"`, from `Jaws-Platform/jaws-ci/aws//modules/github-oidc-role`, with `version` on the line after `source`:
    - `name = "release-infra-publish"`;
    - `description = "Pushes the Jaws image to the ECR Public repository jaws and prunes its old versions, for Jaws-Platform/jaws release runs (environment publish)"`;
    - `repository`, `owner_id` and `repository_id` from `local.repository`;
    - `subjects = ["environment:${local.environment}"]`;
    - `oidc_provider_arn = data.aws_iam_openid_connect_provider.github.arn`;
    - `component = "publishing"`;
    - `inline_policies = { push = local.push_policy }`.
  - `local.push_policy` has three statements, nothing else:
    - `LogInToEcrPublic` allows `["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"]` on `"*"`. Neither action takes a resource, and neither grants anything by itself.
    - `PushTheJawsImage` allows `["ecr-public:BatchCheckLayerAvailability", "ecr-public:InitiateLayerUpload", "ecr-public:UploadLayerPart", "ecr-public:CompleteLayerUpload", "ecr-public:PutImage"]` on `aws_ecrpublic_repository.jaws.arn`.
    - `PruneTheJawsImage` allows `["ecr-public:DescribeImages", "ecr-public:BatchDeleteImage"]` on `aws_ecrpublic_repository.jaws.arn`: exactly what Task 6's prune step calls, on that one repository (ruling 14).
- Produces, in `release-infra/providers.tf`: `region = "us-east-1"`, with the comment "ECR Public's API is in us-east-1 only". Its `default_tags` are `module.context.tags`.
- Produces `module "context"`, from `Jaws-Platform/jaws-foundation/aws//modules/context`, with literal inputs:
  - `organization = "Jaws-Platform"`, `project = "jaws"`, `environment = "prod"`;
  - `repository = "Jaws-Platform/jaws"`, `owner = "Jaws-Platform"`;
  - `name_root = "jaws"`, `managed_by = "JAWS"`.
- Produces, in `release-infra/versions.tf`: `required_version = ">= 1.11, < 2.0"`, and aws `~> 6.0`.
- Produces `release-infra/backend/prod.hcl`, in `foundation/backend/prod.hcl`'s format:
  - `bucket` is `state.bucket`;
  - `key = "project=release-infra/env=prod/release-infra-prod.tfstate"`;
  - `region = "us-east-1"`, `use_lockfile = true`, `encrypt = true`.
- Produces the outputs:
  - `repository_uri` is `aws_ecrpublic_repository.jaws.repository_uri`. Its description: the address `public.ecr.aws/<alias>/jaws`, which is the variable `JAWS_PUBLIC_IMAGE`;
  - `role_arn` is `module.publish_role.arn`. Its description: the variable `JAWS_PUBLISH_ROLE_ARN`.
- Produces, in `tests/workflow_steps.py`, three helpers, so the new tests call what the older ones copy. The older tests stay as they are.
  - `def hcl_values(path: Path) -> dict[str, str]`: a backend file's `key = "value"` lines, parsed as `tests/platform/test_foundation_backend.py` parses them.
  - `def required_checks() -> set[str]`: the contexts `scripts/apply-repo-settings.sh` requires, found as `test_the_monitoring_checks_are_required` (`tests/test_monitoring_workflows.py`) finds them.
  - `def workflows_that_only_check(root: str) -> list[str]`: the sorted names of the workflows that name `root`. It fails if a job naming it holds `id-token`, uses `configure-aws-credentials` or runs `terraform plan|apply|destroy`, as `test_ci_never_plans_or_applies_billing_export` (`tests/test_billing_export.py`) checks.
- For Tasks 5 and 6: the environment `publish`, the variables `JAWS_PUBLISH_ROLE_ARN` and `JAWS_PUBLIC_IMAGE`, and the role's `PruneTheJawsImage` statement.

- [ ] **Step 1: Add the scope, test first**

In `tools/commitlint/scopes.test.mjs`:

```js
test("release-infra/ has its own scope, publishing (spec 6.12)", () => {
  assert.match(SCOPES.publishing ?? "", /release-infra\//);
});
```

Run: `npm run test:commitlint`
Expected: FAIL. Add the scope and its CONTRIBUTING row, then run it again.
Expected: PASS, with "CONTRIBUTING.md lists exactly the configured scopes, in order" among the passes.

```bash
git add commitlint.config.mjs CONTRIBUTING.md tools/commitlint/scopes.test.mjs
git commit -m "chore(repo): add the publishing scope for release-infra/"
```

- [ ] **Step 2: Write the failing tests**

`release-infra/tests/release_infra.tftest.hcl` opens as `billing-export/tests/billing_export.tftest.hcl` does. It has `mock_provider "aws"` with `override_during = plan`, and these mocks, all using `local.account_id`'s literal:
- `mock_data "aws_caller_identity"`: `account_id`;
- `mock_data "aws_iam_openid_connect_provider"`: `arn = "arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com"`;
- `mock_resource "aws_ecrpublic_repository"`: `arn = "arn:aws:ecr-public::<account>:repository/jaws"` and `repository_uri = "public.ecr.aws/example-alias/jaws"`.

Its runs, each `command = plan`:

```hcl
run "the_role_may_push_and_prune_that_repository_and_nothing_else" {
  command = plan

  assert {
    condition = jsonencode(jsondecode(module.publish_role.inline_policies["push"].policy).Statement) == jsonencode([
      { Sid = "LogInToEcrPublic", Effect = "Allow", Action = ["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"], Resource = "*" },
      { Sid = "PushTheJawsImage", Effect = "Allow", Action = ["ecr-public:BatchCheckLayerAvailability", "ecr-public:InitiateLayerUpload", "ecr-public:UploadLayerPart", "ecr-public:CompleteLayerUpload", "ecr-public:PutImage"], Resource = aws_ecrpublic_repository.jaws.arn },
      { Sid = "PruneTheJawsImage", Effect = "Allow", Action = ["ecr-public:DescribeImages", "ecr-public:BatchDeleteImage"], Resource = aws_ecrpublic_repository.jaws.arn },
    ])
    error_message = "the role logs in to ECR Public, pushes to the repository jaws and prunes it, and may do nothing else"
  }

  assert {
    condition     = length(module.publish_role.inline_policies) == 1 && length(module.publish_role.managed_policy_arns) == 0 && length(module.publish_role.managed_policies) == 0
    error_message = "one inline policy, and no managed policy"
  }
}

run "trusts_only_this_repository_s_publish_environment" {
  command = plan

  assert {
    condition = jsondecode(module.publish_role.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == [
      "repo:${local.repository.name}:environment:publish",
      "repo:${split("/", local.repository.name)[0]}@${local.repository.owner_id}/${split("/", local.repository.name)[1]}@${local.repository.repository_id}:environment:publish",
    ]
    error_message = "only Jaws-Platform/jaws's publish environment may assume the role, in both subject forms"
  }

  assert {
    condition     = !can(jsondecode(module.publish_role.assume_role_policy).Statement[0].Condition.StringLike) && module.publish_role.name == "release-infra-publish"
    error_message = "no wildcard subject, and the role keeps its name, outside jaws-*"
  }
}
```

Then add:
- `publishes_one_repository_named_jaws`. It asserts:
  - `aws_ecrpublic_repository.jaws.repository_name == "jaws"`;
  - the catalog's architectures are `x86-64` and its operating systems `Linux`;
  - `output.repository_uri == "public.ecr.aws/example-alias/jaws"`.
- `refuses_credentials_of_another_account`. It overrides `data.aws_caller_identity.current` to account `111122223333`, with `expect_failures = [data.aws_caller_identity.current]`.
- `is_tagged_as_jaws_s_own`. It asserts that `jsonencode(module.context.tags)` is the Interfaces' tag set.

`tests/test_release_infra.py` follows `tests/test_billing_export.py`, and reads no `config/`. Its docstring says:
- it covers the ECR Public repository and the one role that pushes to it and prunes it, in the production account (spec 6.8, ruling 14), applied only by the owner;
- no workflow assumes a role for it, and no foundation role or state prefix names it;
- a project registered under its key would get its state prefix;
- it reads nothing outside its folder, since it stays in `jaws` when `config/` leaves;
- its checks against the owner's values are in `tests/platform/test_release_infra.py`.

```python
RESERVED = "release-infra"
ROOT = REPO_ROOT / RESERVED


def test_no_project_is_registered_under_the_release_infra_key() -> None:
    """The fixture's registry; tests/platform/test_owner_rules.py checks the owner's."""
    assert RESERVED not in onboarded(repo_config()), (
        f"`{RESERVED}` is reserved: its CI roles would get the publishing infrastructure's state"
    )


def test_its_state_has_its_own_prefix() -> None:
    values = hcl_values(ROOT / "backend" / "prod.hcl")
    assert values["key"] == f"project={RESERVED}/env=prod/{RESERVED}-prod.tfstate"
    assert values["region"] == "us-east-1"
    assert sorted(p.name for p in (ROOT / "backend").iterdir()) == ["prod.hcl"]


def test_ci_never_plans_or_applies_release_infra() -> None:
    assert workflows_that_only_check(RESERVED) == ["ci.yml"]


def test_its_ci_check_is_required() -> None:
    check = "Release infrastructure validate, tflint, test"
    assert job("ci.yml", "release-infra-stack")["name"] == check
    assert check in required_checks()
```

Then add:
- `test_no_foundation_role_or_state_prefix_names_release_infra`: no `foundation/*.tf` holds `project=release-infra` or `release-infra`.
- `test_it_reads_nothing_outside_its_folder`: no `release-infra/*.tf` holds `../`.
- `test_it_never_enters_the_image`: `"release-infra"` is a line of `.dockerignore`.

`tests/platform/test_release_infra.py` holds the checks against `config/`, which only `tests/platform/` may read. Its docstring: `release-infra/` spells the owner's values itself (spec 6.8), so check them against `config/` while it exists; each failure names the field, never the value.

```python
def test_its_state_is_in_the_platform_s_state_bucket() -> None:
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    if hcl_values(ROOT / "backend" / "prod.hcl")["bucket"] != settings.state.bucket:
        pytest.fail(
            "release-infra/backend/prod.hcl does not name config/'s state.bucket", pytrace=False
        )
```

`ROOT` comes from `tests/test_release_infra.py`. Then add, each failing the same way:
- `test_it_is_in_the_primary_account`: the one `account_id = "…"` in `main.tf` is the primary account's.
- `test_it_trusts_this_repository`: the `name`, `owner_id` and `repository_id` inside `local.repository` are `platform.repositories[0]`'s `repository`, `owner_id` and `repository_id`. Match them inside `local.repository`: `module "context"` spells `Jaws-Platform/jaws` too.
- `test_the_publishing_role_is_outside_the_platform_s_name_root`. The module's `name` is `release-infra-publish` and doesn't start with `f"{settings.context.name_root}-"`. Its docstring: the foundation's apply role manages every `<name_root>-*` role (jaws-ci's `foundation/manage`).

In `tests/platform/test_owner_rules.py`, `test_no_project_takes_a_reserved_key` gains `RELEASE_INFRA`, imported as its neighbours are: `from tests.test_release_infra import RESERVED as RELEASE_INFRA`.

In `tests/test_versions.py`, `_stack_files()` also yields `REPO_ROOT / "release-infra"`'s `*.tf`. In `tests/test_hooks.py`, `expected` gains `"terraform-test-release-infra": "cd release-infra"`.

- [ ] **Step 3: Run them and watch them fail**

Run: `(cd release-infra && terraform init -backend=false && terraform test) ; uv run pytest tests/test_release_infra.py tests/platform/test_release_infra.py tests/platform/test_owner_rules.py tests/test_versions.py tests/test_hooks.py -v`
Expected: FAIL. `release-infra/` holds only its test, and there's no hook, job or ignore entry yet.

- [ ] **Step 4: Write the root** per the Interfaces, then `terraform init -backend=false` to create its lock file. `release-infra/README.md` follows `billing-export/README.md` and has these sections:
  - **What it is**: the repository, the role, the account, and why it's the vendor's (spec 6.8).
  - **The owner's root**: the guards, and where the state is. What keeps CI out of the state is IAM, not the bucket policy, which exempts the foundation's apply role (ruling 8).
  - **Run it**: this plan's owner hand-off, steps 1–5.
  - **Changing it**:
    - the role's name stays outside `jaws-*`;
    - the role may push and prune, and nothing else (ruling 14);
    - the repository holds every release customers pin, so it is never destroyed or renamed;
    - jaws-ci's version moves with the family (`tests/test_versions.py`).
  - **Locally, with no credentials**: `terraform init -backend=false && terraform test`.

- [ ] **Step 5: Wire it in**
  - `.github/workflows/ci.yml` gets a `release-infra-stack` job, named "Release infrastructure validate, tflint, test": `billing-export-stack`'s job with `release-infra` in place of `billing-export`. Its comment says it is never planned or applied by CI, by design.
  - `scripts/apply-repo-settings.sh` gets `{ "context": "Release infrastructure validate, tflint, test" }`, after the billing export's.
  - `.pre-commit-config.yaml` gets `terraform-test-release-infra`: `billing-export`'s hook with `files: ^release-infra/`.
  - `.dockerignore` gets `release-infra`.

- [ ] **Step 6: Run them and watch them pass**

Run: `terraform fmt -check -recursive && (cd release-infra && terraform validate && terraform test) && tflint --init && tflint --recursive`
Expected: PASS, with 5 runs passed.

Run: `uv run pytest -q && npm test`
Expected: PASS. `tests/test_owner_access.py` and `tests/test_billing_export.py` pass unchanged, and so does `tests/platform/`, the isolation check and the owner-values guard included.

- [ ] **Step 7: Docs**
  - **`AGENTS.md`:**
    - the bump list in the rule "Shared modules come from the Terraform Registry", and `src/jaws/product.yaml`'s header list, gain `release-infra/`;
    - the "Before opening a PR" checklist gains `(cd release-infra && terraform init -backend=false && terraform validate && terraform test)`, after `billing-export`'s line;
    - the `owner-access/` paragraph ("**`owner-access/` is the owner's stack.**") gains: "**`release-infra/` is the owner's too:** Jaws's release infrastructure, the ECR Public repository `jaws` and the role that pushes the image to it and prunes it, in the production account. The same rules hold: no CI role, workflow or state prefix names it, and its role's name stays outside `jaws-*` (`tests/test_release_infra.py` checks). IAM keeps the CI roles out of its state; the bucket policy exempts the foundation's apply role, so only a reviewed foundation change could open it. Its repository is a plain `aws_ecrpublic_repository`, since no module family has one";
    - "Things that need the owner" gains applying `release-infra/`, the ECR Public registry alias, and the `publish` environment.
  - **`README.md`:**
    - in "Shared modules from the Terraform Registry", the rows for `jaws-ci` (add `github-oidc-role`, the publishing role) and `jaws-foundation` gain `release-infra/`, and so does the pin sentence ("Every pin of a family (in `foundation/` …");
    - a Layout row: `release-infra/` (root), "Jaws's release infrastructure: the ECR Public repository `jaws` and the role that publishes the image to it, applied only by the owner, never by CI ([release-infra/README.md](release-infra/README.md))".
  - **`CONTRIBUTING.md`:** `release-infra/` joins the pre-push list ("Local setup") and the bump list ("Updating the shared modules").

- [ ] **Step 8: Commit**

```bash
git add release-infra tests/test_release_infra.py tests/platform/test_release_infra.py tests/platform/test_owner_rules.py tests/workflow_steps.py tests/test_versions.py tests/test_hooks.py .github/workflows/ci.yml scripts/apply-repo-settings.sh .pre-commit-config.yaml .dockerignore AGENTS.md README.md CONTRIBUTING.md src/jaws/product.yaml
git commit -m "feat(publishing): add the ecr public repository jaws and the role that publishes to it"
```

---

### Task 5: Releases publish the generic image to ECR Public

**Files:**
- Modify: `.github/workflows/release-please.yml` (two jobs after `image`)
- Create: `tests/test_public_image.py`
- Modify: `tests/test_workflow_roles.py` (its docstring) and `tests/test_foundation_workflows.py` (one test's name), which the public job makes untrue
- Modify: `README.md` (a section "Jaws's public image" after "Reusable workflows for site repositories"; in CI/CD, the release paragraph and the paragraph "No role ARN is a secret, …"; and "Owner hand-off"), `CONTRIBUTING.md` ("Releases", step 3)

**Interfaces:**
- Consumes:
  - the `generic` target (Task 2);
  - the environment `publish` and the variables `JAWS_PUBLISH_ROLE_ARN` and `JAWS_PUBLIC_IMAGE` (Task 4);
  - `job`, `uses` and `run_step` from `tests/workflow_steps.py` (Task 2).
- Produces, in `release-please.yml`:
  - **`public-image-check`**, named "Public image check":
    - `needs: release-please`, and the `account` job's `if`, character for character after whitespace;
    - `permissions: { contents: read }`, and no environment;
    - `outputs.publish: ${{ steps.decide.outputs.publish }}`;
    - `env`: `TAG` (as in the `image` job), `ROLE_ARN: ${{ vars.JAWS_PUBLISH_ROLE_ARN }}`, `IMAGE: ${{ vars.JAWS_PUBLIC_IMAGE }}` and `KEEP: ${{ vars.JAWS_PUBLIC_IMAGE_KEEP }}`. `KEEP` is checked here, so that a malformed one fails before anything is pushed; Task 6 prunes with it;
    - steps: check out `refs/tags/<tag>`, then `id: decide`.
  - **`public-image`**, named `Publish the public image (<tag>)`:
    - `needs: [release-please, public-image-check]`;
    - `if: "!cancelled() && needs.public-image-check.outputs.publish == 'true'"`, quoted on one line: unquoted, a leading `!` is a YAML tag, which `yaml.safe_load` refuses, and the test compares the parsed string exactly;
    - `environment: { name: publish }`;
    - `permissions: { contents: read, id-token: write }`;
    - `env`: `TAG`, and `IMAGE: ${{ vars.JAWS_PUBLIC_IMAGE }}`.

    Its steps, in order:
    1. check out the tag;
    2. read the Terraform version from `src/jaws/product.yaml`, as CI's step does;
    3. `configure-aws-credentials`, with `role-to-assume: ${{ vars.JAWS_PUBLISH_ROLE_ARN }}`, `aws-region: us-east-1` (commented: ECR Public's API is in us-east-1 only) and `role-session-name: gha-public-image-<tag>`;
    4. `amazon-ecr-login`, with `registry-type: public`;
    5. `setup-buildx`;
    6. `build-push-action`, with `id: build`, `target: generic`, `push: true`, `platforms: linux/amd64`, `provenance: false`, `tags: ${{ env.IMAGE }}:${{ env.TAG }}` and the Terraform build-arg;
    7. a summary step that writes `` `$IMAGE:$TAG@$DIGEST` ``, the pin customers use, from `steps.build.outputs.digest`.

    Task 6 adds the prune step after the summary.
- Neither job names `release-infra`, not even in a comment: `tests/test_release_infra.py` allows only `ci.yml` to.

The `decide` step is the algorithm the jobs depend on. Write it as this:

```bash
publish() { echo "publish=$1" >> "$GITHUB_OUTPUT"; }
if [[ -z "$ROLE_ARN$IMAGE" ]]; then
  echo "::notice::not publishing the public image: JAWS_PUBLISH_ROLE_ARN and JAWS_PUBLIC_IMAGE are not set (README.md, \"Jaws's public image\")"
  publish false; exit 0
fi
[[ "$ROLE_ARN" =~ ^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_-]+$ ]] || { echo "::error::JAWS_PUBLISH_ROLE_ARN is not an IAM role ARN: '$ROLE_ARN'"; exit 1; }
[[ "$IMAGE" =~ ^public\.ecr\.aws/[a-z0-9][a-z0-9._-]*/jaws$ ]] || { echo "::error::JAWS_PUBLIC_IMAGE is not public.ecr.aws/<alias>/jaws: '$IMAGE'"; exit 1; }
[[ -z "$KEEP" || "$KEEP" =~ ^([1-9][0-9]*|all)$ ]] || { echo "::error::JAWS_PUBLIC_IMAGE_KEEP is neither a whole number of at least 1 nor all: '$KEEP'"; exit 1; }
if ! grep -Eq '^FROM [^ ]+ AS generic$' Dockerfile; then
  echo "::notice::$TAG predates the generic image: its only image bakes config/ in, and is never published"
  publish false; exit 0
fi
repository=${IMAGE#public.ecr.aws/}
token=$(curl -fsS "https://public.ecr.aws/token/?service=public.ecr.aws&scope=repository:$repository:pull" | jq -r .token)
code=$(curl -s -o /dev/null -w '%{http_code}' -I -H "Authorization: Bearer $token" -H "Accept: $MANIFEST_TYPES" "https://public.ecr.aws/v2/$repository/manifests/$TAG")
case "$code" in
  404) publish true ;;
  200) echo "::notice::$IMAGE:$TAG is already published: a published tag is never replaced"; publish false ;;
  *) echo "::error::could not tell whether $IMAGE:$TAG is published (HTTP $code from public.ecr.aws)"; exit 1 ;;
esac
```

`MANIFEST_TYPES` is a step `env`: `application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json`. These anonymous calls were checked against `public.ecr.aws/lambda/python`: 200 for an existing tag, 404 for a missing one.

- [ ] **Step 1: Write the failing tests** in `tests/test_public_image.py`

The module docstring says: the generic image goes to ECR Public with the publishing role, only from the `publish` environment, never for a tag cut before it, never over a tag already published, and not at all until the owner has set the two variables. `DOCKERFILE` and `OLD_DOCKERFILE` come from `tests/test_cli_image.py`. `_decide` passes `fakes={"curl": FAKE_CURL}`, and puts `FAKE_LOG`, `FAKE_HTTP_CODE` and any `MANIFEST_TYPES` in the step's environment. `decide` runs the real `jq`, so every test that runs it carries `needs_yq` from `tests/test_databricks_workflows.py`, which requires `jq` too.

```python
NEUTRAL = {
    "ROLE_ARN": "arn:aws:iam::123456789012:role/release-infra-publish",
    "IMAGE": "public.ecr.aws/example-alias/jaws",
    "KEEP": "",
    "TAG": "v0.81.0",
}
#: Stands in for curl: logs each call, answers the token request, and prints
#: FAKE_HTTP_CODE for the manifest request.
FAKE_CURL = """#!/usr/bin/env bash
echo "curl $*" >> "$FAKE_LOG"
case "$*" in
  */token/*) echo '{"token": "anonymous"}' ;;
  *) printf '%s' "$FAKE_HTTP_CODE" ;;
esac
"""


def _decide(
    tmp_path: Path, dockerfile: str, code: str = "404", **env: str
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    """Run the check job's decide step in a checkout holding `dockerfile`; the result,
    what it wrote to GITHUB_OUTPUT, and the curl calls it made."""


def test_a_new_tag_is_published(tmp_path: Path) -> None:
    result, output, calls = _decide(tmp_path, DOCKERFILE.read_text())
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == ["publish=true"]
    assert "scope=repository:example-alias/jaws:pull" in calls
    assert "https://public.ecr.aws/v2/example-alias/jaws/manifests/v0.81.0" in calls


def test_without_the_variables_publishing_is_skipped_with_a_notice(tmp_path: Path) -> None:
    result, output, calls = _decide(tmp_path, DOCKERFILE.read_text(), ROLE_ARN="", IMAGE="")
    assert result.returncode == 0
    assert "::notice::" in result.stdout and "JAWS_PUBLISH_ROLE_ARN" in result.stdout
    assert output.splitlines() == ["publish=false"] and calls == ""


@pytest.mark.parametrize(
    ("overrides", "named"),
    [
        ({"IMAGE": ""}, "JAWS_PUBLIC_IMAGE"),
        ({"ROLE_ARN": ""}, "JAWS_PUBLISH_ROLE_ARN"),
        ({"ROLE_ARN": "release-infra-publish"}, "JAWS_PUBLISH_ROLE_ARN"),
        ({"IMAGE": "public.ecr.aws/example-alias/jaws-cli"}, "JAWS_PUBLIC_IMAGE"),
        ({"KEEP": "ten"}, "JAWS_PUBLIC_IMAGE_KEEP"),
    ],
)
def test_a_half_set_or_malformed_variable_fails_the_check(
    tmp_path: Path, overrides: dict[str, str], named: str
) -> None:
    result, output, _ = _decide(tmp_path, DOCKERFILE.read_text(), **overrides)
    assert result.returncode != 0 and f"::error::{named}" in result.stdout and output == ""
```

Then add:
- `test_a_tag_without_the_generic_image_is_never_published`. With `OLD_DOCKERFILE` as the `Dockerfile`, the step emits a notice and `publish=false`, and makes no curl call.
- `test_a_published_tag_is_never_replaced`. With code `200`, the step emits a notice containing "never replaced", and `publish=false`.
- `test_a_registry_error_stops_the_publish`. With code `503`, the step exits nonzero with `::error::`, and writes nothing.
- `test_the_public_image_is_the_generic_target_pushed_under_the_tag`. The `docker/build-push-action` step has `target == "generic"`, `push is True`, `platforms == "linux/amd64"`, `provenance is False` and `tags == "${{ env.IMAGE }}:${{ env.TAG }}"`. One platform and no provenance make the image one manifest, with no untagged images beside it, which Task 6's prune counts on.
- `test_it_is_pushed_with_the_publishing_role_alone`. It checks:
  - the environment's name is `publish`, and the permissions are `{"contents": "read", "id-token": "write"}`;
  - `role-to-assume == "${{ vars.JAWS_PUBLISH_ROLE_ARN }}"` and `aws-region == "us-east-1"`;
  - the ECR login has `registry-type == "public"`;
  - `env["IMAGE"] == "${{ vars.JAWS_PUBLIC_IMAGE }}"`.
- `test_it_needs_no_configuration_and_no_apply`. `public-image`'s `needs == ["release-please", "public-image-check"]`, and the check job's `needs == "release-please"`.
- `test_the_public_job_runs_only_when_the_check_says_so`. It checks:
  - `public-image`'s `if` is exactly `!cancelled() && needs.public-image-check.outputs.publish == 'true'`;
  - the check job has no `environment`, and `permissions == {"contents": "read"}`;
  - its `if` equals the `account` job's, after whitespace is normalized;
  - its `env` is exactly `TAG`, `ROLE_ARN`, `IMAGE` and `KEEP`, each mapped as the Interfaces say. `run_step` injects those names itself, so only this catches a misnamed key, which would otherwise show only once the owner sets the variables.
- `test_only_the_public_image_job_enters_publish_or_takes_the_publishing_role`. Across `.github/workflows/*.yml`:
  - the only job whose environment is `publish` is `("release-please.yml", "public-image")`;
  - `vars.JAWS_PUBLISH_ROLE_ARN` appears only in `release-please.yml`, in those two jobs.

Two existing tests become untrue, though both still pass. Reword them to name the one exception, the public job's `vars.JAWS_PUBLISH_ROLE_ARN` (spec 6.8):
- `tests/test_workflow_roles.py`'s docstring, "Every workflow builds its roles from the tool's reading of its configuration (config/)";
- `test_the_tools_own_workflows_take_no_role_from_a_repository_variable` (`tests/test_foundation_workflows.py`), which becomes `test_the_tools_own_workflows_take_no_plan_or_apply_role_from_a_repository_variable`, with a docstring naming the exception.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_public_image.py -v`
Expected: FAIL with `KeyError: 'public-image-check'`.

- [ ] **Step 3: Add the two jobs** per the Interfaces.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_public_image.py tests/test_foundation_workflows.py tests/test_release_infra.py tests/test_workflow_roles.py -v`
Expected: PASS.

- [ ] **Step 5: Docs**
  - **`README.md`, a new section "Jaws's public image"** under "Jaws: the `jaws` CLI":
    - what it holds: the `generic` target, with every stack and no configuration, for linux/amd64;
    - where: `public.ecr.aws/<alias>/jaws:vX.Y.Z`, the variable `JAWS_PUBLIC_IMAGE`;
    - when: each release, in the `publish` environment, with `JAWS_PUBLISH_ROLE_ARN` (`release-infra/`). It skips with a notice until both variables are set;
    - pin it by tag and digest, as the job's summary prints them. A platform's image is `FROM` that, plus `COPY config/ /etc/jaws/config/` and `COPY datasets/ /etc/jaws/datasets/`;
    - a published tag is never replaced, and a re-publish fills in a missing one. Tags cut before the generic image are never published.
  - **`README.md`, the release paragraph** ("Releases, applies and the image"): after the `image` job, the public image job, which needs only Release Please.
  - **`README.md`, the paragraph "No role ARN is a secret, and this repository needs none as a variable. …":** it begins "No role ARN is a secret. This repository needs one as a variable, `JAWS_PUBLISH_ROLE_ARN`, the publishing role in `release-infra/`, so that no account ID appears outside that folder (spec 6.8)." The rest of the paragraph stays.
  - **`README.md`, "Owner hand-off":** after the `prod` environment, add the `publish` environment, restricted to `main`; then `release-infra/` and its variables, pointing to [release-infra/README.md](release-infra/README.md).
  - **`CONTRIBUTING.md`, "Releases":** step 3 also names the public image job, once publishing is set up.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/release-please.yml tests/test_public_image.py tests/test_workflow_roles.py tests/test_foundation_workflows.py README.md CONTRIBUTING.md
git commit -m "feat(cli): publish the generic image to ECR Public on each release"
```

---

### Task 6: Each publish prunes ECR Public to the newest release versions

**Files:**
- Create: `scripts/prune_public_images.py`, `tests/test_prune_public_images.py`
- Modify: `.github/workflows/release-please.yml` (the `public-image` job's last step), `tests/test_public_image.py`
- Modify: `pyproject.toml` (`[tool.mypy]`'s `files`) and `.pre-commit-config.yaml` (the `mypy` hook's `files`), so that mypy checks `scripts/` too
- Modify: `README.md` ("Jaws's public image"), `CONTRIBUTING.md` ("Releases", step 3), `AGENTS.md` ("Things that need the owner")

**Interfaces:**
- Consumes: the `public-image` job, and `decide`'s check of `KEEP` (Task 5); the role's `PruneTheJawsImage` statement (Task 4); `job` and `run_step` (Task 2).
- Produces `scripts/prune_public_images.py`. It uses the standard library only, so the runner's `python3` (3.12 on `ubuntu-latest`) runs it with nothing installed.
  - Usage: `python3 scripts/prune_public_images.py --keep <N|all> --published <tag>`, with the JSON of `aws ecr-public describe-images` on stdin.
  - On stdout: the image IDs to delete, in batches of at most 100 (`BatchDeleteImage`'s limit), one JSON array per line. Nothing when nothing goes.
  - On stderr: a line for each image ID it selects, or why it selects none.
  - A `--keep` that is neither a whole number of at least 1 nor exactly `all` exits 2, with a message naming `JAWS_PUBLIC_IMAGE_KEEP`, and prints nothing on stdout.
- Its selection:
  1. A release version is a tag `vX.Y.Z`, ordered by its three numbers, not as text.
  2. It keeps the newest N release versions, and `--published` wherever that falls (a re-published older tag). `all` keeps every image.
  3. It deletes every other release version by tag (`{"imageTag": …}`), oldest first. An image that also carries a kept tag keeps it.
  4. Then it deletes every untagged image by digest (`{"imageDigest": …}`), unless an image in the repository is an index: its `imageManifestMediaType` is an OCI image index or a Docker manifest list. An index's own images are untagged, and deleting them would break it. Today's image is one manifest (one platform, `provenance: false`), so the repository holds no index.
  5. It leaves every other tag alone.
- Produces, in the `public-image` job, a last step, after the summary:
  - `name: Prune the public repository to the newest release versions`, `id: prune`;
  - `if: vars.JAWS_PUBLIC_IMAGE_KEEP != 'all'`, so that `all` skips it;
  - `env: { KEEP: "${{ vars.JAWS_PUBLIC_IMAGE_KEEP || '10' }}" }`, the one place the default lives;
  - a comment: ECR Public has no lifecycle policies, so each publish prunes; the tag just pushed is never deleted; `all` is for v1, once Jaws has consumers;
  - its `run`, with the push role the job already holds:

    ```bash
    aws ecr-public describe-images --region us-east-1 --repository-name jaws --output json > "$RUNNER_TEMP/images.json"
    python3 scripts/prune_public_images.py --keep "$KEEP" --published "$TAG" < "$RUNNER_TEMP/images.json" > "$RUNNER_TEMP/prune.jsonl"
    while read -r batch; do
      aws ecr-public batch-delete-image --region us-east-1 --repository-name jaws --image-ids "$batch" --output json
    done < "$RUNNER_TEMP/prune.jsonl"
    ```

    It uses files, not a pipe: Actions runs `bash -e` without `pipefail`, so a pipe would hide the script's refusal.

- [ ] **Step 1: Write the failing tests**

`tests/test_prune_public_images.py`'s docstring: what each publish deletes from the public repository (ruling 14), fed `describe-images` JSON as the step feeds it, with no AWS. `_prune` runs `[sys.executable, SCRIPT, f"--keep={keep}", "--published", published]` with `{"imageDetails": images}` on stdin. The `=` form lets `-1` and the empty string reach the script as values.

```python
SCRIPT = REPO_ROOT / "scripts" / "prune_public_images.py"
MANIFEST = "application/vnd.oci.image.manifest.v1+json"
INDEX = "application/vnd.oci.image.index.v1+json"
UNTAGGED = "sha256:" + "0" * 64


def _image(*tags: str, digest: str = "", media_type: str = MANIFEST) -> dict[str, Any]:
    """One `imageDetails` entry. With no tags it has no `imageTags`, as AWS answers;
    the digest defaults to one made from the tags."""


def _versions(count: int) -> list[dict[str, Any]]:
    """v0.1.0 to v0.<count>.0: from v0.10.0 on, text order and semver order differ."""
    return [_image(f"v0.{minor}.0") for minor in range(1, count + 1)]


def _prune(
    images: list[dict[str, Any]], keep: str, published: str
) -> tuple[subprocess.CompletedProcess[str], list[dict[str, str]]]:
    """Run the script as the step does: the result, and every image ID it would delete."""


def test_it_keeps_the_newest_n_release_versions_by_semver() -> None:
    result, deleted = _prune(_versions(12), keep="10", published="v0.12.0")
    assert result.returncode == 0, result.stderr
    assert deleted == [{"imageTag": "v0.1.0"}, {"imageTag": "v0.2.0"}]


def test_it_never_deletes_the_tag_just_published() -> None:
    """A re-published older tag stays until a later publish prunes it."""
    _, deleted = _prune(_versions(12), keep="1", published="v0.3.0")
    tags = [d["imageTag"] for d in deleted]
    assert "v0.3.0" not in tags and "v0.12.0" not in tags and len(tags) == 10


def test_it_removes_untagged_images_and_leaves_other_tags_alone() -> None:
    images = [*_versions(2), _image(digest=UNTAGGED), _image("latest")]
    _, deleted = _prune(images, keep="1", published="v0.2.0")
    assert deleted == [{"imageTag": "v0.1.0"}, {"imageDigest": UNTAGGED}]


def test_untagged_images_stay_while_an_index_could_refer_to_them() -> None:
    images = [*_versions(2), _image("v0.3.0", media_type=INDEX), _image(digest=UNTAGGED)]
    result, deleted = _prune(images, keep="10", published="v0.3.0")
    assert deleted == [] and "index" in result.stderr


def test_all_keeps_every_version() -> None:
    result, deleted = _prune(_versions(12), keep="all", published="v0.12.0")
    assert result.returncode == 0 and deleted == []


@pytest.mark.parametrize("keep", ["ten", "0", "-1", "1.5", " 10", "", "ALL"])
def test_it_refuses_a_keep_that_is_neither_a_whole_number_nor_all(keep: str) -> None:
    result, deleted = _prune(_versions(12), keep=keep, published="v0.12.0")
    assert result.returncode == 2 and "JAWS_PUBLIC_IMAGE_KEEP" in result.stderr
    assert deleted == []


def test_it_deletes_in_batches_the_api_accepts() -> None:
    images = [_image(f"v1.0.{patch}") for patch in range(250)]
    result, _ = _prune(images, keep="10", published="v1.0.249")
    assert [len(json.loads(line)) for line in result.stdout.splitlines()] == [100, 100, 40]
```

In `tests/test_public_image.py`, the step itself:

```python
#: Stands in for aws: logs each call, and answers describe-images with FAKE_IMAGES.
FAKE_AWS = """#!/usr/bin/env bash
echo "aws $*" >> "$FAKE_LOG"
case "$2" in
  describe-images) cat "$FAKE_IMAGES" ;;
  batch-delete-image) echo '{"imageIds": [], "failures": []}' ;;
  *) echo "unexpected: aws $*" >&2; exit 2 ;;
esac
"""


def test_each_publish_prunes_the_repository_with_the_push_role() -> None:
    steps = job("release-please.yml", "public-image")["steps"]
    ids = [step.get("id") for step in steps]
    prune = steps[ids.index("prune")]
    assert ids[-1] == "prune" and ids.index("build") < ids.index("prune")
    assert prune["if"] == "vars.JAWS_PUBLIC_IMAGE_KEEP != 'all'", "all skips the prune"
    assert prune["env"] == {"KEEP": "${{ vars.JAWS_PUBLIC_IMAGE_KEEP || '10' }}"}
    roles = [
        s for s in steps if s.get("uses", "").startswith("aws-actions/configure-aws-credentials")
    ]
    assert len(roles) == 1, "the push role, and no other"


def test_the_prune_step_deletes_what_the_script_selects(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / "scripts", tmp_path / "scripts")
    images = tmp_path / "images.json"
    details = [
        {"imageDigest": f"sha256:{minor:064x}", "imageTags": [f"v0.{minor}.0"]}
        for minor in range(1, 13)
    ]
    images.write_text(json.dumps({"imageDetails": details}))
    log = tmp_path / "aws.log"
    env = {"KEEP": "10", "TAG": "v0.12.0", "RUNNER_TEMP": str(tmp_path)}
    result, _ = run_step(
        "release-please.yml",
        "public-image",
        "prune",
        cwd=tmp_path,
        env={**env, "FAKE_LOG": str(log), "FAKE_IMAGES": str(images)},
        fakes={"aws": FAKE_AWS},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    describe, *deletes = log.read_text().splitlines()
    assert describe == (
        "aws ecr-public describe-images --region us-east-1 --repository-name jaws --output json"
    )
    assert len(deletes) == 1 and "--repository-name jaws" in deletes[0]
    assert '"v0.1.0"' in deletes[0] and '"v0.2.0"' in deletes[0] and "v0.3.0" not in deletes[0]
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_prune_public_images.py tests/test_public_image.py -v`
Expected: FAIL. The script doesn't exist, and the job has no step `prune`.

- [ ] **Step 3: Write the script and add the step** per the Interfaces. Add `"scripts"` to `[tool.mypy]`'s `files`, and `scripts` to the `mypy` hook's `files` pattern.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_prune_public_images.py tests/test_public_image.py tests/test_hooks.py -v && uv run mypy && uv run ruff check`
Expected: PASS.

- [ ] **Step 5: Docs**
  - **`README.md`, "Jaws's public image"** gains: until v1, each publish keeps the newest `JAWS_PUBLIC_IMAGE_KEEP` release versions (default 10) and deletes the rest, untagged images included, since ECR Public has no lifecycle policies. At today's pace a version lasts about two days, so pin a recent one. `all` keeps every version; the owner sets it at v1, once Jaws has consumers with maintenance contracts.
  - **`CONTRIBUTING.md`, "Releases":** step 3's public image job then prunes the public repository to the newest `JAWS_PUBLIC_IMAGE_KEEP` versions.
  - **`AGENTS.md`, "Things that need the owner"** gains: at v1, set `JAWS_PUBLIC_IMAGE_KEEP` to `all`.

- [ ] **Step 6: Commit**

```bash
git add scripts/prune_public_images.py tests/test_prune_public_images.py .github/workflows/release-please.yml tests/test_public_image.py pyproject.toml .pre-commit-config.yaml README.md CONTRIBUTING.md AGENTS.md
git commit -m "feat(cli): prune ecr public to the newest release versions after each publish"
```

---

### Task 7: Ready the pull request

The branch already has draft PR #317, which held this plan for review. The work lands on it.

- [ ] **Step 1: Commit this plan's rulings to the roadmap**
  - Row 04's status becomes "in its pull request (#317)".
  - Rows 01 and 03 still describe their work as in a pull request. They become merged: 01 in #314 and #318, 03 in #316. "Plans 01–03 are written so far" becomes "Plans 01–04".
  - Row 05 adds:
    - the platform stacks in the image have no backend, so the hub's runs write theirs from `state`;
    - the helper scripts are not in the image;
    - the Databricks stacks are in the image;
    - the public address is `vars.JAWS_PUBLIC_IMAGE`, and its digests can be read anonymously.
  - Row 06 adds:
    - the hub's `Dockerfile` is the `jaws-cli` stage on the public image;
    - the retention risk, with its two remedies to choose between ("For plan 06" above);
    - `tests/platform/test_release_infra.py` stays in `jaws` when `tests/platform/` moves: it checks a `jaws` folder.
  - Row 07 adds:
    - cleanup removes the `jaws-cli` stage and the release's `image` job;
    - `tests/platform/test_release_infra.py`'s checks against `config/` become literals;
    - the owner-values guard exempts `release-infra/`, and takes up what the public image carries (Review Focus 5).
  - "During plan 04" becomes this plan's owner hand-off, steps 1–5.

```bash
git add docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md
git commit -m "docs(repo): add plan 04's rulings to the roadmap"
```

- [ ] **Step 2: Run the full `AGENTS.md` checklist** (it now includes `release-infra/`), then Task 3's Step 5 commands.
Expected: every command passes.

- [ ] **Step 3: Push the branch and ready the PR**
  - Push with `--force-with-lease`: the branch was rebased before Task 1.
  - Title: `feat(cli): ship a generic image with every stack, and publish it to ECR Public`.
  - Body: `.github/pull_request_template.md`, with every section filled in.
    - It links the spec and this plan.
    - It says merging changes nothing in AWS, and that nothing is published before the owner's steps.
    - It says what keeps CI roles out of `release-infra/`'s state (ruling 8), and which spending the owner accepted (Global Constraints).
    - Its "Owner hand-off" section is this plan's, steps 1–7.

```bash
git push --force-with-lease
gh pr edit 317 --title "feat(cli): ship a generic image with every stack, and publish it to ECR Public" --body-file <file>
gh pr ready 317
```

Expected:
- CI passes, "Image build and smoke test" and "Release infrastructure validate, tflint, test" included;
- the `Terraform plan`, `Monitoring plan` and `Data access plan` comments say merging leaves AWS alone.
