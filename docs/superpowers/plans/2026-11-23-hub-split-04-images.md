# Jaws as a product, plan 04: images and publishing: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Jaws's image with every stack and no configuration inside, and publish it to ECR Public through a new owner-applied `release-infra/`. Keep pushing the configuration-baked `jaws-cli` image, so every existing pin keeps working.

**Architecture:**
- One `Dockerfile`, two targets.
  - `generic` is the default target. It holds the CLI, a pinned Terraform and every stack: `stacks/*`, and the platform's `foundation/`, `monitoring/` and `data-access/`. The stacks come without their backends or tests, with modules and providers vendored, so a run needs the network only for its backend and APIs. The image holds no configuration.
  - `jaws-cli` is `generic` plus this repository's `config/` at `/etc/jaws/config` and `datasets/` at `/etc/jaws/datasets`. That is the shape of every platform's image, the hub's included.
- Each release pushes `jaws-cli:<tag>` as today. A tag cut before this plan has no `jaws-cli` stage, so re-publishing it builds its only image, as it always did.
- `release-infra/` is a new root that only the owner applies, like `billing-export/`.
  - It holds the ECR Public repository `jaws`, and `release-infra-publish`: a role that only this repository's `publish` environment can assume, and that may push only to `jaws`.
  - Its state sits in the platform's state bucket under `project=release-infra/`. The bucket's hardened policy already keeps that prefix from every CI role.
- Once the owner has applied it and set two repository variables, each release also pushes `generic` to `public.ecr.aws/<alias>/jaws:<tag>`. Until then, that job skips with a notice.

**Tech Stack:** Docker BuildKit (named targets); GitHub Actions (`docker/build-push-action@v7`, `aws-actions/configure-aws-credentials@v6`, `aws-actions/amazon-ecr-login@v2` with `registry-type: public`); Terraform 1.14.7 (`terraform test` with mock providers); the AWS provider `~> 6.0` (`aws_ecrpublic_repository`); `Jaws-Platform/jaws-ci/aws//modules/github-oidc-role` and `Jaws-Platform/jaws-foundation/aws//modules/context`, at their `src/jaws/product.yaml` versions; Python 3.13 and pytest; Node's test runner (commitlint).

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md), sections 6.3, 6.8, 6.10 (step 1), 6.12, 2, and 4 (decisions 5 and 6). Roadmap: [2026-11-23-hub-split-00-roadmap.md](2026-11-23-hub-split-00-roadmap.md), row 04. Plan 03's ruling 7 hands this plan the stacks in the image and the size budget.

