"""jaws builds in one account: the primary account of the registry (config/aws.yaml).

The registry's other accounts (management, development) are recorded, never
addressed, and the old `production:`, `management:` and `development:` sections
are refused, pointing at the registry, rather than ignored.
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
from tests.conftest import CONFIG_DIR, repo_config

runner = CliRunner()


def _write(tmp_path: Path, raw: dict[str, Any]) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return path


def test_the_primary_account_is_production() -> None:
    settings = load_settings(CONFIG_DIR, environ={})
    assert settings.aws.primary == "production"
    assert settings.aws.account_id == "570327089884"
    assert settings.context.name_root == "jaws"
    assert (
        settings.context.organization == "Jaws-Platform" and settings.context.managed_by == "JAWS"
    )
    assert settings.state.bucket == "jaws-terraform-state-570327089884"
    assert settings.ecr.repository == "jaws-cli"
    by_type = {a.type: a.account_id for a in settings.aws.accounts.values()}
    assert by_type == {
        "management": "650503560686",
        "production": "570327089884",
        "development": "859674017655",
    }


@pytest.mark.parametrize("section", ["production", "management", "development"])
def test_an_old_account_section_is_refused(tmp_path: Path, section: str) -> None:
    raw = {**repo_config(), section: {"account_id": "650503560686"}}
    with pytest.raises(ConfigError, match=rf"{section}: the accounts are the registry"):
        load_settings(_write(tmp_path, raw), environ={})


@pytest.mark.parametrize("other", ["management", "development"])
def test_the_other_accounts_are_distinct_from_the_primary(tmp_path: Path, other: str) -> None:
    raw = repo_config()
    accounts = raw["aws"]["accounts"]
    accounts[other]["account_id"] = accounts["production"]["account_id"]
    with pytest.raises(ConfigError, match="distinct"):
        load_settings(_write(tmp_path, raw), environ={})


def test_config_env_prints_the_account_the_workflows_build_roles_from(tmp_path: Path) -> None:
    path = _write(tmp_path, repo_config())
    result = runner.invoke(cli.app, ["--config", str(path), "config", "env"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "account_id=570327089884",
        "name_root=jaws",
        "state_bucket=jaws-terraform-state-570327089884",
        "ecr_repository=jaws-cli",
    ]


def test_config_env_reads_the_config_directory() -> None:
    result = runner.invoke(cli.app, ["--config", str(CONFIG_DIR), "config", "env"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "account_id=570327089884"


def test_config_env_follows_the_primary_account(tmp_path: Path) -> None:
    """Pointing `primary` at another account moves every role ARN with it."""
    raw = repo_config()
    raw["aws"]["primary"] = "development"
    result = runner.invoke(cli.app, ["--config", str(_write(tmp_path, raw)), "config", "env"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == "account_id=859674017655"


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
    raw = repo_config()
    raw["databricks"]["enabled"] = enabled
    raw["databricks"]["shared_host_url"] = host
    path = _write(tmp_path, raw)
    result = runner.invoke(cli.app, ["--config", str(path), "config", "env", "--databricks"])
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1] == f"databricks={state}"


def test_there_is_no_account_option() -> None:
    result = runner.invoke(cli.app, ["--account", "production", "config", "env"])
    assert result.exit_code != 0
