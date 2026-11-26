"""A hub plans and applies each platform stack against the state `jaws`'s own workflows use
today, so no state moves (spec 6.10). Each failure names the file, never a value.
tests/platform/test_foundation_backend.py checks the foundation's backend file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from jaws import cli
from jaws.platform import platform_backend, platform_stack
from jaws.settings import load_settings
from tests.conftest import PLATFORM_CONFIG_DIR, REPO_ROOT
from tests.workflow_steps import hcl_text_values, hcl_values


def _config_env_state_bucket() -> str | None:
    """The bucket data-access.yml passes as `-backend-config=bucket=`: the `state_bucket`
    line of `jaws config env --databricks`, read as the workflow reads it."""
    result = CliRunner().invoke(
        cli.app, ["--config", str(PLATFORM_CONFIG_DIR), "config", "env", "--databricks"]
    )
    found = [
        line.removeprefix("state_bucket=")
        for line in result.output.splitlines()
        if line.startswith("state_bucket=")
    ]
    return found[0] if result.exit_code == 0 and len(found) == 1 else None


@pytest.mark.parametrize("name", ["monitoring", "data-access"])
def test_the_hub_s_backends_are_the_stacks_own(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    hub = hcl_text_values(platform_backend(settings, platform_stack(name)))
    file = f"{name}/backend/prod.hcl"
    today = hcl_values(REPO_ROOT / file)
    if hub != today:
        pytest.fail(f"the hub's {name} backend differs from {file}", pytrace=False)
    if name == "data-access":
        monkeypatch.chdir(tmp_path)  # the CLI writes its .jaws/ into the working directory
        bucket = _config_env_state_bucket()
        if bucket is None:
            pytest.fail("jaws config env printed no single state_bucket line", pytrace=False)
        if hub != {**today, "bucket": bucket}:
            pytest.fail(
                f"the hub's data-access backend differs from {file} with the bucket "
                "data-access.yml passes",
                pytrace=False,
            )
