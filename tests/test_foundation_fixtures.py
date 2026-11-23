"""The configurations the foundation's tests plan against.

`foundation/tests/foundation.tftest.hcl` plans the tool configuration (config/)
as written, and a few states it isn't in: a ManagedBy no code spells, no task
runner, the Databricks host before its URL is recorded, an admin role of
another account, and no monitoring section. Each fixture under
`foundation/tests/fixtures/` is config/ as one file
(`jaws.settings.load_document`) with a few values set; this test keeps them
from drifting.

Regenerate after changing config/:

    uv run python -m tests.test_foundation_fixtures
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

import pytest
import yaml

from tests.conftest import REPO_ROOT, onboarded, repo_config

FIXTURES_DIR = REPO_ROOT / "foundation" / "tests" / "fixtures"


def _relabelled(config: dict[str, Any]) -> dict[str, Any]:
    """Values no code spells: the stacks must take them from the file."""
    config["context"]["managed_by"] = "jaws-relabelled"
    config["context"]["owner"] = "example-owner"
    config["platform"]["repositories"][0]["repository"] = "Example-Org/platform"
    config["dns"]["zone"] = "example.com"
    config["dns"]["txt_records"] = {"_example-challenge": ["example-token"]}
    return config


def _no_task_runners(config: dict[str, Any]) -> dict[str, Any]:
    """No project may start a task instance."""
    for project in onboarded(config).values():
        project.pop("instance_types", None)
        project.pop("task_profiles", None)
    return config


def _awaiting_host(config: dict[str, Any]) -> dict[str, Any]:
    """Databricks before its shared host's URL is recorded (the first apply)."""
    config["databricks"]["shared_host_url"] = None
    return config


def _foreign_admin(config: dict[str, Any]) -> dict[str, Any]:
    """An admin role that is not in the primary account: the plan must stop."""
    primary = config["aws"]["accounts"][config["aws"]["primary"]]
    primary["admin_role_arn"] = primary["admin_role_arn"].replace(
        primary["account_id"], "650503560686"
    )
    return config


def _no_monitoring(config: dict[str, Any]) -> dict[str, Any]:
    """No monitoring section: no billing bucket, job, roles or state prefix."""
    config.pop("monitoring")
    return config


FIXTURES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "relabelled.yaml": _relabelled,
    "no-task-runners.yaml": _no_task_runners,
    "awaiting-host.yaml": _awaiting_host,
    "foreign-admin.yaml": _foreign_admin,
    "no-monitoring.yaml": _no_monitoring,
}


def _expected(name: str) -> dict[str, Any]:
    return FIXTURES[name](copy.deepcopy(repo_config()))


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_a_foundation_fixture_is_the_config_with_its_few_changes(name: str) -> None:
    actual = yaml.safe_load((FIXTURES_DIR / name).read_text())
    assert actual == _expected(name), (
        f"{name} has drifted from config/: uv run python -m tests.test_foundation_fixtures"
    )


def test_every_fixture_file_is_accounted_for() -> None:
    assert {p.name for p in FIXTURES_DIR.glob("*.yaml")} == set(FIXTURES)


if __name__ == "__main__":
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for fixture in sorted(FIXTURES):
        header = "# Generated from config/ by tests/test_foundation_fixtures.py: do not edit.\n"
        (FIXTURES_DIR / fixture).write_text(
            header + yaml.safe_dump(_expected(fixture), sort_keys=False)
        )
        print(f"wrote {FIXTURES_DIR / fixture}")
