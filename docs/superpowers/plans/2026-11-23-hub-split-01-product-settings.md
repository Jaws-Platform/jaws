# Jaws as a product, plan 01: product settings: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate what a Jaws release owns from what a platform configures, and run the product's tests on a neutral platform configuration instead of the owner's.

**Architecture:**
- The Terraform version and the module family versions move from `config/terraform.yaml` into a packaged `src/jaws/product.yaml`. `jaws.product` reads it, and so do CI and the version tests.
- Everything else a platform needn't set becomes a default in `jaws.settings`: timeouts, logging, the plan comment size, cache headers and the bot health check. A platform configuration that still sets a release-owned key is refused, with a pointer to the release file.
- The tests switch from the owner's `config/` to `tests/fixtures/platform/`, a copy with every identifying value replaced. The few tests that check the owner's own configuration move to `tests/platform/`, which plan 06 carries to the hub.

**Tech Stack:** Python 3.13, uv, Pydantic v2, Typer, PyYAML, pytest, Terraform 1.14.7 (`terraform test` with mock providers), GitHub Actions, yq.

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md), sections 6.1 and 6.2. Roadmap: [2026-11-23-hub-split-00-roadmap.md](2026-11-23-hub-split-00-roadmap.md).

## Global Constraints

- **The repository's rules (`AGENTS.md`):**
  - never push to `main`: one branch, one PR;
  - each commit is a single line, `type(scope): subject`, at most 100 characters, with a lowercase imperative subject and no trailing period;
  - the scope comes from `SCOPES` in `commitlint.config.mjs`, and this plan uses `cli`;
  - only `Co-authored-by:` trailers may follow, after a blank line;
  - the PR title is a valid commit header, and the PR body fills every template section.
- **Never touch real infrastructure.** Never run `terraform apply`, `jaws apply|publish|release|destroy`, or a plan against real state. Only `terraform test` (mock providers) and `scripts/test-stack-plans.sh`.
- **Nothing in AWS changes.** The owner's platform behaves exactly as before. Every value removed from `config/` equals the default that replaces it.
- **The rule, verbatim from the spec (6.2):** "A value the platform's owner chooses, or that identifies their accounts, organizations, people or brand, belongs to the hub. A value tied to how a Jaws release works is a product default. The hub may override it only where a platform has a real reason to."
- **Owned by the release, not overridable:**
  - `terraform.version`: `1.14.7`;
  - `library.families`: `Jaws-Platform/jaws-ci/aws: 0.4.0`, `jaws-databricks: 0.2.0`, `jaws-foundation: 0.2.0`, `jaws-lichess-bot: 0.1.4`, `jaws-monitoring: 0.8.2`, `jaws-network: 0.1.2`, `jaws-research: 0.1.2`, `jaws-static-site: 0.1.2`. The `Jaws-Platform/…/aws` address is elided after the first; these are today's values in `config/terraform.yaml`.
- **Product defaults a platform may override:**
  - `tool.log_level: info`, `tool.log_format: console`;
  - `terraform.lock_timeout: 120s`, `terraform.plan_timeout: 15m`;
  - `sync.cache_control: public, max-age=3600`;
  - `sync.preview_cache_control: public, max-age=300`;
  - `sync.html_cache_control: public, max-age=0, must-revalidate`;
  - `sync.immutable_cache_control: public, max-age=31536000, immutable`;
  - `bot.health_log_pattern: awaiting challenges`, `bot.health_seconds: 90`.
- **A product constant, not configurable:** the plan comment size, 60000 bytes.
- **Off limits:** `owner-access/` and `billing-export/` are not touched.
- **Owner values in files:** never write an owner value into a file outside `config/` and `tests/platform/`. Refer to it by its path in `config/`.
- **The privacy hook:** if a hook refuses to read a file because it holds the owner's email, stop and ask the owner to make that edit themselves (they can run it with `!`). Never work around the hook.
- **Before the PR:** run the `AGENTS.md` checklist: `terraform fmt -recursive`, the `validate` and `test` commands, `tflint`, `npm test`, `uv run ruff format --check && uv run ruff check && uv run mypy && uv run pytest`, and `scripts/test-stack-plans.sh`.

