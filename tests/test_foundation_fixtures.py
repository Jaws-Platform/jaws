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


#: The management account's shared host and a production one, as the fixtures state them.
MANAGEMENT_HOST = "https://dbc-46322154-036c.cloud.databricks.com"
PRODUCTION_HOST = "https://dbc-0f0f0f0f-aaaa.cloud.databricks.com"


def _databricks_in(
    config: dict[str, Any], account: str, production_host: str | None = None
) -> dict[str, Any]:
    """Databricks enabled in `account` only, stated here and not read from the file:
    it is enabled in one account at a time, and config.yaml flips when it moves."""
    config["databricks"]["enabled"] = account == "management"
    config["databricks"]["shared_host_url"] = MANAGEMENT_HOST
    overrides = config["production"]["overrides"].setdefault("databricks", {})
    overrides["enabled"] = account == "production"
    overrides["shared_host_url"] = production_host
    return config


def _bootstrapped(config: dict[str, Any]) -> dict[str, Any]:
    """What `config.yaml` says once the owner has bootstrapped production, before
    any project moves: the projects are stated here, not read from the file, so
    these fixtures survive each pull request that moves a project. Databricks is
    in the management account, where these fixtures' runs expect it."""
    config = _databricks_in(config, "management")
    production = config["production"]
    production["bootstrapped"] = True
    production["projects"] = {}
    production.pop("management_retired", None)
    production["overrides"]["aws"]["admin_role_arn"] = PRODUCTION_ADMIN
    production["overrides"]["dns"] = {"zone_id": "Z0PRODUCTIONZONE0000"}
    return config


def _with_projects(projects: dict[str, str]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def transform(config: dict[str, Any]) -> dict[str, Any]:
        config = _bootstrapped(config)
        config["production"]["projects"] = projects
        return config

    return transform


def _unbootstrapped(config: dict[str, Any]) -> dict[str, Any]:
    """What `config.yaml` says before the bootstrap: production has no admin
    role and no zone of its own yet. Stated here, not read from the file, so
    the tests that need this state survive the pull request that ends it."""
    config = _databricks_in(config, "management")
    production = config["production"]
    production["bootstrapped"] = False
    production["projects"] = {}
    production.pop("management_retired", None)
    production["overrides"]["aws"].pop("admin_role_arn", None)
    production["overrides"].pop("dns", None)
    return config


def _relabelled(config: dict[str, Any]) -> dict[str, Any]:
    """Production with a ManagedBy of its own that no code spells: the
    foundation must take it from the configuration."""
    config = _bootstrapped(config)
    config["production"]["overrides"]["context"]["managed_by"] = "jaws-relabelled"
    return config


def _databricks_switched(host: str | None) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Databricks rebuilt in production: braveheart-databricks has left management
    and braveheart-selfplay, whose positions it reads, has a stack in both."""

    def transform(config: dict[str, Any]) -> dict[str, Any]:
        config = _with_projects(
            {"braveheart-selfplay": "moving", "braveheart-databricks": "moved"}
        )(config)
        return _databricks_in(config, "production", host)

    return transform


FIXTURES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "unbootstrapped.yaml": _unbootstrapped,
    "production.yaml": _bootstrapped,
    "relabelled.yaml": _relabelled,
    # A research project with a stack in both accounts, and a site that has left.
    "moving.yaml": _with_projects({"braveheart-trainer": "moving", "main-site": "moved"}),
    # A bot whose old stack has been destroyed.
    "moved.yaml": _with_projects({"braveheart-bot": "moved"}),
    "unregistered.yaml": _with_projects({"not-a-project": "moving"}),
    # Databricks after its move: off in management, on in production, whose shared
    # host is not recorded yet (the first release), then recorded (the second).
    "databricks-switched.yaml": _databricks_switched(None),
    "databricks-onboarded.yaml": _databricks_switched(PRODUCTION_HOST),
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
