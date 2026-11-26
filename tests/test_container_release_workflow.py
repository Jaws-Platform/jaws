"""The reusable container-release workflow: the hub's identity, role and configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tests.conftest import REPO_ROOT
from tests.workflow_steps import run_step

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "container-release.yml"
FIXTURE = "account_id=222222222222\nname_root=jaws\n"
IDENTITY_IF = "inputs.platform-image != '' || inputs.account-id != '' || inputs.name-root != ''"


def _workflow() -> dict[Any, Any]:
    data: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text())
    return data


def _steps() -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _workflow()["jobs"]["release"]["steps"]
    return steps


def _index(predicate: Any) -> int:
    return next(i for i, s in enumerate(_steps()) if predicate(s))


def _step(step_id: str) -> dict[str, Any]:
    return _steps()[_index(lambda s: s.get("id") == step_id)]


def _credentials() -> int:
    return _index(lambda s: "configure-aws-credentials" in s.get("uses", ""))


def test_it_takes_the_platform_s_identity() -> None:
    inputs = _workflow()[True]["workflow_call"]["inputs"]
    for name in ("platform-image", "account-id", "name-root"):
        assert inputs[name]["default"] == "" and inputs[name]["type"] == "string"
        assert inputs[name]["required"] is False


def test_in_a_hub_the_release_role_comes_from_the_platform_s_identity() -> None:
    platform = _step("platform")
    assert platform["if"] == IDENTITY_IF
    assert platform["uses"] == "./.jaws-tool/.github/actions/platform-role"
    assert platform["with"] == {
        "platform-image": "${{ inputs.platform-image }}",
        "account-id": "${{ inputs.account-id }}",
        "name-root": "${{ inputs.name-root }}",
        "role": "release",
        "project": "${{ inputs.project }}",
        "role-arn": "${{ inputs.release-role-arn }}",
    }
    assert _step("role")["if"] == "steps.platform.outputs.arn == ''"
    creds = _steps()[_credentials()]
    assert creds["with"]["role-to-assume"] == (
        "${{ steps.platform.outputs.arn || steps.role.outputs.arn }}"
    )


def test_in_a_hub_the_cli_reads_the_platform_image_s_configuration() -> None:
    image = _index(lambda s: s.get("id") == "image")
    reconcile = _index(lambda s: s.get("name") == "jaws bot reconcile")
    assert _credentials() < image < reconcile
    assert _steps()[image]["if"] == "steps.platform.outputs.arn != ''"
    assert _steps()[image]["uses"] == "./.jaws-tool/.github/actions/platform-image"
    assert _steps()[image]["with"]["extract"] == ".jaws-platform"
    step = _steps()[reconcile]
    assert '--config "$JAWS_TOOL_CONFIG"' in step["run"]
    assert step["env"]["JAWS_INFRA_ROOT"] == "${{ steps.image.outputs.infra-root }}"
    assert step["env"]["JAWS_PLATFORM_COMMIT"] == "${{ steps.image.outputs.platform-commit }}"
    assert step["env"]["JAWS_PLATFORM_SOURCE"] == "${{ steps.image.outputs.platform-source }}"
    assert _workflow()["jobs"]["release"]["env"]["JAWS_TOOL_CONFIG"] == (
        "${{ inputs.platform-image != '' && '.jaws-platform/config' || '.jaws-tool/config' }}"
    )


def _release_role(tmp_path: Path, override: str) -> tuple[int, str]:
    fake_uv = (
        "#!/bin/bash\n"
        '[ "$1 $2 $3 $4 $5 $6" = "run --no-dev --project .jaws-tool jaws --config" ] || exit 9\n'
        '[ "$8" = config ] && [ "$9" = env ] || exit 9\n'
        f"printf '{FIXTURE}'\n"
    )
    result, output = run_step(
        "container-release.yml",
        "release",
        "role",
        cwd=tmp_path,
        env={
            "OVERRIDE": override,
            "PROJECT": "braveheart",
            "JAWS_TOOL_CONFIG": ".jaws-tool/config",
        },
        fakes={"uv": fake_uv},
    )
    return result.returncode, output


def test_without_a_platform_image_a_release_runs_as_today(tmp_path: Path) -> None:
    code, output = _release_role(tmp_path, "")
    assert code == 0
    assert output == "arn=arn:aws:iam::222222222222:role/jaws-braveheart-ci-release\n"


def test_without_a_platform_image_the_override_still_wins(tmp_path: Path) -> None:
    override = "arn:aws:iam::123456789012:role/custom"
    code, output = _release_role(tmp_path, override)
    assert code == 0
    assert output == f"arn={override}\n"
