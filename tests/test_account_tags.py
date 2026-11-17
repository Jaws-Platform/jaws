"""Tags are the account's: the tool stamps `Organization` and `ManagedBy` when it renders.

A project file must be valid in both accounts' views while its project moves,
so it cannot decide the tags that differ between them. `context.organization`
and `context.managed_by` of the view a run uses do (config.yaml, with
`production.overrides` merged in the production view). A file may still state
`Organization`, as any configured organization.

Management renders exactly what it rendered before the stamp moved to the
render (tests/fixtures/renders/management.json, captured from the code before
that change): any difference there is drift on a live stack. Regenerate it
only for an intended change, which the pull request's plans then show:

    PYTHONPATH=. uv run python tests/test_account_tags.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from jaws import site as site_module
from jaws.access import Access
from jaws.errors import ConfigError
from jaws.project import DATABRICKS_RESERVED_TAGS, Project
from jaws.settings import Settings, load_settings
from jaws.site import Site, SiteConfig, load_site_config
from jaws.stack import render_tfvars
from jaws.tasks import TaskSpec, task_tags
from tests.conftest import FIXTURES, SITE_FIXTURES
from tests.stack_plans.render import ACCOUNT_OUTPUTS, _handshakes

GOLDEN = FIXTURES / "renders" / "management.json"
CONFIG = FIXTURES / "config.yaml"
REGISTRY = FIXTURES / "registry"
#: The registered projects of the bot stack (bot and research), by their live files.
BOT_STACK_PROJECTS = ("braveheart", "braveheart-bot", "braveheart-selfplay", "braveheart-trainer")
#: A Databricks project that reads no dataset: one that does is refused in production
#: until dataset bucket names are derived from the account (their own plan).
DATABRICKS_POC = FIXTURES / "bots" / "databricks-poc.yaml"


def _management() -> Settings:
    return load_settings(CONFIG, environ={})


def _production() -> Settings:
    return load_settings(CONFIG, environ={}, account="production")


def _registered(name: str) -> SiteConfig:
    return load_site_config(REGISTRY / f"{name}.yaml")


def _spec(project: Project) -> TaskSpec:
    return TaskSpec(
        project=project,
        instance_type="c8a.16xlarge",
        max_hours=6,
        run_id="123-1",
        task_id="sprt-0",
        workflow="SPRT",
        repository=project.config.repository,
        ref="0123456789abcdef0123456789abcdef01234567",
        script="scripts/sprt.sh",
        args=(),
        pull_request="84",
    )


def _renders(settings: Settings, access: Access) -> dict[str, Any]:
    """Every render the live fixtures go through, by `<render>/<project>`."""
    renders: dict[str, Any] = {}
    for path in SITE_FIXTURES:
        config = load_site_config(path)
        renders[f"site/{config.project}"] = render_tfvars(Site.from_config(config, settings))
        renders[f"site-project/{config.project}"] = render_tfvars(
            Project.from_config(config, settings), settings
        )
    for name in BOT_STACK_PROJECTS:
        project = Project.from_config(_registered(name), settings)
        renders[f"bot/{name}"] = render_tfvars(project, settings, access=access)
        if project.task_runner is not None:
            renders[f"task/{name}"] = task_tags(_spec(project), "spot")
    databricks = Project.from_config(_registered("braveheart-databricks"), settings)
    renders["databricks-account/braveheart-databricks"] = render_tfvars(
        databricks, settings, stack="account", access=access
    )
    renders["databricks-workspace/braveheart-databricks"] = render_tfvars(
        databricks, settings, stack="workspace", account_outputs=ACCOUNT_OUTPUTS
    )
    return renders


def _as_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


# -- management: today's tags, exactly ----------------------------------------------------


def test_management_render_is_unchanged() -> None:
    golden = json.loads(GOLDEN.read_text())
    renders = _as_json(_renders(_management(), _handshakes()))
    assert sorted(renders) == sorted(golden)
    for case, expected in golden.items():
        assert renders[case] == expected, f"{case} renders differently in management: drift"


def test_management_stamps_today_s_values_over_whatever_the_file_states() -> None:
    """braveheart's live file states the legacy `ManagedBy: terraform`."""
    assert _registered("braveheart").tags["ManagedBy"] == "terraform"
    project = Project.from_config(_registered("braveheart"), _management())
    tags = render_tfvars(project, _management())["tags"]
    assert (tags["Organization"], tags["ManagedBy"]) == (
        "jwall-engineering",
        "jwall-engineering-infra",
    )


# -- production: the account's tags, whatever the file states -------------------------------


def _bot_for_production() -> SiteConfig:
    """braveheart-bot's live file, with its token parameter under production's prefix:
    an absolute secret path is valid in one account only until secrets are named
    relative to the project (G2). Its tags are the live file's."""
    raw = yaml.safe_load((REGISTRY / "braveheart-bot.yaml").read_text())
    bot = next(c for c in raw["components"] if c["kind"] == "lichess-bot")
    bot["secrets"] = {"LICHESS_TOKEN": "/jaws/braveheart-bot/lichess-token"}
    return SiteConfig.model_validate(raw)


def _production_tags() -> dict[str, dict[str, str]]:
    """The tags of every render in the production view, by render."""
    production = _production()
    guitar = load_site_config(FIXTURES / "sites" / "guitar-knowledge-base.yaml")
    bot = Project.from_config(_bot_for_production(), production)
    databricks = Project.from_config(load_site_config(DATABRICKS_POC), production)
    workspace = render_tfvars(
        databricks, production, stack="workspace", account_outputs=ACCOUNT_OUTPUTS
    )
    return {
        "site": render_tfvars(Site.from_config(guitar, production))["tags"],
        "site-project": render_tfvars(Project.from_config(guitar, production), production)["tags"],
        "bot": render_tfvars(bot, production)["tags"],
        "task": task_tags(_spec(bot), "spot"),
        "databricks-account": render_tfvars(databricks, production, stack="account")["tags"],
        "databricks-workspace": workspace["tags"],
        "databricks-workspace-fixed": workspace["fixed_tags"],
    }


