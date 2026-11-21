"""jaws builds in one account, the one config.yaml describes.

The management and development accounts are recorded, never addressed, and a
`production:` section left over from the move is refused rather than ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from jaws import cli
from jaws.errors import ConfigError
from jaws.settings import load_settings
from tests.conftest import REPO_ROOT

runner = CliRunner()


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load((REPO_ROOT / "config.yaml").read_text())
    return raw


def _write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path


def test_config_yaml_describes_the_production_account() -> None:
    settings = load_settings(REPO_ROOT / "config.yaml", environ={})
    assert settings.aws.account_id == "570327089884"
    assert settings.context.organization == "jaws" and settings.context.managed_by == "jaws"
    assert settings.state.bucket == "jaws-terraform-state-570327089884"
    assert settings.ecr.repository == "jaws-cli"
    assert settings.management is not None and settings.management.account_id == "650503560686"
    assert settings.development is not None and settings.development.account_id == "859674017655"


def test_a_production_section_is_refused(tmp_path: Path) -> None:
    raw = {**_raw(), "production": {"projects": {}}}
    with pytest.raises(ConfigError, match="production: jaws has one account"):
        load_settings(_write(tmp_path, raw), environ={})


@pytest.mark.parametrize("section", ["management", "development"])
def test_the_other_accounts_are_distinct_from_production(tmp_path: Path, section: str) -> None:
    raw = _raw()
    raw[section]["account_id"] = raw["aws"]["account_id"]
    with pytest.raises(ConfigError, match="distinct"):
        load_settings(_write(tmp_path, raw), environ={})


def test_config_env_prints_the_account_the_workflows_build_roles_from(tmp_path: Path) -> None:
    path = _write(tmp_path, _raw())
    result = runner.invoke(cli.app, ["--config", str(path), "config", "env"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "account_id=570327089884",
        "organization=jaws",
        "state_bucket=jaws-terraform-state-570327089884",
        "ecr_repository=jaws-cli",
    ]


@pytest.mark.parametrize(
    ("enabled", "host", "state"),
    [
        (True, "https://dbc-1.cloud.databricks.com", "ready"),
        (True, None, "awaiting-host"),
        (False, None, "disabled"),
    ],
)
def test_config_env_says_whether_databricks_is_ready(
    tmp_path: Path, enabled: bool, host: str | None, state: str
) -> None:
    raw = _raw()
    raw["databricks"]["enabled"] = enabled
    raw["databricks"]["shared_host_url"] = host
    path = _write(tmp_path, raw)
    result = runner.invoke(cli.app, ["--config", str(path), "config", "env", "--databricks"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1] == f"databricks={state}"


def test_there_is_no_account_option() -> None:
    result = runner.invoke(cli.app, ["--account", "production", "config", "env"])
    assert result.exit_code != 0
