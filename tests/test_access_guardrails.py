"""The two halves of a handshake, checked against config.yaml alone.

A producer lists Databricks workspace projects under a dataset's `consumers`;
a consumer lists `<owner>/<name>` ids under its workspace's `reads`. Whether
the other side agrees is the reconcile's question (access.compute_access);
these checks need no other project's file.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from jwall_engineering_sites import guardrails
from jwall_engineering_sites.errors import ConfigError
from jwall_engineering_sites.settings import Settings, load_settings
from jwall_engineering_sites.site import SiteConfig, site_config_from_text
from tests.conftest import FIXTURES


def _file(project: str, change: Callable[[dict[str, Any]], None] | None = None) -> SiteConfig:
    data: dict[str, Any] = yaml.safe_load((FIXTURES / "registry" / f"{project}.yaml").read_text())
    if change is not None:
        change(data)
    return site_config_from_text(yaml.safe_dump(data), project)


def _component(data: dict[str, Any], kind: str) -> dict[str, Any]:
    component: dict[str, Any] = next(c for c in data["components"] if c["kind"] == kind)
    return component


def _consumers(names: list[str]) -> Callable[[dict[str, Any]], None]:
    return lambda data: _component(data, "dataset").update(consumers=names)


def _reads(*ids: str) -> Callable[[dict[str, Any]], None]:
    entries = [{"dataset": i, "purpose": "analysis"} for i in ids]
    return lambda data: _component(data, "databricks-workspace").update(reads=entries)


def test_both_live_files_pass(settings: Settings) -> None:
    assert guardrails.check(_file("braveheart-selfplay"), settings) == []
    assert guardrails.check(_file("braveheart-databricks"), settings) == []


@pytest.mark.parametrize("consumer", ["braveheart-trainer", "nobody"])
def test_a_consumer_must_be_a_databricks_workspace_project(
    consumer: str, settings: Settings
) -> None:
    problems = guardrails.check(_file("braveheart-selfplay", _consumers([consumer])), settings)
    assert any(consumer in p and "is not a Databricks workspace project" in p for p in problems), (
        problems
    )


def test_a_project_cannot_consume_its_own_dataset(settings: Settings) -> None:
    problems = guardrails.check(
        _file("braveheart-selfplay", _consumers(["braveheart-selfplay"])), settings
    )
    assert any("cannot consume its own dataset" in p for p in problems), problems


def test_a_workspace_cannot_read_its_own_dataset(settings: Settings) -> None:
    problems = guardrails.check(
        _file("braveheart-databricks", _reads("braveheart-databricks/x")), settings
    )
    assert any("reads its own dataset" in p for p in problems), problems


@pytest.mark.parametrize(
    ("dataset", "owner", "bucket"),
    [
        (
            "braveheart-selfplay/nets",
            "braveheart-selfplay",
            "jwall-engineering-braveheart-selfplay-nets",
        ),
        ("nobody/x", "nobody", "jwall-engineering-nobody-x"),
    ],
)
def test_a_read_must_name_an_approved_dataset(
    dataset: str, owner: str, bucket: str, settings: Settings
) -> None:
    problems = guardrails.check(_file("braveheart-databricks", _reads(dataset)), settings)
    assert any(
        f"no project {owner} approves bucket {bucket} in config.yaml" in p for p in problems
    ), problems


def test_a_read_must_not_repeat(settings: Settings) -> None:
    problems = guardrails.check(
        _file(
            "braveheart-databricks",
            _reads("braveheart-selfplay/positions", "braveheart-selfplay/positions"),
        ),
        settings,
    )
    assert any("repeats braveheart-selfplay/positions" in p for p in problems), problems


@pytest.mark.parametrize(
    "entry",
    [
        {"dataset": "braveheart-selfplay", "purpose": "analysis"},  # no owner
        {"dataset": "Braveheart-Selfplay/positions", "purpose": "analysis"},
        {"dataset": "braveheart-selfplay/positions", "purpose": "   "},
        {"dataset": "braveheart-selfplay/positions", "purpose": "x" * 201},
        {"dataset": "braveheart-selfplay/positions"},  # no purpose
    ],
)
def test_a_read_needs_an_id_and_a_purpose(entry: dict[str, str]) -> None:
    with pytest.raises(ConfigError, match="reads"):
        _file(
            "braveheart-databricks",
            lambda d: _component(d, "databricks-workspace").update(reads=[entry]),
        )


def _settings_with(tmp_path: Path, change: Callable[[dict[str, Any]], None]) -> Settings:
    raw: dict[str, Any] = yaml.safe_load((FIXTURES / "config.yaml").read_text())
    change(raw)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw))
    return load_settings(path, environ={})


def test_a_leftover_databricks_share_is_refused(tmp_path: Path) -> None:
    def share(raw: dict[str, Any]) -> None:
        approval = raw["projects"]["braveheart-selfplay"]["datasets"][
            "jwall-engineering-braveheart-selfplay-positions"
        ]
        approval["databricks_share"] = {"prefix": "data/", "consumers": ["braveheart-databricks"]}

    with pytest.raises(ConfigError, match="databricks_share"):
        _settings_with(tmp_path, share)


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://dbc-01234567-89ab.cloud.databricks.com", True),
        ("http://dbc-01234567-89ab.cloud.databricks.com", False),
        ("https://dbc-01234567-89ab.cloud.databricks.com/", False),
        ("https://example.com", False),
    ],
)
def test_the_shared_host_url_is_a_databricks_https_url(tmp_path: Path, url: str, ok: bool) -> None:
    def host(raw: dict[str, Any]) -> None:
        raw["databricks"]["shared_host_url"] = url

    if ok:
        assert _settings_with(tmp_path, host).databricks.shared_host_url == url  # type: ignore[union-attr]
    else:
        with pytest.raises(ConfigError, match="shared_host_url"):
            _settings_with(tmp_path, host)
