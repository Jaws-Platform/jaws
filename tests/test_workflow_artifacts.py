"""Every artifact upload of a hidden path asks for hidden files.

actions/upload-artifact skips files and directories whose names start with a dot
unless `include-hidden-files: true`. The CLI writes its run log, plan, plan
comment, checks and outputs to `.jaws/`, and the failure messages and docs send
readers to "the workflow run's artifacts"; without the flag every such upload
was silently empty.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import yaml

from tests.conftest import REPO_ROOT

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def _uploads() -> Iterator[tuple[str, str, dict[str, Any]]]:
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        workflow: dict[Any, Any] = yaml.safe_load(path.read_text())
        for job_name, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps", []):
                if "actions/upload-artifact" in str(step.get("uses", "")):
                    yield path.name, job_name, step


def _hidden(paths: str) -> bool:
    lines = [line.strip().lstrip("!") for line in paths.splitlines() if line.strip()]
    return any(line.startswith(".") or "/." in line for line in lines)


def test_every_upload_of_a_hidden_path_includes_hidden_files() -> None:
    hidden = [(f, j, s) for f, j, s in _uploads() if _hidden(str(s["with"]["path"]))]
    assert len(hidden) >= 10, "the CLI's .jaws/ uploads were not found"
    missing = [
        f"{f}:{j}" for f, j, s in hidden if s["with"].get("include-hidden-files") is not True
    ]
    assert missing == [], f"upload-artifact skips dot paths without include-hidden-files: {missing}"
