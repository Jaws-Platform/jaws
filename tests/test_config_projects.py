"""`jaws config projects`: the project list the hub's workflows read, in place of
scripts/projects.sh's yq."""

from __future__ import annotations

import json
import subprocess

import pytest
from typer.testing import CliRunner

from jaws import cli
from tests.conftest import CONFIG_DIR, REPO_ROOT
from tests.test_databricks_workflows import needs_yq

runner = CliRunner()


@needs_yq
@pytest.mark.parametrize("types", [["bot", "research"], ["databricks"], ["site"]])
def test_config_projects_lists_what_scripts_projects_sh_lists(types: list[str]) -> None:
    result = runner.invoke(cli.app, ["--config", str(CONFIG_DIR), "config", "projects", *types])
    assert result.exit_code == 0, result.output
    script = subprocess.run(
        ["scripts/projects.sh", "--config", str(CONFIG_DIR), *types],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    listed = json.loads(result.stdout)
    assert listed, "the fixture has projects of this type"
    assert listed == json.loads(script.stdout)
    assert result.stdout.strip() == json.dumps(listed, separators=(",", ":"))


def test_config_projects_refuses_an_unknown_type() -> None:
    result = runner.invoke(cli.app, ["--config", str(CONFIG_DIR), "config", "projects", "app"])
    assert result.exit_code == 2
    assert "unknown project type: app (site, bot, research or databricks)" in result.output