## Review Focus

1. **A configuration copied from today's files.** The hub's first configuration (plan 06) will be exactly this: still carrying `library`, `terraform.version` or `plan`. It must be refused with a message naming `src/jaws/product.yaml`, whether it's a directory or a single file. Task 2, `test_release_owned_keys_are_refused`.
2. **A partial section.** A platform that sets only part of a section, such as only `terraform.lock_timeout` or only `sync.cache_control`, keeps the defaults for the rest. Task 2, `test_a_partial_section_keeps_the_other_defaults`.
3. **An override out of range.** `bot.health_seconds: 5` is still refused. Task 2, `test_an_override_out_of_range_is_still_refused`.
4. **`JAWS_LOG_LEVEL` with no `tool` section.** It is still honored. Task 2, `test_the_log_level_variable_works_without_a_tool_section`.
5. **An owner value left behind.** One could survive where the fixture switch didn't look: a tfvars or registry fixture, the foundation's generated fixtures, a `.tftest.hcl`, the CLI's help text. The guard catches it. Task 3, `test_no_product_file_holds_an_owner_value`.

---

### Task 1: The release's pins: `src/jaws/product.yaml` and `jaws.product`

**Files:**
- Create: `src/jaws/product.yaml`
- Create: `src/jaws/product.py`
- Test: `tests/test_product.py`

**Interfaces:**
- Consumes: `jaws.errors.ConfigError`.
- Produces:
  - `jaws.product.PRODUCT_FILE: Path`, which is `Path(__file__).with_name("product.yaml")`.
  - `jaws.product.PLAN_COMMENT_MAX_BYTES: int = 60000`.
  - `@dataclass(frozen=True) class ProductPins`, with fields `terraform_version: str` and `families: Mapping[str, str]`.
  - `def load_product_pins(path: Path = PRODUCT_FILE) -> ProductPins`: uncached. It raises `ConfigError` on a malformed file.
  - `def product_pins() -> ProductPins`: `functools.cache`d, reading `PRODUCT_FILE`. Runtime code uses this one.

- [ ] **Step 1: Write the failing tests** in `tests/test_product.py`

```python
def test_the_release_pins_terraform_and_every_family() -> None:
    pins = product_pins()
    assert pins.terraform_version == "1.14.7"
    assert pins.families["Jaws-Platform/jaws-ci/aws"] == "0.4.0"
    assert pins.families["Jaws-Platform/jaws-monitoring/aws"] == "0.8.2"
    assert len(pins.families) == 8


def test_the_comment_size_is_the_release_s() -> None:
    assert PLAN_COMMENT_MAX_BYTES == 60000


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "terraform: {version: '1.14'}\nlibrary: {families: {a/b/aws: 0.1.0}}\n",
            "terraform.version",
        ),
        ("terraform: {version: 1.14.7}\nlibrary: {families: {}}\n", "library.families"),
        (
            "terraform: {version: 1.14.7}\nlibrary: {families: {not-an-address: 0.1.0}}\n",
            "registry address",
        ),
        (
            "terraform: {version: 1.14.7}\nlibrary: {families: {a/b/aws: '~> 0.1'}}\n",
            "exact version",
        ),
    ],
)
def test_a_malformed_release_file_is_refused(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "product.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_product_pins(path)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_product.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jaws.product'`

- [ ] **Step 3: Create `src/jaws/product.yaml`**

The keys keep today's shape, so `yq -r .terraform.version src/jaws/product.yaml` works:

```yaml
# What this Jaws release is built with. The image installs this Terraform and
# vendors these module family versions, so a platform's configuration cannot
# change them. Every pin of a family in stacks/ carries its version here
# (tests/test_versions.py checks).
terraform:
  version: 1.14.7
library:
  families:
    Jaws-Platform/jaws-ci/aws: 0.4.0
    Jaws-Platform/jaws-databricks/aws: 0.2.0
    Jaws-Platform/jaws-foundation/aws: 0.2.0
    Jaws-Platform/jaws-lichess-bot/aws: 0.1.4
    Jaws-Platform/jaws-monitoring/aws: 0.8.2
    Jaws-Platform/jaws-network/aws: 0.1.2
    Jaws-Platform/jaws-research/aws: 0.1.2
    Jaws-Platform/jaws-static-site/aws: 0.1.2
```

