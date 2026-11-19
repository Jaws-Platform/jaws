"""Databricks lives in one AWS account at a time, and everything follows it there.

Both AWS accounts use the one Databricks account, which holds one metastore per
region, so the platform layer cannot be enabled in both: it switches. The share
role of an onboarded dataset is a reader only where Databricks is enabled and
its shared host's URL is recorded (the datasets are created in the release
after the host). The credentials script and `config env --databricks` name the
account where it is enabled, and that account's own secret parameter.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from jaws import cli
from jaws.errors import ConfigError
from jaws.project import Project
from jaws.settings import Settings, load_settings
from jaws.site import load_site_config
from jaws.stack import render_tfvars
from tests.conftest import FIXTURES, REPO_ROOT, fixture_config, management_only

runner = CliRunner()
SCRIPT = REPO_ROOT / "scripts" / "databricks-credentials.sh"
PRODUCTION_HOST = "https://dbc-0f0f0f0f-aaaa.cloud.databricks.com"
PRODUCTION = "570327089884"


def _config(tmp_path: Path, management: bool, production: bool, host: Any = None) -> Path:
    """config.yaml's fixture with Databricks enabled as told in each account, and
    production's shared host URL (None: not created yet)."""
    config = fixture_config()
    databricks = config["databricks"]
    overrides = config["production"]["overrides"]["databricks"]  # type: ignore[index]
    assert isinstance(databricks, dict)
    databricks["enabled"] = management
    overrides["enabled"] = production
    overrides["shared_host_url"] = host
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    return path


# -- one account at a time ----------------------------------------------------------


def test_databricks_cannot_be_enabled_in_both_accounts(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"databricks\.enabled is true in both accounts"):
        load_settings(_config(tmp_path, management=True, production=True), environ={})


@pytest.mark.parametrize(
    ("management", "production", "expected"),
    [(True, False, "management"), (False, True, "production"), (False, False, None)],
)
def test_both_views_know_where_databricks_is_enabled(
    tmp_path: Path, management: bool, production: bool, expected: str | None
) -> None:
    path = _config(tmp_path, management, production)
    for account in ("management", "production"):
        assert load_settings(path, environ={}, account=account).databricks_account == expected


def test_the_file_cannot_say_where_databricks_is_enabled(tmp_path: Path) -> None:
    config = fixture_config()
    config["databricks_account"] = "production"
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    with pytest.raises(ConfigError, match="databricks_account"):
        load_settings(path, environ={})


def test_production_never_inherits_managements_host_url(tmp_path: Path) -> None:
    """The live config: production's override is null until its own host exists."""
    production = load_settings(FIXTURES / "config.yaml", environ={}, account="production")
    assert production.databricks is not None
    assert production.databricks.shared_host_url is None

    config = fixture_config()
    del config["production"]["overrides"]["databricks"]["shared_host_url"]  # type: ignore[index]
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False))
    with pytest.raises(ConfigError, match="inherits the management account's shared_host_url"):
        load_settings(path, environ={})


# -- the share role as a reader ------------------------------------------------------


def _handshake() -> Any:
    from jaws.access import compute_access, load_registry

    return compute_access(
        load_registry(FIXTURES / "datasets"),
        {
            name: load_site_config(FIXTURES / "registry" / f"{name}.yaml")
            for name in ("braveheart-selfplay", "braveheart-databricks")
        },
    )


def _readers(settings: Settings) -> list[str]:
    settings = management_only(settings, "braveheart-trainer")
    selfplay = load_site_config(FIXTURES / "registry" / "braveheart-selfplay.yaml")
    project = Project.from_config(selfplay, settings)
    (dataset,) = render_tfvars(project, settings, access=_handshake())["datasets"]
    readers: list[str] = dataset["readers"]
    return readers


def test_the_share_role_reads_only_once_the_host_url_is_recorded(tmp_path: Path) -> None:
    share = f"arn:aws:iam::{PRODUCTION}:role/jaws-ds-braveheart-selfplay-positions"
    waiting = load_settings(_config(tmp_path, False, True), environ={}, account="production")
    assert _readers(waiting) == []
    recorded = load_settings(
        _config(tmp_path, False, True, PRODUCTION_HOST), environ={}, account="production"
    )
    assert _readers(recorded) == [share]


def test_no_share_role_is_named_in_the_account_databricks_left(tmp_path: Path) -> None:
    left = load_settings(
        _config(tmp_path, False, True, PRODUCTION_HOST), environ={}, account="management"
    )
    assert all("-ds-" not in reader for reader in _readers(left))


# -- config env --databricks --------------------------------------------------------


def _config_env(path: Path) -> dict[str, str]:
    result = runner.invoke(cli.app, ["--config", str(path), "config", "env", "--databricks"])
    assert result.exit_code == 0, result.output
    return dict(line.split("=", 1) for line in result.output.splitlines() if "=" in line)


