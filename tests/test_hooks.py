"""The local git hooks catch what CI would, before a pull request exists.

`pre-commit install` installs three hook types: pre-commit (format, validate,
lint), commit-msg (commitlint) and pre-push (the slow checks: mypy, pytest, the
three roots' `terraform test` and the stacks' mock plans, each only for the
parts the push changes). CI stays the authoritative check, and runs them all.
"""

from __future__ import annotations

import os
from typing import Any

import yaml

from tests.conftest import REPO_ROOT

CONFIG = REPO_ROOT / ".pre-commit-config.yaml"


def _config() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(CONFIG.read_text())
    return data


def _hooks() -> dict[str, dict[str, Any]]:
    return {h["id"]: h for repo in _config()["repos"] for h in repo["hooks"]}


def test_install_sets_up_every_hook_type() -> None:
    assert set(_config()["default_install_hook_types"]) == {"pre-commit", "commit-msg", "pre-push"}
    # The fast hooks run at commit; a push runs only the slow checks.
    assert _config()["default_stages"] == ["pre-commit"]


def test_the_slow_checks_run_before_a_push() -> None:
    hooks = _hooks()
    expected = {
        "mypy": "uv run mypy",
        "pytest": "uv run pytest",
        "terraform-test-foundation": "cd foundation",
        "terraform-test-data-access": "cd data-access",
        "terraform-test-owner-access": "cd owner-access",
        "stack-plans": "scripts/test-stack-plans.sh",
    }
    for hook_id, command in expected.items():
        hook = hooks[hook_id]
        assert hook["stages"] == ["pre-push"], hook_id
        assert command in hook["entry"], hook_id
        assert hook["pass_filenames"] is False, hook_id
        assert hook.get("files"), f"{hook_id} runs only for the parts a push changes"


def test_the_ruff_hook_matches_the_ruff_ci_runs() -> None:
    ruff = next(r for r in _config()["repos"] if r["repo"].endswith("ruff-pre-commit"))
    lock = (REPO_ROOT / "uv.lock").read_text()
    locked = lock.split('name = "ruff"\nversion = "', 1)[1].split('"', 1)[0]
    assert ruff["rev"] == f"v{locked}"


def test_tests_run_as_the_owners_shell_whatever_runs_them() -> None:
    """CI sets GITHUB_ACTIONS, GITHUB_OUTPUT and friends; a test must behave the
    same locally and there (tests/conftest.py clears them for every test)."""
    leaked = sorted(k for k in os.environ if k == "CI" or k.startswith(("GITHUB_", "RUNNER_")))
    assert leaked == []