**Where the work happens:** `jaws`, on `hub-split/04-images`, from `main` at ef89d7a (plans 01 and 03 merged as Jaws-Platform/jaws#314 and #316). One branch, one PR.

## Global Constraints

- **The repository rules (`AGENTS.md`):**
  - never push to `main`: one branch, one PR;
  - each commit is one line, `type(scope): subject`, at most 100 characters, with a lowercase first letter and no trailing period;
  - only `Co-authored-by:` trailers may follow, after a blank line;
  - the PR title is a valid commit header, and the PR body fills every template section.
- **Scopes.** `cli` for Tasks 1–3, 5 and 6; `repo` for adding the new scope; `publishing` for Task 4. The spec, verbatim (6.12): "**`jaws`:** a new `publishing` scope for the release infrastructure folder."
- **Never touch real infrastructure.**
  - Never run `terraform apply`, a plan against real state, `jaws apply|publish|release|destroy`, or `docker push`.
  - Run only `terraform test` (mock providers), `terraform validate`, `tflint`, `scripts/test-stack-plans.sh`, and local `docker build` and `docker run` (`--network none` for smoke tests).
- **Nothing in AWS changes when this plan merges.**
  - No `.tf` file in `foundation/`, `monitoring/` or `data-access/` changes: the image ships them as they are. So CI's `Terraform plan`, `Monitoring plan` and `Data access plan` must say merging leaves AWS alone.
  - CI never applies `release-infra/`: only the owner does.
  - Nothing pushes to ECR Public until the owner has applied `release-infra/` and set `JAWS_PUBLISH_ROLE_ARN` and `JAWS_PUBLIC_IMAGE`.
- **Old pins keep working.** The spec's anti-goal, verbatim (2): "A window where a project's CI is broken. Old pins keep working until that project switches."
  - The composite action doesn't change, and still runs `jaws-cli:<its own tag>`.
  - Every release still pushes `jaws-cli:<tag>` with `config/` baked in.
  - Re-publishing any tag (`release-please.yml`'s `workflow_dispatch`) builds that tag's own image for `jaws-cli`.
- **Jaws's image, verbatim (6.3):** "Generic: no configuration inside." "Published by `jaws`'s release workflow to `public.ecr.aws/<alias>/jaws:vX.Y.Z`, with the role from section 6.8." "`jaws`'s CI keeps the build, offline smoke test and size budget it has today."
- **The release infrastructure, verbatim (6.8):** "the ECR Public repository `jaws`;" "one role, trusted only for `Jaws-Platform/jaws` release runs, that may push to that repository and nothing else." "Its state goes in the platform's state bucket, under its own prefix." "The role's ARN is a repository variable in `jaws`. No account ID appears in code outside this folder."
- **No spending money.**
  - ECR Public's always-free tier covers 50 GB of storage. Nothing new is paid.
  - Each `jaws-cli` image grows by about 45 MiB, the platform stacks' providers. The repository keeps 20 images, which share layers. So it grows by well under 1 GB, under 10 cents a month, until cleanup retires it.
- **The region** stays `us-east-1`, a product constant (spec 6.7). ECR Public's API exists only there.
- **Owner values in files.**
  - `release-infra/` is the one folder that may spell these: the production account's ID, the platform's state bucket, and the GitHub IDs of `Jaws-Platform/jaws`.
  - This plan names them by their paths: `aws.accounts[aws.primary].account_id` in `config/aws.yaml`, `state.bucket` in `config/terraform.yaml`, and `platform.repositories[0]` in `config/platform.yaml`.
  - A failing test never prints them. Compute a comparison into a boolean before asserting it, so pytest shows only the message.
  - New tests use neutral values: account `123456789012`, `public.ecr.aws/example-alias/jaws`.
- **The privacy hook.**
  - If a hook refuses a command because a file holds the owner's email, stop and ask the owner to run it (they can, with `!`). Never work around the hook.
  - `tests/conftest.py` is never edited. Importing its helpers (`REPO_ROOT`, `repo_config`, `onboarded`) is fine.
  - If the hook refuses the local `docker build --target jaws-cli`, which copies `config/`, leave that target to CI.
- **Off limits.**
  - `owner-access/` and `billing-export/`.
  - Plan 02's files: `src/jaws/report.py`, the `ManagedBy` checks in `stacks/site/variables.tf` and `stacks/bot/variables.tf`, the SSM path constants, and `src/jaws/kinds/lichess_bot/Dockerfile`'s labels.
  - This plan owns the root `Dockerfile`, its labels included.
- **Before the PR,** run the `AGENTS.md` checklist, then `(cd release-infra && terraform init -backend=false && terraform validate && terraform test)`, then the smoke commands of Tasks 2 and 3 against a local `docker build --platform linux/amd64`.

## Review Focus

1. **Re-publishing a tag cut before this plan.** v0.76.0, which every project pins, has one image with `config/` baked in and no `jaws-cli` stage. Expected: `jaws-cli` gets that tag's own image, built as before, and ECR Public gets nothing. Tests: Task 2, `test_the_jaws_cli_job_builds_jaws_cli_or_an_old_tag_s_only_image`; Task 5, `test_a_tag_without_the_generic_image_is_never_published`.
2. **A release before publishing is set up, or when it is half set up.** Expected:
   - with neither variable set, the release goes on and `jaws-cli` is pushed. The public job is skipped with a notice, and never enters the `publish` environment;
   - with one variable, or a malformed one, the check fails and names it. `jaws-cli` is still pushed.

   Tests: Task 5, `test_without_the_variables_publishing_is_skipped_with_a_notice`, `test_a_half_set_or_malformed_variable_fails_the_check` and `test_the_public_job_runs_only_when_the_check_says_so`.
3. **A tag that is already public.** ECR Public tags are mutable, and customers pin tag and digest. Expected: a published tag is never replaced, and a registry error stops the job rather than pushing. Tests: Task 5, `test_a_published_tag_is_never_replaced` and `test_a_registry_error_stops_the_publish`.
4. **The public image run with no configuration.** Expected: exit 2, with a message naming `JAWS_CONFIG` and `/etc/jaws/config`, not today's "tool configuration not found at config". Tests: Task 1, `test_without_a_configuration_the_cli_says_where_it_looks`; Task 2's smoke step.
5. **The owner's files in the public image.** `backend/prod.hcl` names the owner's state bucket, and the stacks' `tests/` hold fixtures generated from the owner's configuration. Expected: the generic image holds no `/etc/jaws`, `backend/`, `tests/`, `.tftest.hcl` or state. Tests: Task 2, `test_the_generic_image_holds_no_configuration`; Task 3, `test_the_build_context_keeps_backends_lock_files_and_stack_tests_out`, and the smoke step "the generic image ships no backend, stack test or state".

## Rulings

Calls this plan makes where the spec is silent, with the later plan that takes each up:

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
   - Measured with this plan's `Dockerfile`: 283 MiB compressed for linux/amd64. The platform stacks add 43 MiB (measured on arm64: 214 → 257).
   - Spec 8 leaves the value to the builder.
   - Images stay linux/amd64 only, as today.
6. **Without a configuration, the CLI names where it looks.** That is the first thing a user of the public image sees.
7. **`release-infra/` reads nothing outside its folder,** since it outlives `config/` (spec 6.10, step 7).
   - It spells the account, the state bucket and the repository's IDs itself. Tests check them against `config/` while `config/` exists.
   - Plan 07 turns those checks into literals, and its owner-values guard exempts this folder.
   - When plan 01 Task 3 lands, those checks read `PLATFORM_CONFIG_DIR` and move to `tests/platform/`, like `tests/test_billing_export.py`'s.
8. **Its state prefix needs no foundation change.** Outside the prefixes the state bucket lists, its hardened policy denies every principal but the break-glass admins, the owner's admin role among them. So `project=release-infra/` is the owner's alone, unless a project is registered under that key, which is tested.
9. **The role** comes from jaws-ci's `github-oidc-role`, with one inline policy.
   - Its name, `release-infra-publish`, stays outside `jaws-*`. The platform's apply role manages every `jaws-*` role, so after the split the hub could otherwise rewrite the vendor's role.
   - It trusts a new GitHub environment, `publish`, which only the public image job enters. `prod` also runs the 15-minute data-access sweep and the by-hand applies.
10. **The repository is a plain `aws_ecrpublic_repository`,** with `prevent_destroy`.
    - No module family has an ECR Public module. `owner-access/state.tf` is the precedent for plain resources in an owner-only root.
    - `prevent_destroy`, because every customer pins it.
11. **Two repository variables.**
    - `JAWS_PUBLISH_ROLE_ARN`, the role.
    - `JAWS_PUBLIC_IMAGE`, the address `public.ecr.aws/<alias>/jaws`. The alias is known only once AWS approves it. With the address in a variable, the role needs no read permission.
    - With both unset, the public job skips with a notice. With only one set, or a malformed one, the check fails.
12. **A published tag is never replaced,** because ECR Public has no tag immutability. An anonymous registry check runs before each push, so a re-publish only fills in a tag that is missing.
13. **The public job needs only Release Please,** not the account or the applies. So it needs no change when cleanup takes `config/` and the applies out of `jaws`.
14. **ECR Public keeps every image:** it has no lifecycle policies. At today's pace that is about 0.5 GB a week, inside the free tier for over a year. Pruning is the owner's, by hand.
15. **The tags of `release-infra/`'s resources are Jaws's own:** `Organization` and `Owner` are `Jaws-Platform`, `Project` is `jaws`. The folder names no person.

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

   ```sh
   gh variable set JAWS_PUBLIC_IMAGE --body "$(terraform output -raw repository_uri)"   # public.ecr.aws/<alias>/jaws
   gh variable set JAWS_PUBLISH_ROLE_ARN --body "$(terraform output -raw role_arn)"
   ```

5. **Make the new check required:** run `scripts/apply-repo-settings.sh`.
6. **Watch the next release.** It publishes `public.ecr.aws/<alias>/jaws:<tag>`, and its summary prints the address with the digest. Check it anonymously with `docker pull`.
   - To publish the current release sooner, run the Release workflow with its tag. Its public job publishes the image.
   - Its `jaws-cli` job then fails on the tag that repository already holds, as re-publishing an existing tag always has (its tags are immutable).

---

### Task 1: Without a configuration, the CLI says where it looks

**Files:**
- Modify: `src/jaws/settings.py:38-40` (a constant after `LOCAL_CONFIG_PATH`) and `src/jaws/settings.py:1141-1151` (`load_settings`)
- Test: `tests/test_settings.py`

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

  - `load_settings(None, ...)` raises `ConfigError(NO_CONFIGURATION)` when `default_config_path()` falls back to `./config` and that doesn't exist.
  - A path that was given (`--config` or `JAWS_CONFIG`) and doesn't exist keeps today's message, "tool configuration not found at {path}".

- [ ] **Step 1: Write the failing tests** in `tests/test_settings.py`

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


def test_a_configuration_given_but_missing_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setenv("JAWS_CONFIG", str(missing))
    with pytest.raises(ConfigError, match=re.escape(f"tool configuration not found at {missing}")):
        load_settings(environ={})
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_settings.py -k "where_it_looks or given_but_missing" -v`
Expected: FAIL, because `NO_CONFIGURATION` can't be imported from `jaws.settings`.

- [ ] **Step 3: Add the constant and the check.** In `load_settings`, before reading the document: if `path` is `None`, the resolved default is `LOCAL_CONFIG_PATH`, and it doesn't exist, raise `ConfigError(NO_CONFIGURATION)`.

- [ ] **Step 4: Run them and watch them pass**

Run: `uv run pytest tests/test_settings.py -v && uv run mypy`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/jaws/settings.py tests/test_settings.py
git commit -m "feat(cli): say where a configuration is looked for when none is found"
```

---

### Task 2: One `Dockerfile`, two images: `generic` and `jaws-cli`

**Files:**
- Modify: `Dockerfile:1-6` (the header) and `Dockerfile:74-102` (stage 3 becomes `generic`, then the `jaws-cli` stage and the final stage)
- Modify: `.github/workflows/release-please.yml:10-15` (the dispatch input's description) and `:178-231` (the `image` job)
- Modify: `.github/workflows/ci.yml:409-469` (the `image` job)
- Create: `tests/workflow_steps.py`, `tests/test_cli_image.py`
- Modify: `README.md:38-41` (the CLI section), `:85` (the build command), `:362` (the `Dockerfile` row), `:380-382` (the tool configuration), `:635` (the image check), `:646` (the release paragraph)

**Interfaces:**
- Consumes: `NO_CONFIGURATION` (Task 1), in the smoke step.
- Produces, in the `Dockerfile`:
  - `FROM python:${PYTHON_VERSION}-alpine AS generic`: today's runtime stage, without `COPY config /etc/jaws/config`;
  - `FROM generic AS jaws-cli`, with exactly `COPY config /etc/jaws/config` and `COPY datasets /etc/jaws/datasets`;
  - a last stage of only `FROM generic`, so a plain `docker build .` builds the generic image.
- Produces, in CI: `jaws:ci` (the default target) and `jaws:ci-cli` (`--target jaws-cli`).
- Produces, in the release's `image` job: a step `id: target` that writes `target=jaws-cli`, or `target=` for a tag without that stage. `docker/build-push-action` takes `target: ${{ steps.target.outputs.target }}`. An empty target means the `Dockerfile`'s last stage.
- Produces, in `tests/workflow_steps.py` (Task 5 uses it too):
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
#: A tag cut before the generic image: one stage, config/ baked in (v0.78.1 and earlier).
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
  - In `generic`, the `org.opencontainers.image.description` label becomes "Jaws: the CLI, a pinned Terraform and its stacks, with their modules and providers vendored. No configuration inside: a platform's image adds it at /etc/jaws/config."
  - The `jaws-cli` stage's comment says three things: it is what today's callers run (the composite action pulls `jaws-cli:<tag>`); it has the shape of every platform's image; and it goes with `config/` at cleanup (spec 6.10, step 7).

- [ ] **Step 4: Point the release's `image` job at the target**
  - The job's name becomes `Publish jaws-cli (${{ needs.release-please.outputs.tag_name || inputs.tag }})`.
  - After the checkout, add a step named "Choose the target (jaws-cli, or the only image of a tag cut before it)", with `id: target`.
    - If `grep -qx 'FROM generic AS jaws-cli' Dockerfile`, it writes `target=jaws-cli`.
    - Otherwise it writes `target=`, and emits `::notice::$TAG predates the generic image: building its only image, config/ baked in, as before`.
  - `docker/build-push-action` takes `target: ${{ steps.target.outputs.target }}`.
  - The dispatch input's description becomes "Re-publish the images of an existing release tag (for example v0.76.0)".

- [ ] **Step 5: Build and smoke-test both images in CI's `image` job.** The job keeps its name, a required check.
  - After the Terraform version step, there are two `docker/build-push-action` steps:
    - the generic image: no target, `tags: jaws:ci`, with today's `cache-from` and `cache-to`;
    - then `target: jaws-cli`, `tags: jaws:ci-cli`, `cache-from: type=gha`.
  - The smoke steps:

| Step name | Image | Passes when |
|---|---|---|
| Smoke test (the generic image holds no configuration) | `jaws:ci` | `docker run --rm --network none --entrypoint sh jaws:ci -c 'test ! -e /etc/jaws'` exits 0 |
| Smoke test (without a configuration, the CLI says where it looks) | `jaws:ci` | `docker run --rm --network none jaws:ci config show` exits 2, and its output contains `JAWS_CONFIG` and `/etc/jaws/config`. Wrap it in `set +e` and check both in one `[[ … ]]` that emits `::error::` |
| Smoke test (the jaws-cli image holds the configuration and the datasets where the CLI and the stacks look) | `jaws:ci-cli` | `test -f /etc/jaws/datasets/README.md && ls /etc/jaws/config/*.yaml` exits 0. The foundation refuses to plan without that README while Databricks is ready |
| Smoke test (validate a fixture site offline, inside the jaws-cli image) | `jaws:ci-cli` | today's step, with `jaws:ci` replaced by `jaws:ci-cli` |
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
  - **The CLI section (:38-41).** It ships as two images, both built from the `Dockerfile` and pushed by each release:
    - the generic image, with no configuration, public at `public.ecr.aws/<alias>/jaws` (link to "Jaws's public image", which Task 5 writes);
    - `jaws-cli`, the same image with this repository's `config/` and `datasets/`, in the account's private ECR repository. Site repositories run `jaws-cli`.
  - **The build command (:85).** Builds the generic image. Add the same command with `--target jaws-cli -t jaws-cli:local`.
  - **The `Dockerfile` row (:362).** "The CLI images: `generic`, the default target (the CLI, a pinned Terraform, the stacks with modules and providers vendored, no configuration), and `jaws-cli`: `generic` plus `config/` at `/etc/jaws/config` and `datasets/` at `/etc/jaws/datasets`".
  - **The tool configuration (:380-382).** Instead of "the image bakes it at `/etc/jaws/config`": "a platform's image holds it at `/etc/jaws/config` (`jaws-cli` holds this repository's; the generic image holds none)".
  - **The image check (:635).** "builds both images, checks that the generic one holds no configuration and says where it looks for one, runs `validate` offline inside `jaws-cli`, checks the Terraform version and enforces the compressed-size budget".
  - **The release paragraph (:646).** The `image` job builds the `jaws-cli` target; for a tag cut before it, the tag's only image.

- [ ] **Step 8: Commit**

```bash
git add Dockerfile .github/workflows/release-please.yml .github/workflows/ci.yml tests/workflow_steps.py tests/test_cli_image.py README.md
git commit -m "feat(cli): build a generic image and the jaws-cli image from one dockerfile"
```

---

### Task 3: Every stack ships in the image

**Files:**
- Modify: `Dockerfile:54-72`: the stack copies, the init loop and their comment. The comment that the Databricks stacks are left out goes.
- Modify: `.dockerignore`
- Modify: `.github/workflows/ci.yml` (the `image` job: three smoke steps, and the budget)
- Modify: `tests/test_cli_image.py`
- Modify: `src/jaws/product.yaml:1-5` (the header comment), and `README.md:362` and `:635`

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

- [ ] **Step 4: Add three smoke steps to CI's `image` job,** after the Terraform-version step, and raise the budget.

| Step name | Passes when |
|---|---|
| Smoke test (every stack initializes offline and validates, as the CLI runs it) | in `jaws:ci` with `--network none`, for each `/opt/jaws/stacks/*/`: copy it to `mktemp -d`, then `terraform init -backend=false -input=false -no-color -plugin-dir=/opt/jaws/plugins`, then `terraform validate -no-color`. A failure emits `::error::<stack> …` |
| Smoke test (one version of each provider in the mirror) | `docker run --rm --network none --entrypoint find jaws:ci /opt/jaws/plugins -name '*.zip' \| xargs -n1 dirname \| sort \| uniq -d` prints nothing. Otherwise emit `::error::` naming the directories: "align the stacks' provider constraints" |
| Smoke test (the generic image ships no backend, stack test or state) | `find /opt/jaws/stacks -path '*/.terraform' -prune -o \( -name backend -o -name tests -o -name '*.tftest.hcl' -o -name '*.tfstate*' \) -print`, run in `jaws:ci`, prints nothing |
| Image size budget | `MAX_COMPRESSED_MB: "300"`. Its comment: what a consumer downloads; the aws provider archive alone is about 170 MB, and the platform stacks' databricks, time and archive providers about 45 MB more. The step checks `jaws:ci` and `jaws:ci-cli` in a loop, and lists both sizes in the summary |

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
  - **`README.md:362`:** the generic image holds every stack: `stacks/*` and the platform's own, without backends.
  - **`README.md:635`:** add "initializes and validates every stack inside it offline, checks the mirror holds one version of each provider, and that no backend or stack test ships"; the budget is 300 MiB.

- [ ] **Step 7: Commit**

```bash
git add Dockerfile .dockerignore .github/workflows/ci.yml tests/test_cli_image.py src/jaws/product.yaml README.md
git commit -m "feat(cli): ship every stack in the image, the platform's own included"
```

---

### Task 4: `release-infra/`, the ECR Public repository and the role that pushes to it

**Files:**
- Modify: `commitlint.config.mjs` (`SCOPES`), `CONTRIBUTING.md:35-49` (the Scopes table), `tools/commitlint/scopes.test.mjs`
- Create in `release-infra/`: `versions.tf`, `providers.tf`, `backend.tf`, `main.tf`, `outputs.tf`, `README.md`, `.terraform.lock.hcl` (from `terraform init`), `backend/prod.hcl` and `tests/release_infra.tftest.hcl`
- Create: `tests/test_release_infra.py`
- Modify: `.github/workflows/ci.yml` (a `release-infra-stack` job after `billing-export-stack`), `scripts/apply-repo-settings.sh:53-71` (the required checks), `.pre-commit-config.yaml` (a pre-push hook; `release-infra` added to the pytest hook's `files`), `.dockerignore`
- Modify: `tests/test_versions.py:105-114` (`_stack_files`), `tests/test_hooks.py:38-47` (`expected`)
- Modify: `AGENTS.md:19,33,42` and "Things that need the owner"; `README.md:303-304,328` and the Layout table; `CONTRIBUTING.md:74,89`; `src/jaws/product.yaml:1-5`

**Interfaces:**
- Produces: the scope `publishing`, after `monitoring` in `SCOPES`. Its value is the plain string "release-infra/: Jaws's ECR Public repository and the role that pushes the image to it", like its neighbours. CONTRIBUTING's table gets the row after `monitoring`'s: `` | `publishing` | `release-infra/`: Jaws's ECR Public repository and the role that pushes the image to it | ``.
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
    - `description = "Pushes the Jaws image to the ECR Public repository jaws, for Jaws-Platform/jaws release runs (environment publish)"`;
    - `repository`, `owner_id` and `repository_id` from `local.repository`;
    - `subjects = ["environment:${local.environment}"]`;
    - `oidc_provider_arn = data.aws_iam_openid_connect_provider.github.arn`;
    - `component = "publishing"`;
    - `inline_policies = { push = local.push_policy }`.
  - `local.push_policy` has two statements, nothing else:
    - `LogInToEcrPublic` allows `["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"]` on `"*"`. Neither action takes a resource, and neither grants anything by itself.
    - `PushTheJawsImage` allows `["ecr-public:BatchCheckLayerAvailability", "ecr-public:InitiateLayerUpload", "ecr-public:UploadLayerPart", "ecr-public:CompleteLayerUpload", "ecr-public:PutImage"]` on `aws_ecrpublic_repository.jaws.arn`.
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
- For Task 5: the environment `publish`, and the variables `JAWS_PUBLISH_ROLE_ARN` and `JAWS_PUBLIC_IMAGE`.

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
run "the_role_may_push_that_repository_and_nothing_else" {
  command = plan

  assert {
    condition = jsonencode(jsondecode(module.publish_role.inline_policies["push"].policy).Statement) == jsonencode([
      { Sid = "LogInToEcrPublic", Effect = "Allow", Action = ["ecr-public:GetAuthorizationToken", "sts:GetServiceBearerToken"], Resource = "*" },
      { Sid = "PushTheJawsImage", Effect = "Allow", Action = ["ecr-public:BatchCheckLayerAvailability", "ecr-public:InitiateLayerUpload", "ecr-public:UploadLayerPart", "ecr-public:CompleteLayerUpload", "ecr-public:PutImage"], Resource = aws_ecrpublic_repository.jaws.arn },
    ])
    error_message = "the role logs in to ECR Public and pushes to the repository jaws, and may do nothing else"
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

`tests/test_release_infra.py` follows `tests/test_billing_export.py`. Its docstring says: the ECR Public repository and the one role that pushes to it, in the production account (spec 6.8), applied only by the owner; no workflow assumes a role for it, and no foundation role or state prefix names it; a project registered under its key would get its state prefix; and it reads nothing outside its folder, since it stays in `jaws` when `config/` leaves.

```python
RESERVED = "release-infra"
ROOT = REPO_ROOT / RESERVED
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def test_no_project_is_registered_under_the_release_infra_key() -> None:
    assert RESERVED not in onboarded(repo_config()), (
        f"`{RESERVED}` is reserved: its CI roles would get the publishing infrastructure's state"
    )


def test_its_state_is_in_the_platform_s_state_bucket_under_its_own_prefix() -> None:
    values = _hcl_values(ROOT / "backend" / "prod.hcl")
    in_the_platform_bucket = values["bucket"] == repo_config()["state"]["bucket"]
    assert in_the_platform_bucket, "the bucket is config/terraform.yaml's state.bucket"
    assert values["key"] == f"project={RESERVED}/env=prod/{RESERVED}-prod.tfstate"
    assert values["region"] == "us-east-1"
    assert sorted(p.name for p in (ROOT / "backend").iterdir()) == ["prod.hcl"]
```

`_hcl_values` parses `key = "value"` lines, as `test_the_backend_file_names_the_accounts_state_bucket` does. Then add:
- `test_no_foundation_role_or_state_prefix_names_release_infra`: no `foundation/*.tf` holds `project=release-infra` or `release-infra`.
- `test_ci_never_plans_or_applies_release_infra`: `tests/test_billing_export.py`'s test, with `RESERVED`, requiring the workflows that name `release-infra` to be exactly `["ci.yml"]`.
- `test_its_ci_check_is_required`: `tests/test_monitoring_workflows.py`'s `test_the_monitoring_checks_are_required`, for "Release infrastructure validate, tflint, test".
- `test_it_reads_nothing_outside_its_folder`: no `release-infra/*.tf` holds `../`.
- `test_it_is_in_the_primary_account_and_trusts_this_repository`. It compares, as booleans:
  - the one `account_id = "…"` in `main.tf` with the primary account;
  - the one `"…/…"` repository name, `owner_id` and `repository_id` with `repo_config()["platform"]["repositories"][0]`.

  The messages name the field, never the value.
- `test_the_publishing_role_is_outside_the_platform_s_name_root`. The module's `name` is `release-infra-publish` and doesn't start with `f"{repo_config()['context']['name_root']}-"`. Its docstring: the foundation's apply role manages every `<name_root>-*` role (jaws-ci's `foundation/manage`).
- `test_it_never_enters_the_image`: `"release-infra"` is a line of `.dockerignore`.

In `tests/test_versions.py`, `_stack_files()` also yields `REPO_ROOT / "release-infra"`'s `*.tf`. In `tests/test_hooks.py`, `expected` gains `"terraform-test-release-infra": "cd release-infra"`.

- [ ] **Step 3: Run them and watch them fail**

Run: `(cd release-infra && terraform init -backend=false && terraform test) ; uv run pytest tests/test_release_infra.py tests/test_versions.py tests/test_hooks.py -v`
Expected: FAIL. `release-infra/` holds only its test, and there's no hook, job or ignore entry yet.

- [ ] **Step 4: Write the root** per the Interfaces, then `terraform init -backend=false` to create its lock file. `release-infra/README.md` follows `billing-export/README.md` and has these sections:
  - **What it is**: the repository, the role, the account, and why it's the vendor's (spec 6.8).
  - **The owner's root**: the guards, and where the state is.
  - **Run it**: this plan's owner hand-off, steps 1–5.
  - **Changing it**:
    - the role's name stays outside `jaws-*`;
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
Expected: PASS. `tests/test_owner_access.py` and `tests/test_billing_export.py` pass unchanged.

- [ ] **Step 7: Docs**
  - **`AGENTS.md`:**
    - line 19's bump list and `src/jaws/product.yaml`'s header list gain `release-infra/`;
    - the checklist gains `(cd release-infra && terraform init -backend=false && terraform validate && terraform test)`;
    - line 42 gains: "**`release-infra/` is the owner's too:** Jaws's release infrastructure, the ECR Public repository `jaws` and the role that pushes the image to it, in the production account. The same rules hold: no CI role, workflow or state prefix names it, and its role's name stays outside `jaws-*` (`tests/test_release_infra.py` checks). Its repository is a plain `aws_ecrpublic_repository`, since no module family has one";
    - "Things that need the owner" gains applying `release-infra/`, the ECR Public registry alias, and the `publish` environment.
  - **`README.md`:**
    - the Shared modules rows for `jaws-ci` (add `github-oidc-role`, the publishing role) and `jaws-foundation` gain `release-infra/`, and so does the pin sentence at :328;
    - a Layout row: `release-infra/` (root), "Jaws's release infrastructure: the ECR Public repository `jaws` and the role that publishes the image to it, applied only by the owner, never by CI ([release-infra/README.md](release-infra/README.md))".
  - **`CONTRIBUTING.md`:** `release-infra/` joins the pre-push list (:74) and the bump list (:89).

- [ ] **Step 8: Commit**

```bash
git add release-infra tests/test_release_infra.py tests/test_versions.py tests/test_hooks.py .github/workflows/ci.yml scripts/apply-repo-settings.sh .pre-commit-config.yaml .dockerignore AGENTS.md README.md CONTRIBUTING.md src/jaws/product.yaml
git commit -m "feat(publishing): add the ecr public repository jaws and the role that pushes to it"
```

---

### Task 5: Releases publish the generic image to ECR Public

**Files:**
- Modify: `.github/workflows/release-please.yml` (two jobs after `image`)
- Create: `tests/test_public_image.py`
- Modify: `README.md` (a section "Jaws's public image" after "Reusable workflows for site repositories"; :646, :648, and "Owner hand-off"), `CONTRIBUTING.md:97`

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
    - `env`: `TAG` (as in the `image` job), `ROLE_ARN: ${{ vars.JAWS_PUBLISH_ROLE_ARN }}` and `IMAGE: ${{ vars.JAWS_PUBLIC_IMAGE }}`;
    - steps: check out `refs/tags/<tag>`, then `id: decide`.
  - **`public-image`**, named `Publish the public image (<tag>)`:
    - `needs: [release-please, public-image-check]`;
    - `if: !cancelled() && needs.public-image-check.outputs.publish == 'true'`;
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
- Neither job names `release-infra`: `tests/test_release_infra.py` allows only `ci.yml` to.

The `decide` step is the algorithm the jobs depend on. Write it as this:

```bash
publish() { echo "publish=$1" >> "$GITHUB_OUTPUT"; }
if [[ -z "$ROLE_ARN$IMAGE" ]]; then
  echo "::notice::not publishing the public image: JAWS_PUBLISH_ROLE_ARN and JAWS_PUBLIC_IMAGE are not set (README.md, \"Jaws's public image\")"
  publish false; exit 0
fi
[[ "$ROLE_ARN" =~ ^arn:aws:iam::[0-9]{12}:role/[A-Za-z0-9+=,.@_-]+$ ]] || { echo "::error::JAWS_PUBLISH_ROLE_ARN is not an IAM role ARN: '$ROLE_ARN'"; exit 1; }
[[ "$IMAGE" =~ ^public\.ecr\.aws/[a-z0-9][a-z0-9._-]*/jaws$ ]] || { echo "::error::JAWS_PUBLIC_IMAGE is not public.ecr.aws/<alias>/jaws: '$IMAGE'"; exit 1; }
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

The module docstring says: the generic image goes to ECR Public with the publishing role, only from the `publish` environment, never for a tag cut before it, never over a tag already published, and not at all until the owner has set the two variables. `DOCKERFILE` and `OLD_DOCKERFILE` come from `tests/test_cli_image.py`. `_decide` passes `fakes={"curl": FAKE_CURL}`, and puts `FAKE_LOG`, `FAKE_HTTP_CODE` and any `MANIFEST_TYPES` in the step's environment.

```python
NEUTRAL = {
    "ROLE_ARN": "arn:aws:iam::123456789012:role/release-infra-publish",
    "IMAGE": "public.ecr.aws/example-alias/jaws",
    "TAG": "v0.79.0",
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
    assert "https://public.ecr.aws/v2/example-alias/jaws/manifests/v0.79.0" in calls


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
- `test_the_public_image_is_the_generic_target_pushed_under_the_tag`. The `docker/build-push-action` step has `target == "generic"`, `push is True`, `platforms == "linux/amd64"` and `tags == "${{ env.IMAGE }}:${{ env.TAG }}"`.
- `test_it_is_pushed_with_the_publishing_role_alone`. It checks:
  - the environment's name is `publish`, and the permissions are `{"contents": "read", "id-token": "write"}`;
  - `role-to-assume == "${{ vars.JAWS_PUBLISH_ROLE_ARN }}"` and `aws-region == "us-east-1"`;
  - the ECR login has `registry-type == "public"`;
  - `env["IMAGE"] == "${{ vars.JAWS_PUBLIC_IMAGE }}"`.
- `test_it_needs_no_configuration_and_no_apply`. `public-image`'s `needs == ["release-please", "public-image-check"]`, and the check job's `needs == "release-please"`.
- `test_the_public_job_runs_only_when_the_check_says_so`. It checks:
  - `public-image`'s `if` is exactly `!cancelled() && needs.public-image-check.outputs.publish == 'true'`;
  - the check job has no `environment`, and `permissions == {"contents": "read"}`;
  - its `if` equals the `account` job's, after whitespace is normalized.
- `test_only_the_public_image_job_enters_publish_or_takes_the_publishing_role`. Across `.github/workflows/*.yml`:
  - the only job whose environment is `publish` is `("release-please.yml", "public-image")`;
  - `vars.JAWS_PUBLISH_ROLE_ARN` appears only in `release-please.yml`, in those two jobs.

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
    - a published tag is never replaced, and a re-publish fills in a missing one. Tags cut before the generic image are never published;
    - ECR Public keeps every image, so pruning is by hand.
  - **`README.md:646`:** after the `image` job, the public image job, which needs only Release Please.
  - **`README.md:648`:** "No role ARN is a secret. This repository needs one as a variable, `JAWS_PUBLISH_ROLE_ARN`, the publishing role in `release-infra/`, so that no account ID appears outside that folder (spec 6.8)." The rest of the paragraph stays.
  - **`README.md`, "Owner hand-off":** after the `prod` environment, add the `publish` environment, restricted to `main`; then `release-infra/` and its variables, pointing to [release-infra/README.md](release-infra/README.md).
  - **`CONTRIBUTING.md:97`:** step 3 also names the public image job, once publishing is set up.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/release-please.yml tests/test_public_image.py README.md CONTRIBUTING.md
git commit -m "feat(cli): publish the generic image to ECR Public on each release"
```

---

### Task 6: Open the pull request

- [ ] **Step 1: Commit the plan, and its rulings to the roadmap**
  - Row 04's status becomes "in its pull request".
  - Row 05 adds:
    - the platform stacks in the image have no backend, so the hub's runs write theirs from `state`;
    - the helper scripts are not in the image;
    - the Databricks stacks are in the image;
    - the public address is `vars.JAWS_PUBLIC_IMAGE`, and its digests can be read anonymously.
  - Row 06 adds: the hub's `Dockerfile` is the `jaws-cli` stage on the public image.
  - Row 07 adds:
    - cleanup removes the `jaws-cli` stage and the release's `image` job;
    - `tests/test_release_infra.py`'s checks against `config/` become literals;
    - the owner-values guard exempts `release-infra/`.
  - "During plan 04" becomes this plan's owner hand-off, steps 1–5.

```bash
git add docs/superpowers/plans/2026-11-23-hub-split-04-images.md docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md
git commit -m "docs(cli): add plan 04 of the hub split and its rulings to the roadmap"
```

- [ ] **Step 2: Run the full `AGENTS.md` checklist** (it now includes `release-infra/`), then Task 3's Step 5 commands.
Expected: every command passes.

- [ ] **Step 3: Push the branch and open the PR**
  - Title: `feat(cli): ship a generic image with every stack, and publish it to ECR Public`.
  - Body: `.github/pull_request_template.md`, with every section filled in.
    - It links the spec and this plan.
    - It says merging changes nothing in AWS, and that nothing is published before the owner's steps.
    - Its "Owner hand-off" section is this plan's, steps 1–6.

```bash
gh pr create --title "feat(cli): ship a generic image with every stack, and publish it to ECR Public" --body-file <file>
```

Expected:
- CI passes, "Image build and smoke test" and "Release infrastructure validate, tflint, test" included;
- the `Terraform plan`, `Monitoring plan` and `Data access plan` comments say merging leaves AWS alone.
