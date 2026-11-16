"""scripts/data-access-should-apply.sh: the sweep skips only a run that would change nothing.

The script runs in data-access/ after `terraform init`; a fake `terraform` on
PATH answers `terraform output` from a JSON file standing in for the applied
state's outputs (no file: a state with no outputs yet).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "data-access-should-apply.sh"
DIGEST = "a" * 64
OTHER = "b" * 64

FAKE_TERRAFORM = """#!/usr/bin/env bash
# `terraform output -raw NAME` and `terraform output -json NAME` from $FAKE_OUTPUTS.
[[ "$1" == output ]] || exit 3
[[ -f "$FAKE_OUTPUTS" ]] || { echo "No outputs found" >&2; exit 1; }
if ! jq -e --arg n "$3" 'has($n)' "$FAKE_OUTPUTS" >/dev/null; then
  echo "Output $3 not found" >&2
  exit 1
fi
if [[ "$2" == -raw ]]; then
  jq -jr --arg n "$3" '.[$n]' "$FAKE_OUTPUTS"
else
  jq -c --arg n "$3" '.[$n]' "$FAKE_OUTPUTS"
fi
"""

NOTHING_WAITING: dict[str, Any] = {"awaiting_onboarding": [], "missing_workspaces": {}}


def _run(
    tmp_path: Path, outputs: dict[str, Any] | None, *, full: str | None = None
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "terraform"
    fake.write_text(FAKE_TERRAFORM)
    fake.chmod(0o755)
    state = tmp_path / "outputs.json"
    if outputs is not None:
        state.write_text(json.dumps(outputs))
    tfvars = tmp_path / "terraform.tfvars.json"
    tfvars.write_text(json.dumps({"fingerprint": DIGEST, "datasets": {}}))
    env = {k: v for k, v in os.environ.items() if k != "FULL"}
    env |= {"PATH": f"{bin_dir}{os.pathsep}{env['PATH']}", "FAKE_OUTPUTS": str(state)}
    if full is not None:
        env["FULL"] = full
    return subprocess.run(
        ["bash", str(SCRIPT), str(tfvars)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )


def _decision(result: subprocess.CompletedProcess[str]) -> str:
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_a_state_with_no_fingerprint_applies(tmp_path: Path) -> None:
    """The first sweep: no outputs at all."""
    assert _decision(_run(tmp_path, None)) == "apply"


def test_a_different_fingerprint_applies(tmp_path: Path) -> None:
    assert _decision(_run(tmp_path, {"fingerprint": OTHER} | NOTHING_WAITING)) == "apply"


def test_an_equal_fingerprint_with_nothing_waiting_skips(tmp_path: Path) -> None:
    assert _decision(_run(tmp_path, {"fingerprint": DIGEST} | NOTHING_WAITING)) == "skip"


def test_full_applies_even_when_the_fingerprints_match(tmp_path: Path) -> None:
    outputs = {"fingerprint": DIGEST} | NOTHING_WAITING
    assert _decision(_run(tmp_path, outputs, full="true")) == "apply"
    assert _decision(_run(tmp_path, outputs, full="false")) == "skip"


@pytest.mark.parametrize(
    "waiting",
    [
        {"awaiting_onboarding": ["braveheart-selfplay-positions"], "missing_workspaces": {}},
        {"awaiting_onboarding": [], "missing_workspaces": {"k": ["braveheart-databricks"]}},
    ],
    ids=["a dataset awaiting its location", "a consumer missing its workspace"],
)
def test_something_still_waiting_applies_though_the_fingerprints_match(
    tmp_path: Path, waiting: dict[str, Any]
) -> None:
    """Its inputs do not change when it becomes ready, so the fingerprint alone
    would never retry it."""
    assert _decision(_run(tmp_path, {"fingerprint": DIGEST} | waiting)) == "apply"


def test_a_state_without_the_waiting_outputs_applies(tmp_path: Path) -> None:
    assert _decision(_run(tmp_path, {"fingerprint": DIGEST})) == "apply"


def test_a_render_without_a_fingerprint_fails_rather_than_deciding(tmp_path: Path) -> None:
    result = _run(tmp_path, {"fingerprint": DIGEST} | NOTHING_WAITING)
    assert result.returncode == 0
    (tmp_path / "terraform.tfvars.json").write_text(json.dumps({"datasets": {}}))
    env = os.environ | {
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "FAKE_OUTPUTS": str(tmp_path / "outputs.json"),
    }
    failed = subprocess.run(
        ["bash", str(SCRIPT), str(tmp_path / "terraform.tfvars.json")],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert failed.returncode != 0
    assert failed.stdout.strip() not in ("apply", "skip")
