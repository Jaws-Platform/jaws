"""The configurations the foundation's account tests plan against.

`foundation/tests/accounts.tftest.hcl` needs a production account that has
been bootstrapped and projects part-way through the move, which `config.yaml`
does not describe yet. Each fixture under `foundation/tests/fixtures/` is
`config.yaml` with a few values set; this test keeps them from drifting.

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
PRODUCTION_ADMIN = (
    "arn:aws:iam::570327089884:role/aws-reserved/sso.amazonaws.com/"
    "AWSReservedSSO_AdministratorAccess_0123456789abcdef"
)


def _bootstrapped(config: dict[str, Any]) -> dict[str, Any]:
    """What `config.yaml` says once the owner has bootstrapped production."""
    production = config["production"]
    production["bootstrapped"] = True
    production["overrides"]["aws"]["admin_role_arn"] = PRODUCTION_ADMIN
    production["overrides"]["dns"] = {"zone_id": "Z0PRODUCTIONZONE0000"}
    return config


def _with_projects(projects: dict[str, str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def transform(config: dict[str, Any]) -> dict[str, Any]:
        config = _bootstrapped(config)
        config["production"]["projects"] = projects
        return config

    return transform


FIXTURES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "production.yaml": _bootstrapped,
    # A research project with a stack in both accounts, and a site that has left.
    "moving.yaml": _with_projects({"braveheart-trainer": "moving", "main-site": "moved"}),
    "unregistered.yaml": _with_projects({"not-a-project": "moving"}),
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
