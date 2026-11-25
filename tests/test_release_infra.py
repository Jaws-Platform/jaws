"""Jaws's release infrastructure (release-infra/) stays the owner's.

The root creates the ECR Public repository and the one role that pushes to it
and prunes it, in the production account (spec 6.8, ruling 14), applied only by
the owner. No workflow assumes a role for it, and no foundation role or state
prefix names it. A project registered under its key would get its state prefix.
It reads nothing outside its folder, since it stays in `jaws` when `config/`
leaves. Its checks against the owner's values are in
tests/platform/test_release_infra.py.
"""

from __future__ import annotations

from tests.conftest import REPO_ROOT, onboarded, repo_config
from tests.workflow_steps import hcl_values, job, required_checks, workflows_that_only_check

RESERVED = "release-infra"
ROOT = REPO_ROOT / RESERVED


def test_no_project_is_registered_under_the_release_infra_key() -> None:
    """The fixture's registry; tests/platform/test_owner_rules.py checks the owner's."""
    assert RESERVED not in onboarded(repo_config()), (
        f"`{RESERVED}` is reserved: its CI roles would get the publishing infrastructure's state"
    )


def test_its_state_has_its_own_prefix() -> None:
    values = hcl_values(ROOT / "backend" / "prod.hcl")
    assert values["key"] == f"project={RESERVED}/env=prod/{RESERVED}-prod.tfstate"
    assert values["region"] == "us-east-1"
    assert sorted(p.name for p in (ROOT / "backend").iterdir()) == ["prod.hcl"]


def test_ci_never_plans_or_applies_release_infra() -> None:
    assert workflows_that_only_check(RESERVED) == ["ci.yml"]


def test_its_ci_check_is_required() -> None:
    check = "Release infrastructure validate, tflint, test"
    assert job("ci.yml", "release-infra-stack")["name"] == check
    assert check in required_checks()


def test_no_foundation_role_or_state_prefix_names_release_infra() -> None:
    for path in sorted((REPO_ROOT / "foundation").glob("*.tf")):
        text = path.read_text()
        assert f"project={RESERVED}" not in text, path.name
        assert RESERVED not in text, path.name


def test_it_reads_nothing_outside_its_folder() -> None:
    for path in sorted(ROOT.glob("*.tf")):
        assert "../" not in path.read_text(), path.name


def test_it_never_enters_the_image() -> None:
    assert RESERVED in (REPO_ROOT / ".dockerignore").read_text().splitlines()
