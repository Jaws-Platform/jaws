"""The producer's plan reads its consumers' files to render its bucket readers.

A counterpart file that cannot be read fails the plan before Terraform runs:
rendering readers without it would drop a consumer's access unseen.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from jaws import cli
from tests.conftest import FIXTURES, fixture_config
from tests.test_cli import _as_role, _calls, runner

SELFPLAY_PLAN_ROLE = "arn:aws:sts::570327089884:assumed-role/jaws-braveheart-selfplay-ci-plan/s"
POSITIONS_ROLE = "arn:aws:iam::570327089884:role/jaws-ds-braveheart-selfplay-positions"


@pytest.fixture
def selfplay_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """braveheart-selfplay's file, the registry fixtures, and a directory of counterpart files."""
    root = tmp_path / "selfplay-workspace"
    root.mkdir()
    shutil.copy(FIXTURES / "registry" / "braveheart-selfplay.yaml", root / "jaws.yaml")
    # Management only: these tests are about the handshake, not the move.
    config = fixture_config()
    (root / "config.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    files = tmp_path / "project-files"
    files.mkdir()
    shutil.copy(
        FIXTURES / "registry" / "braveheart-databricks.yaml", files / "braveheart-databricks.yaml"
    )
    monkeypatch.chdir(root)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("JAWS_INFRA_ROOT", str(FIXTURES))  # its datasets/ is the registry fixture
    monkeypatch.setenv("JAWS_PROJECT_FILES_DIR", str(files))
    yield root


def test_plan_renders_the_agreed_reader(selfplay_workspace: Path, fake_terraform: Path) -> None:
    with _as_role(SELFPLAY_PLAN_ROLE):
        result = runner.invoke(cli.app, ["plan"])
    assert result.exit_code == 0, result.output
    rendered = json.loads((fake_terraform.parent / "rendered.tfvars.json").read_text())
    (dataset,) = rendered["datasets"]
    assert POSITIONS_ROLE in dataset["readers"]


def test_plan_fails_when_a_counterpart_cannot_be_fetched(
    selfplay_workspace: Path, fake_terraform: Path, tmp_path: Path
) -> None:
    (tmp_path / "project-files" / "braveheart-databricks.yaml").unlink()
    with _as_role(SELFPLAY_PLAN_ROLE):
        result = runner.invoke(cli.app, ["plan"])
    assert result.exit_code == 2, result.output
    log = (selfplay_workspace / ".jaws" / "jaws.log").read_text()
    assert "braveheart-databricks" in log
    assert not (fake_terraform.parent / "rendered.tfvars.json").exists()
    assert _calls(fake_terraform) == []


def test_plan_logs_the_projects_pending_handshakes(
    selfplay_workspace: Path, fake_terraform: Path, tmp_path: Path
) -> None:
    consumer = tmp_path / "project-files" / "braveheart-databricks.yaml"
    data = yaml.safe_load(consumer.read_text())
    data["components"][0].pop("reads")
    consumer.write_text(yaml.safe_dump(data))
    with _as_role(SELFPLAY_PLAN_ROLE):
        result = runner.invoke(cli.app, ["plan"])
    assert result.exit_code == 0, result.output
    log = (selfplay_workspace / ".jaws" / "jaws.log").read_text()
    assert "braveheart-selfplay/positions" in log
    assert "the consumer does not read the dataset" in log
    rendered = json.loads((fake_terraform.parent / "rendered.tfvars.json").read_text())
    assert POSITIONS_ROLE not in rendered["datasets"][0]["readers"]