def test_config_env_names_the_account_databricks_is_enabled_in(tmp_path: Path) -> None:
    management = _config_env(_config(tmp_path, True, False))
    assert (management["account"], management["organization"]) == (
        "management",
        "jwall-engineering",
    )
    assert management["databricks"] == "ready"  # management's host URL is recorded

    waiting = _config_env(_config(tmp_path, False, True))
    assert (waiting["account"], waiting["account_id"], waiting["organization"]) == (
        "production",
        PRODUCTION,
        "jaws",
    )
    assert waiting["state_bucket"] == "jaws-terraform-state-570327089884"
    assert waiting["databricks"] == "awaiting-host"

    assert _config_env(_config(tmp_path, False, True, PRODUCTION_HOST))["databricks"] == "ready"


def test_config_env_says_so_when_databricks_is_enabled_nowhere(tmp_path: Path) -> None:
    assert _config_env(_config(tmp_path, False, False))["databricks"] == "disabled"


# -- scripts/databricks-credentials.sh -------------------------------------------------

FAKE_AWS = """#!/usr/bin/env bash
# aws ssm get-parameter --with-decryption --name NAME ...: the name is the secret.
while [ $# -gt 0 ]; do
  if [ "$1" = --name ]; then echo "secret-of:$2"; exit 0; fi
  shift
done
exit 1
"""


def _sourced(tmp_path: Path, config: Path, account: str) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS)
    fake.chmod(0o755)
    command = (
        f'source "{SCRIPT}" "{config}" {account} >/dev/null && echo "$DATABRICKS_CLIENT_SECRET"'
    )
    result = subprocess.run(
        ["bash", "-c", command],
        capture_output=True,
        text=True,
        env=os.environ | {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_the_credentials_script_reads_each_accounts_own_parameter(tmp_path: Path) -> None:
    management = _config(tmp_path, True, False)
    assert _sourced(tmp_path, management, "management") == (
        "secret-of:/jwall-engineering/databricks/client-secret"
    )
    assert _sourced(tmp_path, management, "production") == ""  # not enabled there

    production = _config(tmp_path, False, True)
    assert _sourced(tmp_path, production, "production") == (
        "secret-of:/jaws/databricks/client-secret"
    )
    assert _sourced(tmp_path, production, "management") == ""


# -- the Data access reconcile -------------------------------------------------------


def test_access_render_refuses_the_account_databricks_is_not_in(tmp_path: Path) -> None:
    path = _config(tmp_path, False, True, PRODUCTION_HOST)
    arguments = ["--config", str(path), "--account", "management", "access", "render"]
    result = runner.invoke(cli.app, [*arguments, "--out", str(tmp_path / "out")])
    assert result.exit_code != 0
    assert "Databricks is enabled in the production account" in result.output


@pytest.mark.parametrize("job", ["plan", "apply"])
def test_data_access_runs_where_databricks_is_enabled(job: str) -> None:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "data-access.yml").read_text())
    steps = workflow["jobs"][job]["steps"]
    role = next(s for s in steps if s.get("id") == "role")
    assert "config env --databricks" in role["run"]
    for output in ("account=", "state_bucket=", "databricks="):
        assert f'echo "{output}' in role["run"], output
    after = steps[steps.index(role) + 1 :]
    # Nothing to reconcile while Databricks is disabled or its host is not recorded.
    for step in after:
        assert "steps.role.outputs.databricks == 'ready'" in step.get("if", ""), step.get("name")
    render = next(s for s in after if "access render" in s.get("run", ""))
    assert 'jaws --account "$ACCOUNT" access render' in render["run"]
    assert render["env"]["ACCOUNT"] == "${{ steps.role.outputs.account }}"
    init = next(s for s in after if "terraform-init" in s.get("uses", ""))
    assert "-backend-config=bucket=${{ steps.role.outputs.state_bucket }}" in init["with"]["args"]
    terraform = next(s for s in after if "databricks-credentials.sh" in s.get("run", ""))
    assert 'databricks-credentials.sh ../config.yaml "$ACCOUNT"' in terraform["run"]
    assert terraform["env"]["ACCOUNT"] == "${{ steps.role.outputs.account }}"


# -- the secret is never printed outside GitHub Actions ---------------------------------


def _source_output(tmp_path: Path, actions: bool) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "aws"
    fake.write_text(FAKE_AWS)
    fake.chmod(0o755)
    env = os.environ | {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env.pop("GITHUB_ACTIONS", None)
    if actions:
        env["GITHUB_ACTIONS"] = "true"
    config = _config(tmp_path, True, False)
    result = subprocess.run(
        ["bash", "-c", f'source "{SCRIPT}" "{config}" management'],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout + result.stderr


def test_the_credentials_script_never_prints_the_secret_outside_actions(tmp_path: Path) -> None:
    """`::add-mask::` is a GitHub Actions command: anywhere else it prints the value."""
    secret = "secret-of:/jwall-engineering/databricks/client-secret"
    assert secret not in _source_output(tmp_path, actions=False)
    assert f"::add-mask::{secret}" in _source_output(tmp_path, actions=True)
