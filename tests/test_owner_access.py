"""The owner's Identity Center access (owner-access/) keeps its state out of
every CI role's reach.

foundation/state.tf gives each registered site, bot and Databricks project's
CI roles read and write on `project=<key>/` in the state bucket. The
owner-access stack's state lives under `project=owner-access/`, which only the
break-glass principals may reach because no project is registered under that
key. Registering one would hand its CI roles the owner's admin-access state.
"""

from __future__ import annotations

import re

import yaml

from tests.conftest import REPO_ROOT, onboarded, repo_config

RESERVED = "owner-access"


def registered_keys() -> set[str]:
    """Every project onboarded in config/projects.yaml, the one registry."""
    return set(onboarded(repo_config()))


def test_registries_parse_known_projects() -> None:
    assert {"main-site", "braveheart", "braveheart-databricks"} <= registered_keys()


def test_no_project_is_registered_under_the_owner_access_key() -> None:
    assert RESERVED not in registered_keys(), (
        f"`{RESERVED}` is reserved: its state prefix holds the owner's admin access"
    )


def test_owner_access_state_key_is_the_reserved_prefix() -> None:
    backend = (REPO_ROOT / "owner-access" / "backend" / "prod.hcl").read_text()
    assert f'key          = "project={RESERVED}/env=prod/{RESERVED}-prod.tfstate"' in backend
    assert 'bucket       = "jaws-owner-access-state-650503560686"' in backend


def test_ci_never_plans_or_applies_owner_access() -> None:
    """CI only validates, tests and lints the stack; no job assumes a role for it."""
    workflows = REPO_ROOT / ".github" / "workflows"
    mentions = [w.name for w in workflows.glob("*.yml") if RESERVED in w.read_text()]
    assert mentions == ["ci.yml"], mentions

    job = yaml.safe_load((workflows / "ci.yml").read_text())["jobs"]["owner-access-stack"]
    assert "id-token" not in job.get("permissions", {})
    for step in job["steps"]:
        assert "configure-aws-credentials" not in step.get("uses", "")
        assert not re.search(r"terraform (plan|apply|destroy)", step.get("run", ""))