def test_production_render_stamps_jaws() -> None:
    """Every file here states `Organization: jwall-engineering`, and every render
    in production says `jaws`: the bot stack builds every name from that tag."""
    for path in (REGISTRY / "braveheart-bot.yaml", DATABRICKS_POC):
        assert load_site_config(path).tags["Organization"] == "jwall-engineering"
    for render, tags in _production_tags().items():
        assert (tags["Organization"], tags["ManagedBy"]) == ("jaws", "jaws"), render


def test_databricks_tags_differ_between_the_views_only_in_the_account_s_tags() -> None:
    """The compute policies fix these tags: the stamp adds no key (none Databricks
    reserves) and changes no other value."""
    config = load_site_config(DATABRICKS_POC)
    management = Project.from_config(config, _management()).databricks_tags
    production = Project.from_config(config, _production()).databricks_tags
    assert set(production) == set(management)
    assert not set(production) & set(DATABRICKS_RESERVED_TAGS)
    differing = {key for key in management if management[key] != production[key]}
    assert differing == {"Organization", "ManagedBy"}


# -- one file, both views ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        *SITE_FIXTURES,
        DATABRICKS_POC,
        pytest.param(
            REGISTRY / "braveheart-bot.yaml",
            marks=pytest.mark.xfail(
                strict=True,
                raises=ConfigError,
                reason="its secret is still the absolute management path; the bot "
                "repository names it relative (lichess-token) before the move (runbook M1)",
            ),
        ),
    ],
    ids=lambda p: Path(p).stem,
)
def test_a_file_valid_in_both_views_while_moving(path: Path) -> None:
    config = load_site_config(path)
    for settings in (_management(), _production()):
        project = Project.from_config(config, settings)
        assert project.tags["Organization"] == settings.context.organization


def test_both_views_know_every_configured_organization() -> None:
    assert _management().organizations == ("jwall-engineering", "jaws")
    assert _production().organizations == ("jwall-engineering", "jaws")


def test_without_a_production_section_only_management_s_organization_is_known(
    tmp_path: Path,
) -> None:
    raw = yaml.safe_load(CONFIG.read_text())
    raw.pop("production")
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    assert load_settings(path, environ={}).organizations == ("jwall-engineering",)


def test_the_organizations_are_not_read_from_the_file(tmp_path: Path) -> None:
    raw = yaml.safe_load(CONFIG.read_text())
    raw["organizations"] = ["someone-else"]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    with pytest.raises(ConfigError, match="organizations"):
        load_settings(path, environ={})


@pytest.mark.parametrize(
    "path",
    [FIXTURES / "sites" / "guitar-knowledge-base.yaml", REGISTRY / "braveheart-trainer.yaml"],
    ids=["site", "research"],
)
def test_an_unknown_organization_is_refused(path: Path) -> None:
    raw = yaml.safe_load(path.read_text())
    raw["tags"]["Organization"] = "someone-else"
    config = SiteConfig.model_validate(raw)
    for settings in (_management(), _production()):
        with pytest.raises(
            ConfigError,
            match=r"tags\.Organization must be 'jwall-engineering' or 'jaws', got 'someone-else'",
        ):
            Project.from_config(config, settings)


# -- ManagedBy -------------------------------------------------------------------------------------


def test_managed_by_is_overridable_per_account(tmp_path: Path) -> None:
    """`context` is overridable in both the tool and the foundation
    (test_accounts.py checks the two agree), so `managed_by` is too."""
    assert _management().context.managed_by == "jwall-engineering-infra"
    assert _production().context.managed_by == "jaws"
    raw = yaml.safe_load(CONFIG.read_text())
    raw["production"]["overrides"]["context"]["managed_by"] = "someone-else"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    assert load_settings(path, environ={}, account="production").context.managed_by == (
        "someone-else"
    )
    assert load_settings(path, environ={}).context.managed_by == "jwall-engineering-infra"


def test_every_configured_managed_by_may_be_stated_by_a_file() -> None:
    """A file parses without config.yaml, so it accepts a fixed set of values; the
    stacks' variables accept the same set. Every account's value must be in it."""
    for settings in (_management(), _production()):
        assert settings.context.managed_by in site_module.MANAGED_BY_VALUES


@pytest.mark.parametrize("stated", [None, "terraform", "jwall-engineering-infra", "jaws"])
def test_a_stated_managed_by_never_decides_the_tag(stated: str | None) -> None:
    raw = yaml.safe_load((FIXTURES / "sites" / "guitar-knowledge-base.yaml").read_text())
    if stated is not None:
        raw["tags"]["ManagedBy"] = stated
    config = SiteConfig.model_validate(raw)
    assert config.tags.get("ManagedBy") == stated, "the file's tags are kept as stated"
    for settings in (_management(), _production()):
        site = Site.from_config(config, settings)
        assert render_tfvars(site)["tags"]["ManagedBy"] == settings.context.managed_by


if __name__ == "__main__":
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    renders = _renders(_management(), _handshakes())
    GOLDEN.write_text(json.dumps(renders, indent=2, sort_keys=True) + "\n")
    print(f"wrote {GOLDEN} ({len(renders)} renders)")
