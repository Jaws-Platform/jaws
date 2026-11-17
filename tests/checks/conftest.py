from __future__ import annotations

from collections.abc import Iterator

import pytest

from jaws.checks.framework import isolated_registry
from jaws.project import Project
from jaws.settings import Settings
from jaws.site import load_site_config


@pytest.fixture(autouse=True)
def empty_registry() -> Iterator[None]:
    """Each test starts with an empty registry and its registrations are discarded."""
    with isolated_registry():
        yield


@pytest.fixture
def databricks(settings: Settings) -> Project:
    from tests.conftest import FIXTURES

    return Project.from_config(
        load_site_config(FIXTURES / "bots" / "databricks-poc.yaml"), settings
    )


@pytest.fixture
def disabled(settings: Settings) -> Settings:
    """The config with `databricks.enabled: false`, for the checks' skip paths."""
    assert settings.databricks is not None
    section = settings.databricks.model_copy(update={"enabled": False})
    return settings.model_copy(update={"databricks": section})
