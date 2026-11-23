# Jaws as a product, plan 02: white-label hooks: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a platform put its own name, mark, check-name prefix, tags, `ManagedBy` and name root on everything Jaws builds and posts, with Jaws's values as the defaults, so nothing changes for the owner yet.

**Architecture:**
- **The brand.** A new `brand` section (`name`, `mark`, `check_prefix`) heads every PR comment and titles the CLI's workflow annotations.
  - Under any brand but Jaws's, the footer says "Built with Jaws vX.Y.Z".
  - Step summaries carry no product name today, so they stay as they are.
- **The platform's own tags.** `context` keeps `name_root`, `organization`, `owner` and `managed_by`, and gains `tags`.
  - They are stamped on everything, after the project file's tags.
  - A project file may not state them, as it may not state `Organization` and `ManagedBy`.
- **`ManagedBy`.** The four project stacks check it against a new `managed_by` variable, which the CLI renders from `context.managed_by`. Today they check it against the literal `JAWS`.
- **The name root.** Three things that still spell `jaws` follow `context.name_root`. Each changes in the CLI and in every Terraform root or script that spells it today:
  - the monitoring secrets' prefix;
  - the Databricks defaults;
  - the platform's own project: the foundation's `Project` tag and Name prefix.
- **The bot image's labels.** The engine labels leave the product's Dockerfile. The CLI adds them with `--label`, under the platform's DNS zone reversed. For the owner's zone, that is today's `engineering.jwall.*`, byte for byte.
- **Already configuration, so nothing to do here:**
  - the `Organization` tag of the platform's own stacks (`context.organization`);
  - every other name (`<name_root>-<project>-...`, `/<name_root>/<project>/...`).

**Decision: check names.**
- This plan puts the prefix in the configuration (`brand.check_prefix`) and the CLI: `jaws config env --brand` prints `check_prefix=<prefix>`. No workflow file changes.
- Plan 05 gives an input, `check-prefix` (default `jaws`), to the four project-facing jobs that start with `jaws` today:
  - `jaws plan` in `site-plan.yml`;
  - `jaws release` in `site-deploy.yml`;
  - `jaws preview deploy` and `jaws preview remove` in `site-preview.yml`.
- Plan 05 names them `${{ inputs.check-prefix }} plan` and so on. The hub's callers fill the input from `jaws config env --brand`, run in the hub image.
- With the default, every check name stays as it is, so no ruleset's required check changes. No other job name takes the prefix.

**Tech Stack:** Python 3.13, uv, Pydantic v2, Typer, PyYAML, pytest, Terraform 1.14.7 (`terraform test` with mock providers), yq, Docker (faked in tests).

**Spec:** [2026-11-22-hub-split-design.md](../specs/2026-11-22-hub-split-design.md), section 6.7 and decision 8 in section 4. Roadmap: [row 02](2026-11-23-hub-split-00-roadmap.md). Builds on [plan 01](2026-11-23-hub-split-01-product-settings.md), which merges first.

## Global Constraints

- **The repository's rules (`AGENTS.md`):**
  - Never push to `main`. Work on one branch, `hub-split/02-white-label`, made from `main`. Plan 01 merged as #314; its Task 3, the neutral test fixture, is still deferred.
  - Each commit is a single line, `type(scope): subject`, at most 100 characters, with a lowercase imperative subject and no trailing period.
  - The scope comes from `SCOPES` in `commitlint.config.mjs`. This plan uses `cli`, the scope of the CLI and the stacks it renders.
  - Only `Co-authored-by:` trailers may follow, after a blank line.
  - The PR title is a valid commit header, and the PR body fills every template section.
- **Never touch real infrastructure.**
  - Never run `terraform apply`, `jaws apply|publish|release|destroy`, or a plan against real state.
  - Only `terraform test` (mock providers) and `scripts/test-stack-plans.sh`.
  - CI's own pull request plans are the evidence that nothing changes in AWS.
- **Nothing changes for the owner.**
  - Every new setting defaults to today's value, and the owner's `config/` is not edited.
  - Every plan of the owner's stacks shows no changes: the foundation, monitoring, data access, and every bot, research and Databricks project.
  - Tests prove that each default reproduces today's string exactly:
    - `brand.name: Jaws`, `brand.mark: 🦈` and `brand.check_prefix: jaws`;
    - `context.tags`: none, with `context.managed_by: JAWS` unchanged;
    - with `name_root: jaws`: `/jaws/monitoring/`, `/jaws/databricks/client-secret`, `jaws-us-east-1`, `jaws-databricks-audit-logs`, and the foundation's `Project` tag, `jaws`;
    - the bot image's engine labels: `<the DNS zone, reversed>.engine.version` and `.engine.source`.
- **The white-label line, verbatim from the spec (4.8):** "The company's, set in the hub, with Jaws's as the default: the name and mark on PR comments and step summaries, and the check names; the GitHub App that posts comments; the name root of every resource and secret; the `Organization` and `ManagedBy` tags, plus any tags to stamp on everything (new); the hub image's name. Jaws's, where needed: the project file stays `jaws.yaml`; comments keep a small "built with Jaws vX.Y.Z" line; the hub image records which Jaws release it is built from."
- **Jaws keeps, verbatim from 6.7:** "Things no project team sees stay Jaws's: the CLI's name and the image's internal paths (`/opt/jaws`, `/etc/jaws`)."
  - These carry the CLI's name, so they stay:
    - the SSM command comments (`jaws task run`, `jaws deploy`, `jaws bot stop`);
    - the CloudFront invalidation reference `jaws-<sha>-<environment>`;
    - the `User-Agent`;
    - the logger name and `.jaws/`.
  - The run records' `provider=jaws` also stays: it is the source name Jaws's monitoring module reads.
- **The region stays `us-east-1`, a product constant (6.7).**
- **Not in this plan:**
  - the workflows: job names, step names and the comments App (plan 05);
  - the foundation's identity, with its `Repository` and `Owner` literals (plan 03). Plan 03 leaves its `Project` tag to this plan (Task 6);
  - the hub image's name, and the CLI image's `Dockerfile` label (plans 03 and 04);
  - the CLI's help text naming the owner's zone (plan 01, Task 3);
  - the hub's own values, JWall Engineering's name, mark and App (plan 06);
  - `owner-access/` and `billing-export/`, which are off limits.
- **Plan 03 runs in parallel** and edits `foundation/` and `monitoring/`.
  - It rewrites `local.context` in `foundation/context.tf`, `_relabelled` in `tests/test_foundation_fixtures.py`, and the run named `takes_its_managed_by_from_the_configuration`.
  - Keep this plan's Terraform edits to the lines each task names, and give its fixtures their own names, so the second plan to merge rebases cleanly.
- **Tests:**
  - New tests assert no owner-identifying value: no account ID, email, the owner's zone or GitHub IDs.
  - They build what they need from `fixture_config()`, from the `settings`, `site`, `bot` and `databricks` fixtures with `model_copy`, or from tmp configs. That keeps plan 01's deferred fixture switch cheap.
  - `tests/conftest.py`, `config/databricks.yaml` and `config/projects.yaml` are not read or edited.
- **The privacy hook:** if a hook refuses a command because a file holds the owner's email, stop and ask the owner. Never work around it.
- **Before the PR:** run the `AGENTS.md` checklist:
  - `terraform fmt -recursive`, then the `validate` and `test` commands and `tflint`;
  - `npm test`;
  - `uv run ruff format --check && uv run ruff check && uv run mypy && uv run pytest`;
  - `scripts/test-stack-plans.sh`.

## Review Focus