- [ ] **Step 4: Implement `src/jaws/product.py`** with the Interfaces above.

Move `_FAMILY_ADDRESS`, `_FAMILY_VERSION` and both error messages from `LibrarySection` in `src/jaws/settings.py:80-104` here, unchanged. Add two messages:
- "terraform.version must be an exact version such as 1.14.7, not {value!r}";
- "library.families must name at least one module family".

Prefix each message with the file's path. Read the file with `yaml.safe_load`.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest tests/test_product.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add src/jaws/product.yaml src/jaws/product.py tests/test_product.py
git commit -m "feat(cli): pin terraform and the module families in the release's own file"
```

---

### Task 2: The platform configuration stops owning release values

**Files:**
- Modify: `src/jaws/settings.py`, which covers:
  - `TerraformSection` (63-77);
  - `LibrarySection` (80-104, removed);
  - `SyncSection` (238-242);
  - `BotSection` (245-249);
  - `PlanSection` (881-882, removed);
  - the `Settings` fields (888-899);
  - `load_settings` (1078-).
- Modify: `src/jaws/stack.py:571-590` (`check_version`)
- Modify: `src/jaws/cli.py:594`, `src/jaws/cli.py:688`, `src/jaws/databricks.py:527` (the comment size)
- Modify: `config/terraform.yaml`, `config/tool.yaml`, `config/sites.yaml`, `config/bots.yaml`
- Modify: `tests/test_settings.py`, `tests/test_versions.py`, `tests/test_stack.py`
- Modify: `.github/workflows/ci.yml:416-418,437`, `.github/workflows/release-please.yml:203-206`, `Dockerfile:5-6`
- Modify: `config/README.md`, `AGENTS.md` (the family-pin rule), and `README.md` wherever it names `library.families` or the Terraform version in `config/terraform.yaml`
- Regenerate: `foundation/tests/fixtures/*.yaml`

**Interfaces:**
- Consumes: `product_pins()`, `PLAN_COMMENT_MAX_BYTES` (Task 1).
- Produces:
  - `Settings` has no `library` and no `plan`.
  - `Settings.terraform: TerraformSection = TerraformSection()`, with only `lock_timeout` and `plan_timeout`, plus the `plan_timeout_seconds` property.
  - `Settings.sync: SyncSection = SyncSection()`, with every field defaulted.
  - `BotSection.health_log_pattern` and `health_seconds` are defaulted.
  - `load_settings` refuses `library`, `terraform.version` and `plan` with a `ConfigError` whose message names the key and `src/jaws/product.yaml`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_settings.py`, add a module-level helper:

```python
def _write(tmp_path: Path, raw: dict[str, Any], single_file: bool) -> Path:
    """`raw` as a config directory, one file per section, or as one file."""
```

Then add the tests:

```python
@pytest.mark.parametrize("single_file", [False, True])
@pytest.mark.parametrize(
    ("extra", "key"),
    [
        ({"library": {"families": {"a/b/aws": "0.1.0"}}}, "library"),
        ({"terraform": {"version": "1.14.7"}}, "terraform.version"),
        ({"plan": {"comment_max_bytes": 60000}}, "plan"),
    ],
)
def test_release_owned_keys_are_refused(tmp_path, extra, key, single_file) -> None:
    raw = {**fixture_config(), **extra}
    with pytest.raises(ConfigError, match=rf"{re.escape(key)}.*src/jaws/product\.yaml"):
        load_settings(_write(tmp_path, raw, single_file), environ={})


def test_product_defaults_fill_what_the_platform_leaves_out(tmp_path) -> None:
    raw = fixture_config()
    for section in ("tool", "terraform", "sync"):
        raw.pop(section, None)
    raw["bot"].pop("health_log_pattern", None)
    raw["bot"].pop("health_seconds", None)
    settings = load_settings(_write(tmp_path, raw, single_file=True), environ={})
    assert (settings.tool.log_level, settings.tool.log_format) == ("info", "console")
    assert settings.terraform.lock_timeout == "120s"
    assert settings.terraform.plan_timeout_seconds == 900
    assert settings.sync.cache_control == "public, max-age=3600"
    assert settings.sync.preview_cache_control == "public, max-age=300"
    assert settings.sync.html_cache_control == "public, max-age=0, must-revalidate"
    assert settings.sync.immutable_cache_control == "public, max-age=31536000, immutable"
    assert (settings.bot.health_log_pattern, settings.bot.health_seconds) == (
        "awaiting challenges",
        90,
    )


def test_a_partial_section_keeps_the_other_defaults(tmp_path) -> None:
    raw = {
        **fixture_config(),
        "terraform": {"lock_timeout": "300s"},
        "sync": {"cache_control": "public, max-age=60"},
    }
    settings = load_settings(_write(tmp_path, raw, single_file=True), environ={})
    assert (settings.terraform.lock_timeout, settings.terraform.plan_timeout) == ("300s", "15m")
    assert settings.sync.cache_control == "public, max-age=60"
    assert settings.sync.html_cache_control == "public, max-age=0, must-revalidate"


def test_an_override_out_of_range_is_still_refused(tmp_path) -> None:
    raw = fixture_config()
    raw["bot"]["health_seconds"] = 5
    with pytest.raises(ConfigError, match=r"bot\.health_seconds"):
        load_settings(_write(tmp_path, raw, single_file=True), environ={})


def test_the_log_level_variable_works_without_a_tool_section(tmp_path) -> None:
    raw = fixture_config()
    raw.pop("tool", None)
    settings = load_settings(
        _write(tmp_path, raw, single_file=True), environ={"JAWS_LOG_LEVEL": "debug"}
    )
    assert settings.tool.log_level == "debug"
```

Change `SECTION_FILES` to the new layout. It drops `terraform`, `library`, `tool`, `plan` and `sync`, and keeps `state` in `terraform.yaml`, `context` and `ecr` in `tool.yaml`, `dns` in `sites.yaml`, and the rest as they are.

In `tests/test_versions.py`, `_families()` returns `dict(product_pins().families)`.

In `tests/test_stack.py`, the Terraform version-mismatch case expects `RunError` matching `src/jaws/product\.yaml`. Use the existing fake binary in `tests/fixtures/bin/terraform`, the way the file's other version tests do. Add the case if none exists.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_settings.py tests/test_versions.py tests/test_stack.py -v`
Expected: the new tests FAIL. Release-owned keys are accepted, or the defaults are missing. `test_every_section_is_in_its_file` fails because `config/` still has the old sections.

- [ ] **Step 3: Implement the settings changes**

In `src/jaws/settings.py`:
- Drop `TerraformSection.version`.
- Delete `LibrarySection` and `PlanSection`.
- Give `SyncSection` and `BotSection.health_*` the Global Constraints defaults, keeping `health_seconds` at `Field(default=90, ge=10, le=600)`.
- Default `Settings.terraform` and `Settings.sync`, and remove `Settings.library` and `Settings.plan`.

In `load_settings`, after the `JAWS_*` overrides and before validation, refuse `library`, `terraform.version` and `plan` with:

> `{path}: {key}: this belongs to the Jaws release (src/jaws/product.yaml), not the platform configuration`

- [ ] **Step 4: Point the readers at the release**

- `Terraform.check_version` in `src/jaws/stack.py` compares against `product_pins().terraform_version`. On mismatch it raises: "terraform {actual} is on PATH but this Jaws release is built with {expected} (src/jaws/product.yaml)". Update the docstring to match.
- `src/jaws/cli.py:594`, `src/jaws/cli.py:688` and `src/jaws/databricks.py:527` use `PLAN_COMMENT_MAX_BYTES`.

- [ ] **Step 5: Take the release values out of `config/`**

Every removed value equals its default.
- `config/terraform.yaml` keeps only `state`, and its header becomes "Where every stack's state lives."
- `config/tool.yaml` loses its `tool:` and `plan:` blocks.
- `config/sites.yaml` loses `sync:`.
- `config/bots.yaml` loses `health_log_pattern` and `health_seconds`. Move their comment to the field docs in `BotSection`.
- If `tests/conftest.py` builds its fixture document by hand rather than from `config/`, remove the same keys there.

- [ ] **Step 6: CI and the image read the release file**

- `.github/workflows/ci.yml:416-418` and `.github/workflows/release-please.yml:203-206` become `yq -r .terraform.version src/jaws/product.yaml`. Name the steps "Read the Terraform version from the release (src/jaws/product.yaml)".
- `ci.yml:437` becomes a real comparison, which also proves `product.yaml` ships in the installed package:

```yaml
      - name: Smoke test (the image's Terraform is the release's, and the release file ships)
        run: |
          docker run --rm --network none --entrypoint python jaws:ci -c '
          import json, subprocess
          from jaws.product import product_pins
          out = subprocess.run(["terraform", "version", "-json"], capture_output=True, text=True, check=True).stdout
          actual, expected = json.loads(out)["terraform_version"], product_pins().terraform_version
          assert actual == expected, f"image has terraform {actual}, the release pins {expected}"
          print("terraform", actual, "is the release pin")'
```

- `Dockerfile:5-6`: in the comments, replace `config/terraform.yaml` with `src/jaws/product.yaml`.

- [ ] **Step 7: Docs**

- **`config/README.md`:**
  - the table rows become `terraform.yaml` → `state`, `tool.yaml` → `context`, `ecr`, `sites.yaml` → `dns`;
  - drop `terraform` from the list of sections that `yq` reads;
  - add one paragraph: the Terraform version and module family versions are the release's (`src/jaws/product.yaml`), and the product's defaults for logging, timeouts, cache headers and the bot health check apply unless a section here overrides them.
- **`AGENTS.md`:** replace "the family's entry under `library.families` in `config/terraform.yaml`" with "the family's entry in `src/jaws/product.yaml`".
- **`README.md`:** the same substitution wherever it occurs.

- [ ] **Step 8: Regenerate the foundation's fixtures**

Run: `uv run python -m tests.test_foundation_fixtures`
Expected: `foundation/tests/fixtures/*.yaml` lose the removed sections.

- [ ] **Step 9: Run everything**

Run: `uv run ruff format --check && uv run ruff check && uv run mypy && uv run pytest -q`
Expected: PASS

Run: `(cd foundation && terraform init -backend=false && terraform test) && scripts/test-stack-plans.sh`
Expected: PASS. The foundation reads none of the removed keys.

- [ ] **Step 10: Commit**

```bash
git add -A src/jaws config tests .github/workflows Dockerfile AGENTS.md README.md foundation/tests/fixtures
git commit -m "refactor(cli): keep release pins and product defaults out of the platform config"
```

---

### Task 3: The product's tests run on a neutral platform configuration

**Files:**
- Create: `tests/fixtures/platform/{aws,projects,terraform,tool,sites,bots,databricks,monitoring}.yaml`
- Create: `tests/platform/__init__.py`, `tests/platform/test_isolation.py`, `tests/platform/test_no_owner_values.py`, `tests/platform/test_config_layout.py`, `tests/platform/test_foundation_backend.py`
- Modify: `tests/conftest.py`
- Modify: every test whose assertion names an identifying value. The likely set is the files that use the configuration fixtures: `test_settings`, `test_one_account`, `test_cli`, `test_databricks_workflows`, `test_stack`, `test_jaws_action`, `test_secret_names`, `test_image`, `test_monitoring_stack`, `test_foundation_workflows`, `test_components`, `test_access_render`, `test_access_files`, `test_access_cli`, `test_tasks_run`, `test_cli_databricks`, `test_bots_registry`, `test_bot_schedule`, `checks/test_databricks_config`, `checks/test_databricks_live`. Also any file under `tests/fixtures/` holding an owner value.
- Modify: `foundation/tests/foundation.tftest.hcl`, `tests/test_foundation_fixtures.py` (its docstring and generated header), `AGENTS.md` (the sentence on how the tests read `config/`)
- Modify: `src/jaws/cli.py:75` (the help text names the owner's zone)
- Regenerate: `foundation/tests/fixtures/*.yaml`

**Interfaces:**
- Consumes: the configuration shape after Task 2.
- Produces:
  - `tests.conftest.CONFIG_DIR = REPO_ROOT / "tests" / "fixtures" / "platform"`: the configuration every product test uses. The existing helpers built on it (`repo_config()`, `fixture_config()`, `baseline_config_path()`) keep their names and now see the fixture.
  - `tests.conftest.PLATFORM_CONFIG_DIR = REPO_ROOT / "config"`: only `tests/platform/` may use it.
  - `tests/platform/`: checks of the owner's own configuration. Plan 06 moves them to the hub.

**The neutral values.** The fixture is `config/` after Task 2, file for file, with these replacements and nothing else changed:

| Path | Fixture value |
|---|---|
| `aws.accounts.<management>.account_id` | `"111111111111"` |
| `aws.accounts.<production>.account_id` | `"222222222222"` |
| `aws.accounts.<development>.account_id` | `"333333333333"` |
| `aws.accounts.<production>.admin_role_arn` | `arn:aws:iam::222222222222:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_0123456789abcdef` |
| `state.bucket`, `monitoring.cost.bucket` | the same names, with `222222222222` as the account suffix |
| `context.organization` / `context.owner` | `Example-Platform` / `example-owner` |
| `dns.zone` / `dns.zone_id` | `example.com` / `Z0000000000EXAMPLE` |
| every domain in or under the zone | the same name under `example.com` |
| `databricks.account_id` / `databricks.client_id` | `00000000-0000-4000-8000-000000000001` / `00000000-0000-4000-8000-000000000002` |
| `databricks.shared_host_url` | `https://dbc-00000000-0000.cloud.databricks.com` |
| every email address | `owner@example.com` |
| the projects group keyed by the owner's personal login | keyed `example-owner` |
| every `owner_id` | `"10000001"`, `"10000002"`, …, in file order |
| every `repository_id` | `"20000001"`, `"20000002"`, …, in file order |

These stay the same, as example names: project keys, the other organization names, repository names, instance types, limits, schedules, policies, AMI names, prefixes and SSM paths. Plan 07 decides whether the examples are renamed when the docs that share them are rewritten.

- [ ] **Step 1: Write the failing platform checks**

`tests/platform/test_isolation.py`:

```python
def test_only_platform_checks_read_the_owner_s_configuration() -> None:
    """tests/platform/ checks the owner's config/; every other test uses the fixture."""
    tests = REPO_ROOT / "tests"
    readers = sorted(
        path.relative_to(tests).as_posix()
        for path in tests.rglob("*.py")
        if path.relative_to(tests).parts[0] != "platform"
        and (
            "PLATFORM_CONFIG_DIR" in path.read_text() or 'REPO_ROOT / "config"' in path.read_text()
        )
    )
    assert readers == ["conftest.py"]
```

`tests/platform/test_no_owner_values.py` declares:
- `def owner_values() -> set[str]`, built from `load_document(PLATFORM_CONFIG_DIR)`. It collects:
  - every account ID and `admin_role_arn`;
  - `context.owner`;
  - `dns.zone` and `dns.zone_id`;
  - `databricks.account_id`, `databricks.client_id` and the host of `databricks.shared_host_url`;
  - every string in the document that matches an email address;
  - every `owner_id` and `repository_id`.

  It leaves out `context.organization`, which is still `Jaws-Platform`, the vendor's own name, until the hub exists.
- `def _scanned_files() -> list[Path]`: every file under `src/jaws/`, `tests/` and `foundation/tests/`. It excludes `tests/platform/`, `__pycache__` and binaries, which are files that don't decode as UTF-8.

```python
@pytest.mark.parametrize(
    "path", _scanned_files(), ids=lambda p: p.relative_to(REPO_ROOT).as_posix()
)
def test_no_product_file_holds_an_owner_value(path: Path) -> None:
    text = path.read_text()
    found = sorted(value for value in owner_values() if value in text)
    assert not found, (
        f"{path.relative_to(REPO_ROOT)} holds values from config/ that identify the owner"
    )
```

The message must not print the values; it names only the file.

`tests/platform/test_config_layout.py` takes `SECTION_FILES` and `test_every_section_is_in_its_file` from `tests/test_settings.py`, unchanged except that they read `PLATFORM_CONFIG_DIR`. It adds:

```python
def test_the_owner_s_configuration_loads() -> None:
    load_settings(PLATFORM_CONFIG_DIR, environ={})


def test_the_fixture_has_every_section_the_owner_uses() -> None:
    assert set(load_document(CONFIG_DIR)) == set(load_document(PLATFORM_CONFIG_DIR))
```

`tests/platform/test_foundation_backend.py` takes the `backend/prod.hcl` bucket check from `tests/test_foundation_workflows.py:133-136`, reading `PLATFORM_CONFIG_DIR`.

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/platform -v`
Expected: FAIL. `PLATFORM_CONFIG_DIR` can't be imported, and the guard flags `tests/` files and `src/jaws/cli.py`.

- [ ] **Step 3: Create `tests/fixtures/platform/`** from `config/` and the table.

Keep one header line per file: `# A neutral platform configuration for the product's tests: config/'s shape, with every identifying value replaced (tests/platform/test_no_owner_values.py).` Drop config/'s long comments.

- [ ] **Step 4: Repoint `tests/conftest.py`**

Point `CONFIG_DIR` at the fixture, add `PLATFORM_CONFIG_DIR`, and replace any owner value conftest holds with its table value.

- [ ] **Step 5: Make the suite pass on the fixture**

Run: `uv run pytest -q`

Work through each failure by the rule:
- An assertion that names an identifying value takes the fixture's value.
- A test that checks the owner's configuration itself, its values or its file layout, moves to `tests/platform/` and reads `PLATFORM_CONFIG_DIR`.
- A fixture file under `tests/fixtures/` holding an owner value takes the table's value.

`test_repository_config_loads` stays a product test and asserts the fixture's values:
- `jaws-cli`;
- `jaws-terraform-state-222222222222`;
- `example.com`.

- [ ] **Step 6: Clear the source and the foundation's tests**

- `src/jaws/cli.py:75`: the help text becomes "Provisions and publishes a site from jaws.yaml."
- `foundation/tests/foundation.tftest.hcl`: replace identifying values with the table's.
- `tests/test_foundation_fixtures.py`: the docstring and the generated header say "Generated from tests/fixtures/platform/".

Then run: `uv run python -m tests.test_foundation_fixtures`

- [ ] **Step 7: Update `AGENTS.md`**

Replace the sentence "The tests read `config/` itself; after changing it, regenerate the foundation's test fixtures …" with:

> The product's tests read `tests/fixtures/platform/`, a neutral copy of `config/`'s shape. Checks of the owner's own configuration live in `tests/platform/`. After changing the fixture, regenerate the foundation's test fixtures with `uv run python -m tests.test_foundation_fixtures` (a test checks).

- [ ] **Step 8: Run everything**

Run: `uv run ruff format --check && uv run ruff check && uv run mypy && uv run pytest -q`
Expected: PASS, including `tests/platform/`.

Run: `(cd foundation && terraform init -backend=false && terraform test) && scripts/test-stack-plans.sh`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add -A tests src/jaws/cli.py foundation/tests AGENTS.md
git commit -m "test(cli): run the product's tests on a neutral platform configuration"
```

---

### Task 4: Open the pull request

- [ ] **Step 1: Commit the design and the plans with the work they describe**

```bash
git add docs/superpowers/specs/2026-11-22-hub-split-design.md docs/superpowers/plans/2026-11-23-hub-split-*.md
git commit -m "docs(cli): add the hub split design, its roadmap and plan 01"
```

- [ ] **Step 2: Run the full `AGENTS.md` checklist**

Run the "Before opening a PR" block in `AGENTS.md`.
Expected: every command passes.

- [ ] **Step 3: Push the branch and open the PR**

- Title: `refactor(cli): separate the release's settings from the platform's`.
- Body: `.github/pull_request_template.md`, with every section filled in. "Owner hand-off" is "n/a: nothing in AWS changes". The body links the spec and this plan.

```bash
gh pr create --title "refactor(cli): separate the release's settings from the platform's" --body-file <file>
```

Expected: CI passes, including "Image build and smoke test" with the new release-pin check.
