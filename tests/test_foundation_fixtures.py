"""The configurations the foundation's tests plan against.

`foundation/tests/foundation.tftest.hcl` plans config.yaml as written, and a few
states it isn't in: a ManagedBy no code spells, no task runner, the Databricks
host before its URL is recorded, and an admin role of another account. Each
fixture under `foundation/tests/fixtures/` is `config.yaml` with a few values
set; this test keeps them from drifting.

Regenerate after changing `config.yaml`:

    uv run python tests/test_foundation_fixtures.py
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT

FIXTURES_DIR = REPO_ROOT / "foundation" / "tests" / "fixtures"


def _relabelled(config: dict[str, Any]) -> dict[str, Any]:
    """A ManagedBy no code spells: the foundation must take it from the file."""
    config["context"]["managed_by"] = "jaws-relabelled"
    return config


def _no_task_runners(config: dict[str, Any]) -> dict[str, Any]:
    """No project may start a task instance."""
    for project in config["projects"].values():
        if isinstance(project, dict):
            project.pop("instance_types", None)
            project.pop("task_profiles", None)
    return config


def _awaiting_host(config: dict[str, Any]) -> dict[str, Any]:
    """Databricks before its shared host's URL is recorded (the first apply)."""
    config["databricks"]["shared_host_url"] = None
    return config


def _foreign_admin(config: dict[str, Any]) -> dict[str, Any]:
    """An admin role that is not in the account: the plan must stop."""
    config["aws"]["admin_role_arn"] = config["aws"]["admin_role_arn"].replace(
        config["aws"]["account_id"], "650503560686"
    )
    return config


FIXTURES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "relabelled.yaml": _relabelled,
    "no-task-runners.yaml": _no_task_runners,
    "awaiting-host.yaml": _awaiting_host,
    "foreign-admin.yaml": _foreign_admin,
}


def _expected(name: str) -> dict[str, Any]:
    config = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    return FIXTURES[name](copy.deepcopy(config))


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_a_foundation_fixture_is_config_yaml_with_its_few_changes(name: str) -> None:
    actual = yaml.safe_load((FIXTURES_DIR / name).read_text())
    assert actual == _expected(name), (
        f"{name} has drifted from config.yaml: uv run python tests/test_foundation_fixtures.py"
    )


def test_every_fixture_file_is_accounted_for() -> None:
    assert {p.name for p in FIXTURES_DIR.glob("*.yaml")} == set(FIXTURES)


if __name__ == "__main__":
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for fixture in sorted(FIXTURES):
        header = "# Generated from config.yaml by tests/test_foundation_fixtures.py: do not edit.\n"
        (FIXTURES_DIR / fixture).write_text(
            header + yaml.safe_dump(_expected(fixture), sort_keys=False)
        )
        print(f"wrote {FIXTURES_DIR / fixture}")