1. **A brand that sets only its name.** `brand: {name: Acme}` must not put Jaws's shark beside another company's name. It has no mark until it states one, and it keeps the `jaws` check prefix. Task 1, `test_a_brand_that_names_itself_does_not_inherit_the_shark`.
2. **A platform tag that a project file already states.**
   - The case: the platform adds `context.tags.Department` while a project's `jaws.yaml` states `Department`.
   - That project's plan and apply are refused, naming the key and where it is set.
   - Its stop commands still load, and the platform's value wins.

   Task 3, `test_a_project_file_cannot_state_a_platform_tag` and `test_the_stop_commands_still_load_a_file_that_states_a_platform_tag`.
3. **A platform tag that shadows one jaws or a stack sets.** A `context.tags` key that is `Project`, `Name`, `Component`, `CostCenter` or `RunId`, or that starts with `aws:`, is refused when the configuration loads, before any plan. Task 3, `test_a_platform_tag_cannot_shadow_a_tag_jaws_sets`.
4. **Another name root.**
   - With `name_root: acme`, the monitoring secrets, the Slack channels' prefix and the Databricks names all move to `acme`.
   - A Slack channel left under `/jaws/monitoring/` is refused, and the message names the prefix it needs.

   Task 4, `test_slack_channels_live_under_the_name_root_s_secrets`. Task 5, `test_the_databricks_names_a_platform_leaves_out_follow_its_name_root`.
5. **Brand text that isn't plain.**
   - A mark that is an image URL becomes an `<img>`.
   - A `&` in a name or a URL is escaped.
   - An `http://` mark is refused.
   - A name with `,` or `:` still makes a valid annotation title.

   Task 1, `test_an_image_mark_is_an_img_tag`, `test_the_brand_s_text_is_escaped`, `test_a_bad_brand_names_its_key` and `test_an_error_annotation_carries_the_platform_s_name`.

---

### Task 1: The platform's brand on comments and annotations, and the check-name prefix

**Files:**
- Modify: `src/jaws/settings.py`: a new `BrandSection` after `ContextSection` (187-196), and `Settings.brand` (fields at 860-875)
- Modify: `src/jaws/report.py`:
  - the docstring (1-8) and the constants (18-22);
  - `_header` (119-127) and `_footer` (134-146);
  - the four comment functions (247-277, 313-371, 374-393, 396-404).
- Modify: `src/jaws/cli.py`: the annotation at 224, the comment calls at 592-600, 636, 660 and 686-692, and `config_env` (965-1003)
- Modify: `src/jaws/databricks.py:525-532`, `src/jaws/log.py:98-104,124-132`, `config/README.md`
- Test: `tests/test_settings.py`, `tests/test_report.py`, `tests/test_one_account.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `jaws.settings.BrandSection`, a frozen section with three fields:
    - `name: str = "Jaws"`;
    - `mark: str | None = "🦈"`;
    - `check_prefix: str = "jaws"`.

    A mapping that sets `name` and leaves out `mark` gets `mark=None`.
  - `Settings.brand: BrandSection = BrandSection()`.
  - In `jaws.report`:
    - `PRODUCT = "Jaws"` stays, as the footer's name for the product;
    - `PRODUCT_MARK` is deleted;
    - `MARK_HEIGHT = 28` is new.
  - `plan_comment`, `stacks_plan_comment`, `preview_comment` and `preview_removed_comment` gain a required keyword-only `brand: BrandSection` after their current parameters.
  - `jaws.log.annotate_error(message: str, title: str)` and `annotate_warning(message: str, title: str)` lose their `"Jaws"` default titles.
  - `jaws config env --brand` appends `check_prefix=<brand.check_prefix>`. Without the flag, the output is unchanged.

- [ ] **Step 1: Write the failing tests**

In `tests/test_settings.py`, using its `_load_raw(tmp_path, raw)`:

```python
def test_the_brand_is_jaws_s_unless_the_platform_sets_one(tmp_path: Path) -> None:
    raw = fixture_config()
    raw.pop("brand", None)
    brand = _load_raw(tmp_path, raw).brand
    assert (brand.name, brand.mark, brand.check_prefix) == ("Jaws", "🦈", "jaws")


def test_a_brand_that_names_itself_does_not_inherit_the_shark(tmp_path: Path) -> None:
    brand = _load_raw(tmp_path, {**fixture_config(), "brand": {"name": "Acme Platform"}}).brand
    assert (brand.name, brand.mark, brand.check_prefix) == ("Acme Platform", None, "jaws")


@pytest.mark.parametrize(
    ("brand", "key"),
    [
        ({"name": ""}, "brand.name"),
        ({"name": " Acme"}, "brand.name"),
        ({"name": "A" * 41}, "brand.name"),
        ({"mark": "http://example.com/mark.png"}, "brand.mark"),
        ({"mark": "two words"}, "brand.mark"),
        ({"mark": "123456789"}, "brand.mark"),
        ({"check_prefix": "acme/ci"}, "brand.check_prefix"),
        ({"check_prefix": "-acme"}, "brand.check_prefix"),
        ({"check_prefix": "a" * 31}, "brand.check_prefix"),
        ({"colour": "teal"}, "brand.colour"),
    ],
)
def test_a_bad_brand_names_its_key(tmp_path: Path, brand: dict[str, str], key: str) -> None:
    with pytest.raises(ConfigError, match=re.escape(key)):
        _load_raw(tmp_path, {**fixture_config(), "brand": brand})
```

In `tests/test_report.py`:
- every existing call to the four comment functions gains `brand=JAWS`;
- import `StackSection`, `stacks_plan_comment`, `pytest` and `jaws.settings.BrandSection`;
- add:

```python
JAWS = BrandSection()
ACME = BrandSection(name="Acme Platform", mark="🔧")
IMAGE = "https://raw.githubusercontent.com/Example-Org/example-branding/main/mark.png"
KINDS = ["plan", "stacks", "preview", "removed"]


def _comments(brand: BrandSection) -> dict[str, str]:
    """Every kind of comment the tool posts, for `brand`."""
    account = StackSection("Account stack", PLAN_CHANGES, PLAN_WITH_CHANGES)
    return {
        "plan": plan_comment(PLAN_CHANGES, PLAN_WITH_CHANGES, 60000, "a.example", PROVENANCE, brand=brand),
        "stacks": stacks_plan_comment([account], None, 60000, "dbx", PROVENANCE, brand=brand),
        "preview": preview_comment("https://pr-3.preview.a.example/", 3, "a.example", PROVENANCE, brand=brand),
        "removed": preview_removed_comment(3, "a.example", PROVENANCE, brand=brand),
    }  # fmt: skip


def _footer(comment: str) -> str:
    return next(line for line in comment.splitlines() if line.startswith('<p align="center"><sub>'))


def _header(brand: BrandSection) -> str:
    return _comments(brand)["removed"].splitlines()[0]


@pytest.mark.parametrize("kind", KINDS)
def test_jaws_s_brand_keeps_today_s_header_and_footer(kind: str) -> None:
    comment = _comments(JAWS)[kind]
    assert comment.splitlines()[0] == '<h2 align="center">🦈 Jaws</h2>'
    assert _footer(comment).startswith('<p align="center"><sub><b>Jaws</b> v0.9.1 &nbsp;·&nbsp; ')


def test_the_plan_comment_s_footer_is_today_s_to_the_byte() -> None:
    assert _footer(_comments(JAWS)["plan"]) == (
        '<p align="center"><sub><b>Jaws</b> v0.9.1 &nbsp;·&nbsp; Commit '
        '<a href="https://github.com/o/r/commit/193fcc3deadbeef0000000000000000000000000">'
        "<code>193fcc3</code></a> &nbsp;·&nbsp; "
        '<a href="https://github.com/o/r/actions/runs/1">Workflow run</a> &nbsp;·&nbsp; '
        "Updated on every push</sub></p>"
    )


