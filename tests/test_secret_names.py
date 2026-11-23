"""A bot's secrets are named relative to its project, so one project file serves
both accounts while the bot moves: `lichess-token` is the parameter
`/<organization>/<project>/lichess-token` in whichever account a run addresses.
An absolute path still works, in the one account whose prefix it carries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import boto3
import pytest
import yaml
from moto import mock_aws
from pydantic import ValidationError
from typer.testing import CliRunner

from jaws import cli
from jaws.errors import ConfigError
from jaws.project import Project
from jaws.settings import Settings, load_settings
from jaws.site import SiteConfig, load_site_config
from jaws.stack import render_tfvars
from tests.conftest import CONFIG_DIR, FIXTURES

CONFIG = CONFIG_DIR
BOT = FIXTURES / "registry" / "braveheart-bot.yaml"
PRODUCTION_ADMIN = (
    "arn:aws:sts::222222222222:assumed-role/"
    "AWSReservedSSO_AdministratorAccess_0123456789abcdef/owner"
)
runner = CliRunner()


def _management() -> Settings:
    return load_settings(CONFIG, environ={})


def _production() -> Settings:
    return load_settings(CONFIG, environ={})


def _raw_bot() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(BOT.read_text())
    return raw


def _with_secret(tmp_path: Path, value: str) -> Path:
    raw = _raw_bot()
    for component in raw["components"]:
        if component["kind"] == "lichess-bot":
            component["secrets"] = {"LICHESS_TOKEN": value}
    path = tmp_path / "jaws.yaml"
    path.write_text(yaml.safe_dump(raw))
    return path


def _bot(tmp_path: Path, value: str) -> SiteConfig:
    return load_site_config(_with_secret(tmp_path, value))


def test_a_relative_secret_resolves_in_each_account(tmp_path: Path) -> None:
    config = _bot(tmp_path, "lichess-token")
    management = Project.from_config(config, _management())
    production = Project.from_config(config, _production())
    assert management.secret_parameters == {"LICHESS_TOKEN": "/jaws/braveheart-bot/lichess-token"}
    assert production.secret_parameters == {"LICHESS_TOKEN": "/jaws/braveheart-bot/lichess-token"}


def test_the_stack_is_given_the_account_s_parameter(tmp_path: Path) -> None:
    config = _bot(tmp_path, "lichess-token")
    for settings, expected in (
        (_management(), "/jaws/braveheart-bot/lichess-token"),
        (_production(), "/jaws/braveheart-bot/lichess-token"),
    ):
        tfvars = render_tfvars(Project.from_config(config, settings), settings)
        assert tfvars["secret_parameters"] == {"LICHESS_TOKEN": expected}


@pytest.mark.parametrize("value", ["bot", "bot/x", "../x", "x/y", "", "Lichess-Token", "-x"])
def test_a_reserved_or_malformed_relative_name_is_refused(tmp_path: Path, value: str) -> None:
    with pytest.raises((ValidationError, ConfigError)):
        _bot(tmp_path, value)


def test_bot_secrets_set_writes_the_addressed_account_s_parameter(
    bot_workspace: Path,
) -> None:
    # braveheart-bot's own file.
    raw = yaml.safe_load(_with_secret(bot_workspace.parent, "lichess-token").read_text())
    (bot_workspace / "jaws.yaml").write_text(yaml.safe_dump(raw))
    lichess_config = (bot_workspace / "lichess" / "config.yml").read_text()
    (bot_workspace / raw["components"][1]["config"]).write_text(lichess_config)
    production = ("222222222222", PRODUCTION_ADMIN)
    with mock_aws(), patch("jaws.aws.caller_identity", return_value=production):
        result = runner.invoke(
            cli.app,
            ["bot", "secrets", "set", "LICHESS_TOKEN"],
            input="lip_t0k\n",
        )
        assert result.exit_code == 0, result.output
        names = [
            p["Name"]
            for p in boto3.client("ssm", region_name="us-east-1").describe_parameters()[
                "Parameters"
            ]
        ]
    assert names == [f"/jaws/{raw['project']}/lichess-token"]
