"""The composite action pulls the CLI image of config.yaml's account.

ECR login reaches only the role's own registry, so a step checks that the role
is in config.yaml's account and takes the image repository (`ecr.repository`)
from config.yaml at the action's own commit. That step's script is run here,
with a stand-in `aws` and the real `yq`.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import yaml

from tests.conftest import REPO_ROOT

ACTION_DIR = REPO_ROOT / ".github" / "actions" / "jaws"
CONFIG = REPO_ROOT / "config.yaml"
ACCOUNT = "570327089884"


def _steps() -> list[dict[str, Any]]:
    action: dict[str, Any] = yaml.safe_load((ACTION_DIR / "action.yml").read_text())
    steps: list[dict[str, Any]] = action["runs"]["steps"]
    return steps


def _step(step_id: str) -> dict[str, Any]:
    matches = [s for s in _steps() if s.get("id") == step_id]
    assert len(matches) == 1, f"the action has no single step with id {step_id}"
    return matches[0]


def _resolve(
    tmp_path: Path, account: str, config: Path
) -> tuple[subprocess.CompletedProcess[str], str]:
    """Run the resolve step's script as the role of `account`; its output and GITHUB_OUTPUT."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    aws = bin_dir / "aws"
    aws.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$*" == "sts get-caller-identity --query Account --output text" ]] || '
        '{ echo "unexpected: aws $*" >&2; exit 2; }\n'
        f"echo {account}\n"
    )
    aws.chmod(aws.stat().st_mode | stat.S_IEXEC)
    output = tmp_path / "github_output"
    output.write_text("")
    result = subprocess.run(
        ["bash", "-e", "-c", _step("image")["run"]],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "CONFIG": str(config),
            "GITHUB_OUTPUT": str(output),
        },
        check=False,
    )
    return result, output.read_text()


def _config_without(tmp_path: Path, *path: str) -> Path:
    raw: dict[str, Any] = yaml.safe_load(CONFIG.read_text())
    node = raw
    for key in path[:-1]:
        node = node[key]
    del node[path[-1]]
    written = tmp_path / "config.yaml"
    written.write_text(yaml.safe_dump(raw))
    return written


def test_the_step_reads_the_config_at_the_actions_own_commit() -> None:
    env = _step("image")["env"]
    assert env["CONFIG"] == "${{ github.action_path }}/../../../config.yaml"
    assert (ACTION_DIR / ".." / ".." / ".." / "config.yaml").resolve() == CONFIG.resolve()


def test_the_image_comes_from_the_resolved_repository() -> None:
    run = next(s for s in _steps() if s.get("id") == "run")
    assert run["env"]["REPOSITORY"] == "${{ steps.image.outputs.repository }}"
    assert 'image="$REGISTRY/$REPOSITORY:$IMAGE_TAG"' in run["run"]
    assert "jaws-cli" not in (ACTION_DIR / "action.yml").read_text()


def test_the_account_pulls_its_repository(tmp_path: Path) -> None:
    result, output = _resolve(tmp_path, ACCOUNT, CONFIG)
    assert result.returncode == 0, result.stdout + result.stderr
    assert output.splitlines() == ["repository=jaws-cli"]


def test_an_account_config_yaml_does_not_name_stops_the_job(tmp_path: Path) -> None:
    result, output = _resolve(tmp_path, "111122223333", CONFIG)
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert "111122223333" in result.stdout
    assert output == ""


def test_a_config_without_an_image_repository_stops_the_job(tmp_path: Path) -> None:
    config = _config_without(tmp_path, "ecr", "repository")
    result, output = _resolve(tmp_path, ACCOUNT, config)
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert output == ""