@pytest.mark.parametrize("kind", KINDS)
def test_a_platform_s_brand_heads_every_comment(kind: str) -> None:
    comment = _comments(ACME)[kind]
    assert comment.splitlines()[0] == '<h2 align="center">🔧 Acme Platform</h2>'
    assert "🦈" not in comment
    assert _footer(comment).startswith('<p align="center"><sub>Built with <b>Jaws</b> v0.9.1')


def test_an_image_mark_is_an_img_tag() -> None:
    assert _header(BrandSection(name="Acme Platform", mark=IMAGE)) == (
        f'<h2 align="center"><img src="{IMAGE}" alt="" height="28"> Acme Platform</h2>'
    )


def test_a_brand_without_a_mark_shows_its_name_alone() -> None:
    assert _header(BrandSection(name="Acme Platform")) == '<h2 align="center">Acme Platform</h2>'


def test_the_brand_s_text_is_escaped() -> None:
    assert _header(BrandSection(name="Smith & Jones", mark=f"{IMAGE}?v=1&s=2")) == (
        f'<h2 align="center"><img src="{IMAGE}?v=1&amp;s=2" alt="" height="28"> '
        "Smith &amp; Jones</h2>"
    )
```

In `tests/test_one_account.py`, add `fixture_config` to the conftest import, then:
- `test_config_env_prints_the_check_prefix_of_the_job_names`, parametrized over two cases:
  - no `brand`, which gives `check_prefix=jaws`;
  - `brand: {name: Acme Platform, check_prefix: acme}`, which gives `check_prefix=acme`.
- It runs `config env --brand` on `_write(tmp_path, raw)` and asserts the last stdout line.

In `tests/test_cli.py`, add `fixture_config` to the conftest import, then:

```python
def _branded_config(tmp_path: Path, brand: dict[str, str]) -> Path:
    path = tmp_path / "branded.yaml"
    path.write_text(yaml.safe_dump({**fixture_config(), "brand": brand}))
    return path


@pytest.mark.parametrize(
    ("name", "title"),
    [("Acme Platform", "Acme Platform"), ("Acme, Inc.: Platform", "Acme%2C Inc.%3A Platform")],
)
def test_an_error_annotation_carries_the_platform_s_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, title: str
) -> None:
    config = _branded_config(tmp_path, {"name": name})
    monkeypatch.chdir(tmp_path)  # no jaws.yaml here: validate fails with a ConfigError
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    result = runner.invoke(cli.app, ["--config", str(config), "validate"])
    assert result.exit_code == 2
    assert f"::error title={title}::" in result.output
```

Also add `test_report_plan_comment_carries_the_platform_s_brand`. It is `test_report_plan_comment_renders_a_plan_log` with `--config` set to `_branded_config(tmp_path, {"name": "Acme Platform", "mark": "🔧"})`, and it asserts `out.read_text().splitlines()[0] == '<h2 align="center">🔧 Acme Platform</h2>'`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_settings.py tests/test_report.py tests/test_one_account.py tests/test_cli.py -q`
Expected: FAIL with `ImportError: cannot import name 'BrandSection' from 'jaws.settings'`

- [ ] **Step 3: Add `BrandSection` and `Settings.brand` to `src/jaws/settings.py`**

- **`name`:** `pattern=r"^\S(?:.{0,38}\S)?$"`: 1 to 40 characters, with no leading or trailing whitespace and no newline.
- **`mark`:** a `field_validator`.
  - `None` passes.
  - A value starting with `https://` must match `^https://[^\s"'<>]+$` and be at most 512 characters.
  - Anything else is a text mark: 1 to 8 characters, with no whitespace, and not starting with `http`.
  - The error message is "an emoji or text of at most 8 characters, or an https:// image URL; null for none".
- **`check_prefix`:** `Field(default="jaws", max_length=30, pattern=r"^[A-Za-z0-9]+(?:[ ._-][A-Za-z0-9]+)*$")`.
- **A `model_validator(mode="before")`:** a mapping with `name` but no `mark` becomes a copy with `mark: None`.
- **The field docs:**
  - the header shows the mark and the name;
  - the footer keeps "Built with Jaws";
  - `check_prefix` is the first word of the project-facing workflows' job names.

- [ ] **Step 4: Render the brand in `src/jaws/report.py`**

- `_header(kind, subject, brand, extra=None)`: the `<h2 align="center">` holds one of three forms, with each value passed through `html.escape`:
  - `<img src="{mark}" alt="" height="{MARK_HEIGHT}"> {name}` for an `https://` mark;
  - `{mark} {name}` for a text mark;
  - `{name}` alone when there is no mark.
- `_footer(provenance, brand, note=None)`: the first part is `<b>{PRODUCT}</b> v{version}` when `brand.name == PRODUCT`, else `Built with <b>{PRODUCT}</b> v{version}`.
- The four comment functions pass `brand` down. Their byte budgets already measure the header.
- The docstring's "a centred product header" becomes "a centred header with the platform's brand".

- [ ] **Step 5: Pass the brand from the callers, and escape annotation titles**

- `src/jaws/cli.py:592-600`, `636`, `660` and `686-692` pass `brand=run.settings.brand`. `src/jaws/databricks.py:525-532` passes `brand=self.settings.brand`.
- `src/jaws/cli.py:224`: `annotate_error(str(exc), title=run.settings.brand.name)`.
- `src/jaws/log.py`, `_emit_workflow_command`: escape each property value as GitHub's toolkit does:
  - `%` to `%25`;
  - `\r` to `%0D` and `\n` to `%0A`;
  - `:` to `%3A` and `,` to `%2C`.
- `config_env` gains a `--brand` flag, with the help text "Also print `check_prefix=<brand.check_prefix>`, the first word of the workflows' job names." It appends its line after the other optional lines.
- `config/README.md` gets a section, "The brand":
  - `brand` goes in `tool.yaml`, next to `context`;
  - `name` defaults to `Jaws`;
  - `mark` is an emoji, short text, or an `https://` image URL such as one the organization's branding repository publishes. It defaults to `🦈`, `null` means none, and a brand that sets its `name` gets none unless it states one;
  - `check_prefix` defaults to `jaws`;
  - comments keep a small "Built with Jaws vX.Y.Z" line.

- [ ] **Step 6: Run the tests and watch them pass**

Run: `uv run pytest tests/test_settings.py tests/test_report.py tests/test_one_account.py tests/test_cli.py -q && uv run mypy`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/jaws/settings.py src/jaws/report.py src/jaws/cli.py src/jaws/databricks.py src/jaws/log.py config/README.md tests/test_settings.py tests/test_report.py tests/test_one_account.py tests/test_cli.py
git commit -m "feat(cli): head comments with the platform's brand and add a check-name prefix"
```

---

### Task 2: `ManagedBy` is checked against the platform's value

**Files:**
- Modify: `stacks/site/variables.tf` (`name_root` 15-23, `tags` 84-87), `stacks/bot/variables.tf` (19-27, 56-59), `stacks/databricks-account/variables.tf` (27-35, 64-71), `stacks/databricks-workspace/variables.tf` (28-36, 60-68)
- Modify: `src/jaws/stack.py`: the returns at 126-135, 140-149, 209-213, 367-372 and 447-452
- Modify: `src/jaws/site.py:30-41,199-211`
- Modify: `tests/stack_plans/render.py` and both `tests/stack_plans/databricks-*/databricks_poc.tftest.hcl`
- Create: `tests/stack_plans/bot/relabelled.tftest.hcl`
- Modify: `docs/tagging.md`, `README.md:262-267`
- Test: `tests/test_stack.py`, `tests/test_site.py`, `tests/test_stack_plans.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - Every rendered tfvars, for a site, bot, research project and both Databricks stacks, has `"managed_by": <context.managed_by>`, equal to `tags["ManagedBy"]`.
  - Each stack has a required `variable "managed_by"`, with no default.
  - `jaws.site.MANAGED_BY` is deleted.
  - `tests.stack_plans.render._relabelled(settings: Settings) -> Settings` returns `settings` with `context.managed_by = "ACME"`, through `model_copy`. Task 3 adds tags to it.
  - A bot case, `relabelled`: the braveheart sample, with its guardrails, under `_relabelled`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_stack.py`:
- `test_rendered_tfvars_match_the_old_infra_directories` also asserts `tfvars["managed_by"] == "JAWS"`.
- `ACCOUNT_TFVARS_KEYS` and `WORKSPACE_TFVARS_KEYS` gain `"managed_by"`.
- The dict in `test_databricks_account_tfvars` gains `"managed_by": "JAWS"`.
- `_strip_new_keys` drops `"managed_by"`.
- Add:

```python
@pytest.mark.parametrize("stack", ["site", "bot", "databricks-account", "databricks-workspace"])
def test_every_stack_checks_managed_by_against_the_configured_value(stack: str) -> None:
    variables = (REPO_ROOT / "stacks" / stack / "variables.tf").read_text()
    assert 'variable "managed_by"' in variables
    assert 'lookup(var.tags, "ManagedBy", "") == var.managed_by' in variables
    assert '"JAWS"' not in variables


