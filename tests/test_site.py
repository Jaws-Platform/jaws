from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from jaws.errors import ConfigError
from jaws.settings import Settings
from jaws.site import (
    REQUIRED_TAGS,
    TOOL_TAGS,
    Site,
    SiteConfig,
    load_site_config,
)
from tests.conftest import FIXTURES

GUITAR = FIXTURES / "sites" / "guitar-knowledge-base.yaml"


def _raw(mutate: dict[str, Any] | None = None, drop: tuple[str, ...] = ()) -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(GUITAR.read_text())
    for dotted, value in (mutate or {}).items():
        target = raw
        *parents, key = dotted.split(".")
        for part in parents:
            target = target.setdefault(part, {})
        target[key] = value
    for dotted in drop:
        target = raw
        *parents, key = dotted.split(".")
        for part in parents:
            target = target[part]
        del target[key]
    return raw


def _write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "jaws.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


# -- the three real sites ---------------------------------------------------------


def test_every_fixture_loads(site: Site) -> None:
    assert site.bucket == f"jaws-{site.project}"
    assert site.state_key == f"project={site.project}/env=prod/{site.project}-prod.tfstate"
    assert site.role_name("plan") == f"jaws-{site.project}-ci-plan"
    assert site.role_name("preview") == f"jaws-{site.project}-ci-preview"
    assert site.role_name("apply") == f"jaws-{site.project}-ci-apply"
    assert site.prod_url == f"https://{site.config.domain}/"
    assert site.preview_url(7) == f"https://pr-7.preview.{site.config.domain}/"
    assert site.preview_prefix(7) == "previews/pr-7/"
    assert site.dev_url is None


def test_every_site_fixture_still_loads_as_a_site(site: Site) -> None:
    assert site.config.kind == "site"
    assert site.config.components == ()
    assert site.config.site is not None


def test_main_site_keeps_extra_tags_and_immutable_paths(settings: Settings) -> None:
    config = load_site_config(FIXTURES / "sites" / "main-site.yaml")
    assert config.tags["CostCenter"] == "personal"
    assert config.site is not None
    assert config.site.immutable_paths == ("_astro/**",)
    assert config.site.output_dir == "dist"


# -- validation rules -----------------------------------------------------------


@pytest.mark.parametrize("tag", REQUIRED_TAGS)
def test_each_required_tag_is_required(tmp_path: Path, tag: str) -> None:
    with pytest.raises(ConfigError, match=f"missing the required keys {tag}"):
        load_site_config(_write(tmp_path, _raw(drop=(f"tags.{tag}",))))


@pytest.mark.parametrize(
    ("tag", "value"),
    [
        ("Project", "other"),
        ("Repository", "example-owner/other"),
        ("Environment", "dev"),
    ],
)
def test_cross_checked_tags(tmp_path: Path, tag: str, value: str) -> None:
    with pytest.raises(ConfigError, match=f"{tag} must be"):
        load_site_config(_write(tmp_path, _raw({f"tags.{tag}": value})))


@pytest.mark.parametrize("stated", ["JAWS", "jaws", "hand"])
def test_a_stated_managed_by_is_refused(tmp_path: Path, stated: str) -> None:
    """The tool sets ManagedBy; a file may not state it, even with the tool's value."""
    with pytest.raises(
        ConfigError,
        match=(
            r"tags\.ManagedBy is set by jaws "
            r"\(context\.managed_by in config/tool\.yaml\); remove it"
        ),
    ):
        load_site_config(_write(tmp_path, _raw({"tags.ManagedBy": stated})))


def test_empty_tag_value(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="empty values for Owner"):
        load_site_config(_write(tmp_path, _raw({"tags.Owner": "  "})))


@pytest.mark.parametrize("stated", ["example-owner", "jaws", "someone-else"])
def test_a_stated_organization_is_refused(tmp_path: Path, stated: str) -> None:
    """The tool sets Organization; a file may not state it, even with the right owner."""
    with pytest.raises(
        ConfigError,
        match=r"tags\.Organization is set by jaws \(the project's GitHub owner in "
        r"config/projects\.yaml\); remove it",
    ):
        load_site_config(_write(tmp_path, _raw({"tags.Organization": stated})))


def test_both_stated_tool_tags_are_named(tmp_path: Path) -> None:
    raw = _raw({"tags.Organization": "jaws", "tags.ManagedBy": "jaws"})
    with pytest.raises(ConfigError, match=r"tags\.Organization.*tags\.ManagedBy"):
        load_site_config(_write(tmp_path, raw))


@pytest.mark.parametrize(
    "fixture",
    [
        FIXTURES / "sites" / "guitar-knowledge-base.yaml",
        FIXTURES / "bots" / "braveheart.yaml",
        FIXTURES / "bots" / "math-prover.yaml",
        FIXTURES / "bots" / "databricks-poc.yaml",
    ],
    ids=["site", "bot", "research", "databricks"],
)
@pytest.mark.parametrize("tag", TOOL_TAGS)
def test_every_kind_refuses_a_tool_tag(tmp_path: Path, fixture: Path, tag: str) -> None:
    raw: dict[str, Any] = yaml.safe_load(fixture.read_text())
    raw["tags"][tag] = "jaws"
    with pytest.raises(ConfigError, match=rf"tags\.{tag} is set by jaws"):
        load_site_config(_write(tmp_path, raw))


