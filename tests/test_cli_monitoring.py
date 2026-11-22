"""`jaws monitoring secrets`: the owner's secrets of the monitoring stack, under
/jaws/monitoring/ in SSM. Values are prompted without echo and never printed."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws
from typer.testing import CliRunner

from jaws import cli
from tests.conftest import read_config, repo_config, write_config

runner = CliRunner()
OWNER = "arn:aws:sts::570327089884:assumed-role/AWSReservedSSO_AdministratorAccess_0f/owner"
SENTINEL = "hooks.slack.com/services/T000/B000/SENTINEL-s3cr3t"
#: Every secret config/monitoring.yaml implies: the Grafana admin, and one
#: webhook per Slack channel, at the parameter the channel names.
SECRETS = {
    "grafana-admin-user": "/jaws/monitoring/grafana-admin-user",
    "grafana-admin-password": "/jaws/monitoring/grafana-admin-password",
    "slack/platform": "/jaws/monitoring/slack/platform",
    "slack/costs": "/jaws/monitoring/slack/costs",
}


def _as(arn: str, account: str = "570327089884") -> AbstractContextManager[Any]:
    return patch("jaws.aws.caller_identity", return_value=(account, arn))


@pytest.fixture
def platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """The owner's shell in a checkout: the tool configuration, no project file."""
    root = tmp_path / "jaws"
    write_config(root, repo_config(), sort_keys=False)
    monkeypatch.chdir(root)
    yield root


def _ssm() -> Any:
    return boto3.client("ssm", region_name="us-east-1")


def _stored(name: str) -> dict[str, Any]:
    parameter: dict[str, Any] = _ssm().get_parameter(Name=name, WithDecryption=True)["Parameter"]
    return parameter


@pytest.mark.parametrize(("name", "parameter"), SECRETS.items(), ids=list(SECRETS))
def test_set_writes_a_secure_string_without_echo(platform: Path, name: str, parameter: str) -> None:
    with mock_aws(), _as(OWNER):
        result = runner.invoke(
            cli.app, ["monitoring", "secrets", "set", name], input=f"{SENTINEL}\n"
        )
        assert result.exit_code == 0, result.output
        stored = _stored(parameter)
        assert (stored["Type"], stored["Value"]) == ("SecureString", SENTINEL)
        again = runner.invoke(cli.app, ["monitoring", "secrets", "set", name], input="rotated\n")
        assert again.exit_code == 0, again.output
        assert _stored(parameter)["Value"] == "rotated"
    assert SENTINEL not in result.output
    assert SENTINEL not in (platform / ".jaws" / "jaws.log").read_text()
    assert parameter in result.output


def test_set_refuses_an_empty_value(platform: Path) -> None:
    with mock_aws(), _as(OWNER):
        result = runner.invoke(
            cli.app, ["monitoring", "secrets", "set", "grafana-admin-password"], input="  \n"
        )
        assert result.exit_code == 3, result.output
        assert _ssm().describe_parameters()["Parameters"] == []


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("grafana-admin", "use one of grafana-admin-user, grafana-admin-password, "
                          "slack/platform, slack/costs"),
        ("slack/billing", r"billing is not a channel in monitoring\.slack\.channels "
                          r"\(platform, costs\)"),
        ("slack", "use one of"),
        ("/jaws/monitoring/grafana-admin-user", "use one of"),
    ],
    ids=["unknown-name", "unknown-channel", "bare-slack", "a-parameter-path"],
)  # fmt: skip
def test_set_refuses_a_name_the_config_does_not_imply(
    platform: Path, name: str, message: str
) -> None:
    with mock_aws(), _as(OWNER):
        result = runner.invoke(cli.app, ["monitoring", "secrets", "set", name], input="x\n")
        assert result.exit_code == 2, result.output
        assert _ssm().describe_parameters()["Parameters"] == []
    assert re.search(message, result.output), result.output


def test_set_refuses_another_accounts_credentials(platform: Path) -> None:
    with mock_aws(), _as("arn:aws:sts::650503560686:assumed-role/admin/s", "650503560686"):
        result = runner.invoke(
            cli.app, ["monitoring", "secrets", "set", "grafana-admin-user"], input="x\n"
        )
        assert result.exit_code == 3, result.output
        assert _ssm().describe_parameters()["Parameters"] == []
    assert "570327089884" in result.output


def test_check_lists_the_missing_secrets(platform: Path) -> None:
    with mock_aws(), _as(OWNER):
        none = runner.invoke(cli.app, ["monitoring", "secrets", "check"])
        for name in ("grafana-admin-user", "slack/costs"):
            _ssm().put_parameter(Name=SECRETS[name], Value=SENTINEL, Type="SecureString")
        some = runner.invoke(cli.app, ["monitoring", "secrets", "check"])
        for name in ("grafana-admin-password", "slack/platform"):
            _ssm().put_parameter(Name=SECRETS[name], Value=SENTINEL, Type="SecureString")
        every = runner.invoke(cli.app, ["monitoring", "secrets", "check"])
    assert none.exit_code == 3, none.output
    assert "4 of 4 monitoring secrets are not set" in none.output
    for name, parameter in SECRETS.items():
        assert f"missing {name} ({parameter})" in none.output
    assert some.exit_code == 3, some.output
    assert "2 of 4 monitoring secrets are not set: grafana-admin-password, slack/platform" in (
        some.output
    )
    assert "missing grafana-admin-user" not in some.output
    assert every.exit_code == 0, every.output
    assert "all 4 monitoring secrets are set" in every.output
    for result in (none, some, every):
        assert SENTINEL not in result.output
    assert SENTINEL not in (platform / ".jaws" / "jaws.log").read_text()


def test_without_slack_only_the_grafana_admin_is_needed(platform: Path) -> None:
    config = read_config(platform)
    del config["monitoring"]["slack"]
    write_config(platform, config, sort_keys=False)
    with mock_aws(), _as(OWNER):
        refused = runner.invoke(
            cli.app, ["monitoring", "secrets", "set", "slack/platform"], input="x\n"
        )
        check = runner.invoke(cli.app, ["monitoring", "secrets", "check"])
    assert refused.exit_code == 2, refused.output
    assert "no monitoring.slack" in refused.output
    assert check.exit_code == 3 and "2 of 2 monitoring secrets are not set" in check.output


@pytest.mark.parametrize("command", [["set", "grafana-admin-user"], ["check"]], ids=" ".join)
def test_without_monitoring_there_are_no_secrets(platform: Path, command: list[str]) -> None:
    config = read_config(platform)
    del config["monitoring"]
    write_config(platform, config, sort_keys=False)
    with mock_aws(), _as(OWNER):
        result = runner.invoke(cli.app, ["monitoring", "secrets", *command], input="x\n")
    assert result.exit_code == 2, result.output
    assert "config/monitoring.yaml" in result.output