def _every_stack(
    site: Site, bot: Project, databricks: Project, settings: Settings, **update: Any
) -> list[dict[str, Any]]:
    """The tfvars of every stack kind, each target copied with `update`."""
    return [
        render_tfvars(site.model_copy(update=update)),
        render_tfvars(bot.model_copy(update=update), settings),
        *(
            render_tfvars(databricks.model_copy(update=update), settings, stack=s, account_outputs=ACCOUNT_OUTPUTS)
            for s in ("account", "workspace")
        ),
    ]  # fmt: skip


def test_every_stack_is_rendered_the_platform_s_managed_by(
    site: Site, bot: Project, databricks: Project, settings: Settings
) -> None:
    for tfvars in _every_stack(site, bot, databricks, settings, managed_by="ACME"):
        assert tfvars["managed_by"] == tfvars["tags"]["ManagedBy"] == "ACME"
```

In `tests/test_site.py`:
- drop the `MANAGED_BY` import;
- `test_a_stated_managed_by_is_refused` takes `["JAWS", "jaws", "hand"]`;
- it matches `r"tags\.ManagedBy is set by jaws \(context\.managed_by in config/tool\.yaml\); remove it"`.

In `tests/test_stack_plans.py`, add `test_the_relabelled_case_is_another_platform_s`:

```python
relabelled = cases(_settings())["bot"]["relabelled"]
assert relabelled["managed_by"] == relabelled["tags"]["ManagedBy"] == "ACME"
```

Create `tests/stack_plans/bot/relabelled.tftest.hcl`:

```hcl
# The braveheart sample on a platform with its own ManagedBy: the stack accepts
# the value the CLI stamps, and only that value.
mock_provider "aws" {
  source = "./tests/mocks"
}

run "accepts_the_platform_s_managed_by" {
  command = plan

  assert {
    condition     = var.managed_by == "ACME" && var.tags["ManagedBy"] == "ACME"
    error_message = "ManagedBy is the platform's context.managed_by, and the stack checks the tag against it"
  }
}

run "refuses_a_managed_by_the_platform_did_not_stamp" {
  command = plan

  variables {
    managed_by = "JAWS"
  }

  expect_failures = [var.tags]
}
```

Add the same `refuses_a_managed_by_the_platform_did_not_stamp` run to both `databricks_poc.tftest.hcl` files, with `managed_by = "ACME"`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_stack.py tests/test_site.py tests/test_stack_plans.py -q`
Expected: FAIL. No `managed_by` is rendered, the stacks spell `"JAWS"`, and `cases()` has no `relabelled`, so `test_every_rendered_case_has_a_test_file_and_the_reverse` fails.

- [ ] **Step 3: Add the variable and the check to the four stacks**

Add this block after `name_root` in each stack:

```hcl
variable "managed_by" {
  description = "The ManagedBy tag the platform stamps on everything (config/tool.yaml `context.managed_by`, `JAWS` unless the platform sets another). tags.ManagedBy must equal it."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9]+(-[A-Za-z0-9]+)*$", var.managed_by))
    error_message = "managed_by must be letters, digits and single hyphens, such as JAWS."
  }
}
```

In each `tags` validation:
- `lookup(var.tags, "ManagedBy", "") == "JAWS"` becomes `lookup(var.tags, "ManagedBy", "") == var.managed_by`;
- the message's "must be `JAWS` (stamped by the CLI)" becomes "must equal managed_by (context.managed_by, stamped by the CLI)".

- [ ] **Step 4: Render it, and name the setting in the refusal**

- `src/jaws/stack.py`: each of the five renderers adds `"managed_by"`, from `site.managed_by` or `project.managed_by`.
- `src/jaws/site.py`: delete `MANAGED_BY` and its comment (39-41). `_no_tool_tags` gives the source of `ManagedBy` as `context.managed_by in config/tool.yaml`.
- `tests/stack_plans/render.py`: add `_relabelled`, and `"relabelled": (_file("braveheart"), _relabelled(sample))` in `bots`.
- `docs/tagging.md`, "How each stack gets them": "refuse any `ManagedBy` other than `JAWS`" becomes "refuse a `ManagedBy` other than their `managed_by` variable, which the CLI renders from `context.managed_by`".
- `README.md:266`: "`ManagedBy` (`JAWS`)" becomes "`ManagedBy` (`context.managed_by`, `JAWS` by default)".

- [ ] **Step 5: Run the tests and the stack plans, and watch them pass**

Run: `uv run pytest tests/test_stack.py tests/test_site.py tests/test_stack_plans.py -q && scripts/test-stack-plans.sh`
Expected: PASS, including `== bot/relabelled` and both Databricks refusal runs.