def test_the_tool_stamps_organization_and_names_keep_the_root(
    tmp_path: Path, settings: Settings
) -> None:
    """Organization is the GitHub owner the project is registered under; the
    names keep the name root."""
    site = Site.from_config(load_site_config(_write(tmp_path, _raw())), settings)
    assert site.tags["Organization"] == settings.owner(site.project) == "example-owner"
    assert site.bucket == f"jaws-{site.project}" and site.name_root == "jaws"


def test_a_file_without_the_tool_tags_is_stamped(tmp_path: Path, settings: Settings) -> None:
    site = Site.from_config(load_site_config(_write(tmp_path, _raw())), settings)
    assert "Organization" not in site.config.tags and "ManagedBy" not in site.config.tags
    assert {k: site.tags[k] for k in TOOL_TAGS} == {
        "Organization": "example-owner",
        "ManagedBy": "JAWS",
    }


def test_domain_must_be_under_the_zone(tmp_path: Path, settings: Settings) -> None:
    config = load_site_config(_write(tmp_path, _raw({"domain": "guitar.example.org"})))
    with pytest.raises(ConfigError, match="not under the zone"):
        Site.from_config(config, settings)


def test_apex_domain_is_under_the_zone(settings: Settings) -> None:
    config = load_site_config(FIXTURES / "sites" / "main-site.yaml")
    assert Site.from_config(config, settings).config.domain == "example.com"


def test_dev_domain(tmp_path: Path, settings: Settings) -> None:
    config = load_site_config(_write(tmp_path, _raw({"dev": {"domain": "dev.guitar.example.com"}})))
    site = Site.from_config(config, settings)
    assert site.dev_url == "https://dev.guitar.example.com/"


def test_dev_domain_must_differ(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"dev\.domain must differ"):
        load_site_config(_write(tmp_path, _raw({"dev": {"domain": "guitar.example.com"}})))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("version", 2, "version"),
        ("project", "Guitar", "project"),
        ("project", "a" * 31, "project"),
        ("repository", "example-owner", "repository"),
        ("domain", "Guitar.example.com", "domain"),
        ("site.output_dir", "../site", "output_dir"),
        ("site.output_dir", "/site", "output_dir"),
        ("site.immutable_paths", ["/abs/**"], "immutable_paths"),
        ("extra", "nope", "extra"),
    ],
)
def test_field_rules(tmp_path: Path, field: str, value: Any, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_site_config(_write(tmp_path, _raw({field: value})))


def test_errors_name_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path, _raw({"version": 2}))
    with pytest.raises(ConfigError, match=str(path)):
        load_site_config(path)


def test_missing_site_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="site file not found"):
        load_site_config(tmp_path / "missing.yaml")


def test_model_is_frozen(guitar: Site) -> None:
    with pytest.raises(Exception, match="frozen"):
        guitar.config.project = "x"


def test_site_config_defaults() -> None:
    config = SiteConfig.model_validate(_raw(drop=("preview",)))
    assert config.preview.enabled is True
    assert config.site is not None
    assert config.site.immutable_paths == ()


def test_a_research_file_is_neither_a_site_nor_a_bot() -> None:
    config = load_site_config(FIXTURES / "bots" / "math-prover.yaml")
    assert config.kind == "research"
    assert config.domain is None and config.site is None
    assert load_site_config(FIXTURES / "bots" / "braveheart.yaml").kind == "bot"


def test_site_commands_refuse_a_research_project(settings: Settings) -> None:
    config = load_site_config(FIXTURES / "bots" / "math-prover.yaml")
    with pytest.raises(ConfigError, match="not a site"):
        Site.from_config(config, settings)


def _with_platform_tags(settings: Settings, tags: dict[str, str]) -> Settings:
    return settings.model_copy(
        update={"context": settings.context.model_copy(update={"tags": tags})}
    )


def test_the_platform_s_tags_are_stamped_on_a_site(tmp_path: Path, settings: Settings) -> None:
    tagged = _with_platform_tags(settings, {"Department": "web"})
    site = Site.from_config(load_site_config(_write(tmp_path, _raw())), tagged)
    assert site.tags["Department"] == "web"


def test_a_site_file_cannot_state_a_platform_tag(tmp_path: Path, settings: Settings) -> None:
    tagged = _with_platform_tags(settings, {"Department": "web"})
    config = load_site_config(_write(tmp_path, _raw({"tags.Department": "mine"})))
    with pytest.raises(
        ConfigError,
        match=r"tags\.Department is set by jaws \(context\.tags in config/tool\.yaml\); remove it",
    ):
        Site.from_config(config, tagged)
