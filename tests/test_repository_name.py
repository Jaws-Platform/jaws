"""The repository is `Jaws-Platform/jaws`, and its workflows say so.

A reusable workflow runs in the consumer's repository and checks this one out
beside it, at the workflow's own commit. That checkout names the repository
and a directory; both are checked here, because a wrong name only fails in a
consumer's run, never in this repository's own CI.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import yaml

from tests.conftest import REPO_ROOT

WORKFLOWS = REPO_ROOT / ".github" / "workflows"
REPOSITORY = "Jaws-Platform/jaws"
#: Where a reusable workflow checks the tool out, in the consumer's workspace.
#: Not `.jaws`: that is the artifacts directory the tool writes there.
TOOL_DIR = ".jaws-tool"


def _steps() -> Iterator[tuple[str, dict[str, Any]]]:
    for path in sorted(WORKFLOWS.glob("*.yml")):
        data: dict[Any, Any] = yaml.safe_load(path.read_text())
        for job in data["jobs"].values():
            for step in job.get("steps", []):
                yield path.name, step


def _self_checkouts() -> list[tuple[str, dict[str, Any]]]:
    """Checkouts of a repository named literally (an expression names a consumer's)."""
    return [
        (name, step)
        for name, step in _steps()
        if str(step.get("uses", "")).startswith("actions/checkout")
        and "repository" in step.get("with", {})
        and "${{" not in step["with"]["repository"]
    ]


def test_every_literal_checkout_is_of_this_repository_under_its_name() -> None:
    checkouts = _self_checkouts()
    assert len(checkouts) >= 5, "the reusable workflows check the tool out"
    for name, step in checkouts:
        assert step["with"]["repository"] == REPOSITORY, name
        assert step["with"]["path"] == TOOL_DIR, name
        assert step["with"]["ref"] == "${{ job.workflow_sha }}", name


def test_no_step_uses_the_old_checkout_directory() -> None:
    for name, step in _steps():
        assert ".jwall-engineering-infra" not in yaml.safe_dump(step), f"{name}: {step.get('name')}"


def test_the_tool_directory_is_not_the_artifacts_directory() -> None:
    from jaws.log import ARTIFACTS_DIR

    assert str(ARTIFACTS_DIR) != TOOL_DIR
    for name, step in _steps():
        uses = str(step.get("uses", ""))
        if uses.startswith("./") and "/.github/actions/jaws" in uses:
            assert uses == f"./{TOOL_DIR}/.github/actions/jaws", name