Run the four stack `terraform validate` lines from `AGENTS.md`, then `tflint --recursive`.
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add stacks/*/variables.tf src/jaws/stack.py src/jaws/site.py tests/stack_plans tests/test_stack.py tests/test_site.py tests/test_stack_plans.py docs/tagging.md README.md
git commit -m "feat(cli): check ManagedBy against the platform's value in every stack"
```

---

### Task 3: The platform's own tags, on everything, never from a project file

**Files:**
- Modify: `src/jaws/settings.py`: `RESERVED_TAG_KEYS`, and `ContextSection.tags` (187-196)
- Modify: `src/jaws/site.py`: `stamped_tags` (276-278), a new `platform_tag_problems`, and `Site` (field 293-302, `from_config` 305-330, `tags` 337-339)
- Modify: `src/jaws/project.py`: the field (44-55), the site branch (63-74), `if check_guardrails:` (123-124), the constructor (127-141), `tags` (152-154)
- Modify: `foundation/context.tf:52-63`, `monitoring/config.tf:35-46` (the `module "context"` blocks)
- Modify: `tests/test_foundation_fixtures.py` (a new fixture), `foundation/tests/foundation.tftest.hcl`, `monitoring/tests/monitoring.tftest.hcl`, `tests/stack_plans/render.py`, `tests/stack_plans/bot/relabelled.tftest.hcl`
- Create (generated): `foundation/tests/fixtures/platform-tags.yaml`
- Modify: `docs/tagging.md`, `config/README.md`, `README.md:403`
- Test: `tests/test_settings.py`, `tests/test_site.py`, `tests/test_components.py`, `tests/test_stack.py`, `tests/test_tasks_launch.py`, `tests/test_stack_plans.py`

**Interfaces:**
- Consumes: Task 2's `_relabelled`, the `relabelled` bot case, and `_every_stack` in `tests/test_stack.py`.
- Produces:
  - `jaws.settings.RESERVED_TAG_KEYS: tuple[str, ...]`, the keys that a project file, jaws, the modules, Databricks or a task set themselves:
    - `Project`, `Environment`, `Repository` and `Owner`;
    - `Organization` and `ManagedBy`;
    - `Name`, `Component`, `Purpose`, `Profile` and `Lifecycle`;
    - `CostCenter`, `Workspace`, `Vendor`, `Creator`, `ClusterName` and `ClusterId`;
    - `Workflow`, `RunId`, `TaskId`, `MaxLifetimeHours`, `PullRequest` and `Campaign`.
  - `ContextSection.tags: dict[str, str] = {}`.
  - `jaws.site.stamped_tags(tags, organization, managed_by, platform_tags: Mapping[str, str]) -> dict[str, str]` returns `{**tags, **platform_tags, "Organization": ..., "ManagedBy": ...}`.
  - `jaws.site.platform_tag_problems(tags: Mapping[str, str], settings: Settings) -> list[str]` gives one `"tags.<key> is set by jaws (context.tags in config/tool.yaml); remove it"` per platform key that the file states.
  - `Site.platform_tags` and `Project.platform_tags`, both `dict[str, str]`. They are required, and `from_config` sets them from `settings.context.tags`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_settings.py`, import `REQUIRED_TAGS` and `TOOL_TAGS` from `jaws.site`, `DATABRICKS_RESERVED_TAGS` from `jaws.project`, and `RESERVED_TAG_KEYS`. Then:

```python
def test_a_platform_stamps_no_tags_of_its_own_by_default(settings: Settings) -> None:
    assert settings.context.tags == {}


def test_a_platform_s_own_tags_load(tmp_path: Path) -> None:
    raw = fixture_config()
    raw["context"]["tags"] = {"Department": "platform", "cost-pool": "shared/2026"}
    assert _load_raw(tmp_path, raw).context.tags == raw["context"]["tags"]


@pytest.mark.parametrize(
    "key", [*RESERVED_TAG_KEYS, "aws:createdBy", "AWS:Team", "", "a" * 129, "Team!"]
)
def test_a_platform_tag_cannot_shadow_a_tag_jaws_sets(tmp_path: Path, key: str) -> None:
    raw = fixture_config()
    raw["context"]["tags"] = {key: "x"}
    with pytest.raises(ConfigError, match=r"context\.tags"):
        _load_raw(tmp_path, raw)


@pytest.mark.parametrize("value", ["", "   ", "a" * 257, "café", "a;b"])
def test_a_platform_tag_value_is_one_every_service_accepts(tmp_path: Path, value: str) -> None:
    raw = fixture_config()
    raw["context"]["tags"] = {"Department": value}
    with pytest.raises(ConfigError, match=r"context\.tags"):
        _load_raw(tmp_path, raw)


def test_the_reserved_tags_cover_what_files_jaws_and_databricks_set() -> None:
    known = {*REQUIRED_TAGS, *TOOL_TAGS, *DATABRICKS_RESERVED_TAGS, "CostCenter", "Workspace"}
    assert known <= set(RESERVED_TAG_KEYS)
```

`tests/test_site.py` and `tests/test_components.py` each get a helper, `_with_platform_tags(settings, tags) -> Settings`. It returns `settings.model_copy(update={"context": settings.context.model_copy(update={"tags": tags})})`.

In `tests/test_site.py`:
- **`test_the_platform_s_tags_are_stamped_on_a_site`:** `Site.from_config` of `_raw()` under `{"Department": "web"}`; `assert site.tags["Department"] == "web"`.
- **`test_a_site_file_cannot_state_a_platform_tag`:** `_raw({"tags.Department": "mine"})` under the same settings raises `ConfigError` matching `r"tags\.Department is set by jaws \(context\.tags in config/tool\.yaml\); remove it"`.

In `tests/test_components.py`, with its `_raw()` and `_load(tmp_path, raw, settings)`:

```python
def test_a_project_file_cannot_state_a_platform_tag(tmp_path: Path, settings: Settings) -> None:
    raw = _raw()
    raw["tags"]["Department"] = "chess"
    with pytest.raises(ConfigError, match=r"tags\.Department is set by jaws \(context\.tags"):
        _load(tmp_path, raw, _with_platform_tags(settings, {"Department": "research"}))


def test_the_stop_commands_still_load_a_file_that_states_a_platform_tag(
    tmp_path: Path, settings: Settings
) -> None:
    """Like a guardrail change, a new platform tag must not strand an instance."""
    raw = _raw()
    raw["tags"]["Department"] = "chess"
    path = tmp_path / "jaws.yaml"
    path.write_text(yaml.safe_dump(raw))
    tagged = _with_platform_tags(settings, {"Department": "research"})
    project = Project.from_config(load_site_config(path), tagged, check_guardrails=False)
    assert project.tags["Department"] == "research"
```

Then the remaining tests:
- **`tests/test_components.py`, `test_a_bot_carries_the_platform_s_tags`:** `_load(tmp_path, _raw(), _with_platform_tags(settings, {"Department": "research"})).tags["Department"] == "research"`.
- **`tests/test_stack.py`, `test_every_stack_is_rendered_the_platform_s_tags`:** every `tfvars` in `_every_stack(..., platform_tags={"Department": "research"})` has `tfvars["tags"]["Department"] == "research"`.
- **`tests/test_tasks_launch.py`:**
  - `test_a_task_carries_the_platform_s_tags`: `tasks.task_tags(_spec(bot.model_copy(update={"platform_tags": {"Department": "research"}})), "spot")["Department"] == "research"`;
  - `test_a_task_s_own_tags_are_reserved_from_the_platform`: for `tags = tasks.task_tags(_spec(bot, pull_request="84", campaign="nnue-v2"), "spot")`, assert `set(tags) - set(bot.config.tags) <= set(RESERVED_TAG_KEYS)`.
- **`tests/test_stack_plans.py`:** `test_the_relabelled_case_is_another_platform_s` also asserts `relabelled["tags"]["Department"] == "research"`. The `accepts_the_platform_s_managed_by` condition in `relabelled.tftest.hcl` adds `&& var.tags["Department"] == "research"`.
- **`tests/test_foundation_fixtures.py`:** a new fixture, `"platform-tags.yaml": _platform_tags`. It sets `config["context"]["tags"] = {"Department": "platform"}`. Its docstring is "A tag of the platform's own: the platform's stacks stamp it from the file." It is not `_relabelled`, which plan 03 rewrites.
- **`foundation/tests/foundation.tftest.hcl`:** a new run, `stamps_the_platform_s_own_tags`, with `config_path = "tests/fixtures/platform-tags.yaml"` and the condition `module.context.tags["Department"] == "platform"`.
- **`monitoring/tests/monitoring.tftest.hcl`:** the same run, with `config_path = "../foundation/tests/fixtures/platform-tags.yaml"`. That fixture is `config/` as one file, with the tag.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_settings.py tests/test_site.py tests/test_components.py tests/test_stack.py tests/test_tasks_launch.py tests/test_stack_plans.py -q`
Expected: FAIL with `ImportError: cannot import name 'RESERVED_TAG_KEYS' from 'jaws.settings'`

- [ ] **Step 3: Add `RESERVED_TAG_KEYS` and `ContextSection.tags`**

- `RESERVED_TAG_KEYS` holds exactly the Interfaces block's keys. Its comment points at the sources, which `settings` cannot import:
  - `site.REQUIRED_TAGS` and `site.TOOL_TAGS`;
  - `project.DATABRICKS_RESERVED_TAGS`;
  - `tasks.task_tags`.
- A `field_validator("tags")` refuses a failing key with `context.tags.<key>: <reason>`. A key fails when:
  - it is in `RESERVED_TAG_KEYS`: "jaws or a stack sets this tag itself";
  - it starts with `aws:`, in any case: "AWS reserves keys that start with aws:";
  - it doesn't match `^[A-Za-z0-9 +\-=._:/@]{1,128}$`;
  - its value doesn't match `^(?=.*\S)[A-Za-z0-9 +\-=._:/@]{1,256}$`. That is the character set `tasks._TAG_VALUE_UNSAFE` keeps, because RunInstances and Databricks take no more.
- The field doc says the tags are stamped on every resource, after the project file's, and that a file may not state them.

- [ ] **Step 4: Stamp and refuse them in `src/jaws/site.py` and `src/jaws/project.py`**

- `Site.tags` and `Project.tags` pass `self.platform_tags` to `stamped_tags`.
- `Site.from_config` extends `problems` with `platform_tag_problems(config.tags, settings)`, and sets `platform_tags=dict(settings.context.tags)`.
- `Project.from_config`:
  - the site branch copies `site.platform_tags`;
  - the other branch adds `platform_tag_problems` inside `if check_guardrails:`, so the cleanup commands still load such a file, and the platform's value wins;
  - it sets `platform_tags`.
- `tasks.task_tags` already spreads `project.tags` first, so it needs no change.

- [ ] **Step 5: Stamp them on the platform's own stacks**

- In each `module "context"`, the library's module merges `extra_tags` under the six required tags:
  - `foundation/context.tf`: `extra_tags = try(local.account.context.tags, {})`;
  - `monitoring/config.tf`: `extra_tags = try(local.tool_config.context.tags, {})`.

  The default runs' exact tag assertions prove that nothing changes without the key.
- `tests/stack_plans/render.py`: `_relabelled` also sets `context.tags = {"Department": "research"}`.
- Run: `uv run python -m tests.test_foundation_fixtures`. Expected: a new `platform-tags.yaml`, with the other fixtures unchanged.

- [ ] **Step 6: Docs**

- **`docs/tagging.md`:**
  - The opening says every resource carries the six tags "and any the platform stamps on everything (`context.tags`)".
  - A new section, "The platform's own tags", covers:
    - where they are set: `config/tool.yaml`, with none by default;
    - what carries them: every stack the CLI renders, every task instance, and the foundation's and monitoring's resources. The owner's `owner-access/` and `billing-export/` do not;
    - that a project file may not state them, though the cleanup commands still load such a file;
    - that they may not use a reserved key or `aws:`.
  - "Adding a tag" gains a bullet: a tag the platform wants on everything, that only it knows, goes in `context.tags`.
- **`config/README.md`:** the `tool.yaml` row adds "the platform's own tags".
- **`README.md:403`:** "the same six tags" becomes "the same six tags, plus the platform's own (`context.tags`)".

- [ ] **Step 7: Run the tests and watch them pass**

Run: `uv run pytest -q && uv run mypy`
Expected: PASS, including `test_every_fixture_file_is_accounted_for`

Run: `(cd foundation && terraform init -backend=false && terraform test) && (cd monitoring && terraform init -backend=false && terraform test) && scripts/test-stack-plans.sh`
Expected: PASS, including both `stamps_the_platform_s_own_tags` runs

- [ ] **Step 8: Commit**

```bash
git add src/jaws/settings.py src/jaws/site.py src/jaws/project.py foundation/context.tf monitoring/config.tf foundation/tests monitoring/tests tests docs/tagging.md config/README.md README.md
git commit -m "feat(cli): stamp the platform's own tags on everything, never from a project file"
```

---

### Task 4: The monitoring secrets live under the name root

**Files:**
- Modify: `src/jaws/settings.py`:
  - `MONITORING_SECRETS_PREFIX` (479-481);
  - `MonitoringSlack._channels` (647-662);
  - a new `Settings` validator after `_monitoring_domain_in_the_zone` (948-956).
- Modify: `src/jaws/monitoring.py` (1-47), `src/jaws/cli.py:116,2246,2267`, `monitoring/main.tf:44-46`
- Test: `tests/test_settings.py`, `tests/test_cli_monitoring.py`, `tests/test_monitoring_stack.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `jaws.settings.monitoring_secrets_prefix(name_root: str) -> str`, which returns `f"/{name_root}/monitoring/"`. `MONITORING_SECRETS_PREFIX` is removed.
  - `jaws.monitoring.secret_parameters(section: MonitoringSection, *, name_root: str) -> dict[str, str]`.
  - `jaws.monitoring.secret_parameter(section: MonitoringSection, name: str, *, name_root: str) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings.py
ACME_MONITORING = {
    "ami": "al2023-ami-2023.12.20261026.1-kernel-6.18-arm64",
    "slack": {"channels": {"platform": "/acme/monitoring/slack/platform"}, "routes": {"host": "platform"}},
}  # fmt: skip


def test_the_monitoring_secrets_live_under_the_name_root() -> None:
    assert monitoring_secrets_prefix("jaws") == "/jaws/monitoring/"
    assert monitoring_secrets_prefix("acme") == "/acme/monitoring/"


def test_slack_channels_live_under_the_name_root_s_secrets(tmp_path: Path) -> None:
    raw = fixture_config()
    raw["context"]["name_root"] = "acme"
    raw["monitoring"] = copy.deepcopy(ACME_MONITORING)
    raw["monitoring"]["slack"]["channels"]["platform"] = "/jaws/monitoring/slack/platform"
    with pytest.raises(
        ConfigError,
        match=r"monitoring\.slack\.channels\.platform '/jaws/monitoring/slack/platform' must "
        r"be an SSM parameter under /acme/monitoring/, such as /acme/monitoring/slack/platform",
    ):
        _load_raw(tmp_path, raw)
    raw["monitoring"] = copy.deepcopy(ACME_MONITORING)
    assert _load_raw(tmp_path, raw).monitoring is not None
```

- **`tests/test_cli_monitoring.py`, `test_the_secrets_follow_the_name_root`:** the file defines its own `ACME_MONITORING`, the same mapping. With `section = MonitoringSection.model_validate(ACME_MONITORING)`:

  ```python
  assert monitoring.secret_parameters(section, name_root="acme") == {
      "grafana-admin-user": "/acme/monitoring/grafana-admin-user",
      "grafana-admin-password": "/acme/monitoring/grafana-admin-password",
      "slack/platform": "/acme/monitoring/slack/platform",
  }
  ```

  and `monitoring.secret_parameter(section, "grafana-admin-user", name_root="acme") == "/acme/monitoring/grafana-admin-user"`.
- **`tests/test_monitoring_stack.py`:** import `monitoring_secrets_prefix` in place of the constant. `test_the_stack_reads_the_secrets_where_the_cli_writes_them` asserts `f'secrets_prefix = "{monitoring_secrets_prefix("${local.name_root}")}"' in _main()`. That is the CLI's derivation, applied to the stack's own interpolation.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_settings.py tests/test_cli_monitoring.py tests/test_monitoring_stack.py -q`
Expected: FAIL with `ImportError: cannot import name 'monitoring_secrets_prefix'`

- [ ] **Step 3: Derive the prefix**

- **`src/jaws/settings.py`:**
  - Replace the constant with `monitoring_secrets_prefix`. The constant's comment becomes the function's docstring.
  - `MonitoringSlack._channels` keeps only its channel-name check.
  - A new `Settings` validator, `_slack_channels_are_the_platform_s_secrets` (`mode="after"`), refuses a channel parameter that doesn't start with `monitoring_secrets_prefix(self.context.name_root)` or doesn't match `_SSM_NAME`. Its message is today's: `f"monitoring.slack.channels.{name} {parameter!r} must be an SSM parameter under {prefix}, such as {prefix}slack/{name}"`.
- **`src/jaws/monitoring.py`:** both functions take `*, name_root`. The docstrings say `/<name_root>/monitoring/`.
- **`src/jaws/cli.py`:** lines 2246 and 2267 pass `name_root=run.settings.context.name_root`. The help text at 116 says "under /<name_root>/monitoring/".
- **`monitoring/main.tf:44-46`:** `secrets_prefix = "/${local.name_root}/monitoring/"`. Its comment names `jaws.settings.monitoring_secrets_prefix`.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest -q && uv run mypy && (cd monitoring && terraform init -backend=false && terraform test)`
Expected: PASS. The monitoring runs still see `/jaws/monitoring/grafana-admin-*`. The settings cases `channel-outside-prefix` and `channel-relative` still name their key.

- [ ] **Step 5: Commit**

```bash
git add src/jaws/settings.py src/jaws/monitoring.py src/jaws/cli.py monitoring/main.tf tests/test_settings.py tests/test_cli_monitoring.py tests/test_monitoring_stack.py
git commit -m "feat(cli): keep the monitoring secrets under the name root"
```

---

### Task 5: The Databricks names follow the name root

**Files:**
- Modify: `src/jaws/settings.py`: the `DatabricksSection` fields (392-393, 400), a new `databricks_defaults`, and a new `Settings` validator
- Modify: `foundation/config.tf:36`, `scripts/databricks-credentials.sh`
- Modify: `tests/test_foundation_fixtures.py`, `foundation/tests/foundation.tftest.hcl`
- Create (generated): `foundation/tests/fixtures/databricks-defaults.yaml`
- Test: `tests/test_settings.py`, `tests/test_databricks_workflows.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `jaws.settings.databricks_defaults(name_root: str) -> dict[str, str]`, which returns three keys. The region in the metastore name is the product constant:
    - `secret_parameter`: `/<name_root>/databricks/client-secret`;
    - `metastore_name`: `<name_root>-us-east-1`;
    - `audit_bucket`: `<name_root>-databricks-audit-logs`.
  - In `DatabricksSection`, `secret_parameter`, `metastore_name` and `audit_bucket` are `str` with no default.
  - `Settings._databricks_names_follow_the_name_root`, a `model_validator(mode="before")`. When the raw `databricks` and `context.name_root` are both present, it fills in the three keys the section leaves out, and returns a new mapping. Every reader keeps reading `section.<name>`.
  - The foundation and the credentials script apply the same defaults. The owner's `config/databricks.yaml` keeps its explicit values.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_settings.py
def test_the_databricks_defaults_are_today_s_names_for_the_jaws_root() -> None:
    assert databricks_defaults("jaws") == {
        "secret_parameter": "/jaws/databricks/client-secret",
        "metastore_name": "jaws-us-east-1",
        "audit_bucket": "jaws-databricks-audit-logs",
    }


@pytest.mark.parametrize("name_root", ["jaws", "acme"])
def test_the_databricks_names_a_platform_leaves_out_follow_its_name_root(
    tmp_path: Path, name_root: str
) -> None:
    raw = fixture_config()
    raw["context"]["name_root"] = name_root
    raw.pop("monitoring", None)  # its Slack channels live under /jaws/monitoring/
    for key in ("secret_parameter", "metastore_name", "audit_bucket"):
        raw["databricks"].pop(key, None)
    section = _load_raw(tmp_path, raw).databricks
    assert section is not None
    assert (section.secret_parameter, section.metastore_name, section.audit_bucket) == (
        f"/{name_root}/databricks/client-secret",
        f"{name_root}-us-east-1",
        f"{name_root}-databricks-audit-logs",
    )
```

**`tests/test_settings.py`, `test_a_databricks_name_the_platform_sets_wins`:** under `name_root: acme`, without `monitoring`, the setting `databricks.audit_bucket: acme-audit` stays `acme-audit`.

**`tests/test_databricks_workflows.py`:**
- Split `_run_credentials` into the existing `_write_databricks` and `_source_credentials(tmp_path: Path, config: str = "config") -> tuple[str, Path, Path]`. The second is the rest of today's function, and it sources the script with `config` as its argument.
- The existing tests call both.
- Add `fixture_config` to the conftest import, then:

```python
@needs_yq
@pytest.mark.parametrize("single_file", [False, True])
def test_a_left_out_parameter_follows_the_name_root(tmp_path: Path, single_file: bool) -> None:
    databricks = {**fixture_config()["databricks"], "enabled": True}
    databricks.pop("secret_parameter", None)
    sections = {"databricks": databricks, "context": {"name_root": "acme"}}
    if single_file:
        (tmp_path / "all.yaml").write_text(yaml.safe_dump(sections))
    else:
        (tmp_path / "config").mkdir()
        for name, file in (("databricks", "databricks.yaml"), ("context", "tool.yaml")):
            (tmp_path / "config" / file).write_text(yaml.safe_dump({name: sections[name]}))
    out, calls, _ = _source_credentials(tmp_path, "all.yaml" if single_file else "config")
    assert "--name /acme/databricks/client-secret" in calls.read_text()
    assert "_dbx_" not in out.split("---\n", 1)[1]
```

**`tests/test_foundation_fixtures.py`:** a new fixture, `"databricks-defaults.yaml": _databricks_defaults`. It pops the three keys from `config["databricks"]`. Its docstring is "Databricks without the names that follow the name root: the foundation derives them as the CLI does."

**`foundation/tests/foundation.tftest.hcl`:** a new run, `the_databricks_names_follow_the_name_root`, with `config_path = "tests/fixtures/databricks-defaults.yaml"`. It asserts:

```hcl
local.databricks.secret_parameter == "/jaws/databricks/client-secret" && local.databricks.metastore_name == "jaws-us-east-1" && local.databricks.audit_bucket == "jaws-databricks-audit-logs"
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_settings.py tests/test_databricks_workflows.py tests/test_foundation_fixtures.py -q`
Expected: FAIL with `ImportError: cannot import name 'databricks_defaults'`. `test_every_fixture_file_is_accounted_for` also fails, until the fixture is generated.

- [ ] **Step 3: Derive the names in `src/jaws/settings.py`**

Add `databricks_defaults` and the validator, and drop the three field defaults. Each field's doc says what the field is when the platform leaves it out.

- [ ] **Step 4: Derive them in the foundation and the credentials script**

- **`foundation/config.tf:36`:** the `databricks` entry of `local.account` becomes the expression below. Its comment is "The names a platform leaves out follow its name root, as jaws.settings.databricks_defaults derives them".

  ```hcl
  merge({
    secret_parameter = "/${local.tool_config.context.name_root}/databricks/client-secret"
    metastore_name   = "${local.tool_config.context.name_root}-us-east-1"
    audit_bucket     = "${local.tool_config.context.name_root}-databricks-audit-logs"
  }, local.tool_config.databricks)
  ```

- **`scripts/databricks-credentials.sh`:**
  - It keeps the argument as `_dbx_source`.
  - `_dbx_context` is `$_dbx_source/tool.yaml` for a directory, or `$_dbx_source` itself for one file.
  - `_dbx_parameter` comes from `yq -r '.databricks.secret_parameter // ""'`. When that is empty, it is `/$(yq -r .context.name_root "$_dbx_context")/databricks/client-secret`.
  - It returns 1 if either `yq` fails.
  - It unsets `_dbx_source` and `_dbx_context` on both exits.
  - The header comment names the fallback.
- Run: `uv run python -m tests.test_foundation_fixtures`. Expected: only the new `databricks-defaults.yaml` appears.

- [ ] **Step 5: Run the tests and watch them pass**

Run: `uv run pytest -q && uv run mypy && (cd foundation && terraform init -backend=false && terraform test)`
Expected: PASS, including `the_databricks_names_follow_the_name_root`. `databricks_is_built_and_onboards_the_registry` is unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/jaws/settings.py foundation/config.tf foundation/tests scripts/databricks-credentials.sh tests/test_settings.py tests/test_databricks_workflows.py tests/test_foundation_fixtures.py
git commit -m "feat(cli): derive the databricks names from the name root"
```

---

### Task 6: The platform's own project is its name root

**Files:**
- Modify: `foundation/context.tf:18-19` (`project` in `local.context`), `monitoring/main.tf:80-88` (`workspace_projects` and its comment)
- Modify: `docs/tagging.md:14,76`, `README.md:408`
- Test: `tests/test_monitoring_stack.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `local.context.project` is `local.account.context.name_root`. It is the foundation's `Project` tag and the prefix of its Name tags, such as `<name_root>-dns-zone`.
  - The monitoring stack gives the shared host's untagged Databricks usage to the same project.
  - `owner-access/` keeps its own `Project = jaws`, because it is off limits.

- [ ] **Step 1: Write the failing test**

In `tests/test_monitoring_stack.py`:

```python
def test_the_platform_s_own_project_is_its_name_root() -> None:
    """The foundation's Project tag, and the shared host's usage, are the name root's."""
    context = (REPO_ROOT / "foundation" / "context.tf").read_text()
    assert re.search(r"^\s+project\s+= local\.account\.context\.name_root$", context, re.MULTILINE)
    assert '{ "${local.name_root}-shared" = local.name_root }' in _main()
```

- [ ] **Step 2: Run it and watch it fail**

Run: `uv run pytest tests/test_monitoring_stack.py -q`
Expected: FAIL, because both files still spell `"jaws"`.

- [ ] **Step 3: Derive the project**

- **`foundation/context.tf:19`:** `project = local.account.context.name_root`. Its comment becomes "Project tag value (the name root, like every name), and the prefix of this stack's Name tags."
- **`monitoring/main.tf:87`:** `{ "${local.name_root}-shared" = local.name_root }`. The comment above it reads "(the foundation's Project tag, the name root)".
- **`docs/tagging.md:14` and `README.md:408`:** "`jaws` for the foundation" becomes "the name root (`jaws`) for the foundation".
- **`docs/tagging.md:76`:** "`Project` `jaws`" becomes "`Project`, the name root".

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest tests/test_monitoring_stack.py -q && (cd foundation && terraform init -backend=false && terraform test) && (cd monitoring && terraform init -backend=false && terraform test)`
Expected: PASS. The default runs still assert `Project = "jaws"`, `name_prefix == "jaws-jaws-prod"` and `"jaws-shared" = "jaws"`.

- [ ] **Step 5: Commit**

```bash
git add foundation/context.tf monitoring/main.tf docs/tagging.md README.md tests/test_monitoring_stack.py
git commit -m "feat(cli): make the platform's own project its name root"
```

---

### Task 7: The bot image's engine labels take the platform's namespace

**Files:**
- Modify: `src/jaws/kinds/lichess_bot/Dockerfile:29-34`, `src/jaws/image.py:120-154`, `src/jaws/cli.py:1346`
- Test: `tests/test_image.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `jaws.image.label_namespace(zone: str) -> str`, the zone's labels reversed: `example.com` becomes `com.example`.
  - `jaws.image.build(context, project, tag, logger, docker="docker", engine_version=None, *, label_namespace: str) -> str` adds two labels:
    - `--label <ns>.engine.version=<engine_version or tag>`;
    - `--label <ns>.engine.source=https://github.com/<project.release_repository>`.

    The `ENGINE_REPOSITORY` build argument stays, for consumers' own Dockerfiles.

- [ ] **Step 1: Write the failing tests**

In `tests/test_image.py`:
- `test_build_command_line` passes `label_namespace="com.example"`. It also expects `--label com.example.engine.version=v0.14.0` and `--label com.example.engine.source=https://github.com/Braveheart-Chess/braveheart`.
- `test_build_passes_the_engine_version_separately` passes the same, and expects `--label com.example.engine.version=v0.13.0`.
- Add:

```python
def test_the_label_namespace_is_the_zone_reversed() -> None:
    assert image.label_namespace("example.com") == "com.example"
    assert image.label_namespace("platform.example.co.uk") == "uk.co.example.platform"


def test_the_bot_dockerfile_labels_only_the_image() -> None:
    """The engine's labels are the CLI's, under the platform's own namespace."""
    text = resources.files(image.KIND_PACKAGE).joinpath("Dockerfile").read_text()
    instructions = re.sub(r"\\\n", " ", text).splitlines()
    keys = [
        pair.split("=", 1)[0]
        for line in instructions
        if line.startswith("LABEL ")
        for pair in shlex.split(line)[1:]
    ]
    assert keys and all(key.startswith("org.opencontainers.image.") for key in keys)
```

In `tests/test_cli.py`, `test_bot_build_verifies_and_smoke_tests` also asserts `re.search(r"--label [a-z0-9.-]+\.engine\.version=v0\.14\.0 ", fake_docker.read_text().splitlines()[0])`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `uv run pytest tests/test_image.py tests/test_cli.py -q -k "build or label or dockerfile"`
Expected: FAIL with `TypeError: build() got an unexpected keyword argument 'label_namespace'`

- [ ] **Step 3: Move the labels**

- **The Dockerfile's `LABEL`:** it keeps the three `org.opencontainers.image.*` keys and drops the two `engineering.jwall.*` keys. A comment says "The CLI adds the engine's own labels, `<the platform's zone, reversed>.engine.version` and `.engine.source` (jaws.image.build)."
- **`src/jaws/cli.py:1346`:** passes `label_namespace=image.label_namespace(run.settings.dns.zone)`.
- **Pinned bots:** `image.config_digest` doesn't hash the product's Dockerfile, so no pinned bot's tag changes and nothing rebuilds.

- [ ] **Step 4: Run the tests and watch them pass**

Run: `uv run pytest -q && uv run mypy`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jaws/kinds/lichess_bot/Dockerfile src/jaws/image.py src/jaws/cli.py tests/test_image.py tests/test_cli.py
git commit -m "feat(cli): label the bot image's engine under the platform's own zone"
```

---

### Task 8: Open the pull request

- [ ] **Step 1: Commit this plan with the work it describes**

In `docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md`:
- row 02's Status becomes `written`;
- "Only plan 01 is written so far." names every written plan.

```bash
git add docs/superpowers/plans/2026-11-23-hub-split-02-white-label.md docs/superpowers/plans/2026-11-23-hub-split-00-roadmap.md
git commit -m "docs(cli): add plan 02 of the hub split"
```

- [ ] **Step 2: Run the full `AGENTS.md` checklist**

Run the "Before opening a PR" block in `AGENTS.md`.
Expected: every command passes.

- [ ] **Step 3: Push the branch and open the PR**

- Title: `feat(cli): add white-label hooks with jaws's values as the defaults`.
- Body: `.github/pull_request_template.md`, with every section filled in.
  - **Why** links spec 6.7 and this plan, and says that nothing in AWS changes and the owner has nothing to do.
  - **Changes** has one line per task, the check-name decision, and a note that plan 03 edits `foundation/` and `monitoring/` in parallel.
  - **Verification** lists the commands run and the CI plan comments.

```bash
gh pr create --title "feat(cli): add white-label hooks with jaws's values as the defaults" --body-file <file>
```

Expected: CI passes, and every plan comment says **No changes**: Terraform plan, Monitoring plan, Data access plan, and each Bot plan and Databricks plan.
