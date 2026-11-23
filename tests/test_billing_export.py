"""The organization's AWS billing export (billing-export/) stays the owner's.

The root creates the org-wide FOCUS export in the management account, where
AWS Organizations and IAM Identity Center are, so only the owner applies it,
from their own shell, as with owner-access/. No CI role may plan or apply it:
no workflow assumes a role for it, no foundation role or state prefix names it,
and its state lives beside owner-access's, in the management account's
owner-only bucket, never in the shared state bucket the CI roles reach.
"""

from __future__ import annotations

import re

import yaml

from tests.conftest import REPO_ROOT, onboarded, repo_config

RESERVED = "billing-export"
ROOT = REPO_ROOT / RESERVED
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def test_no_project_is_registered_under_the_billing_export_key() -> None:
    assert RESERVED not in onboarded(repo_config()), (
        f"`{RESERVED}` is reserved: its CI roles would get the export's state prefix"
    )


def test_the_state_lives_in_the_management_accounts_owner_only_bucket() -> None:
    backend = (ROOT / "backend" / "prod.hcl").read_text()
    assert f'key          = "project={RESERVED}/env=prod/{RESERVED}-prod.tfstate"' in backend


def test_ci_never_plans_or_applies_billing_export() -> None:
    """CI may only validate, test and lint the root; no job assumes a role for it."""
    mentions = [w.name for w in WORKFLOWS.glob("*.yml") if RESERVED in w.read_text()]
    assert set(mentions) <= {"ci.yml"}, mentions
    if not mentions:
        return
    for name, job in yaml.safe_load((WORKFLOWS / "ci.yml").read_text())["jobs"].items():
        if RESERVED not in yaml.safe_dump(job):
            continue
        assert "id-token" not in job.get("permissions", {}), name
        for step in job["steps"]:
            assert "configure-aws-credentials" not in step.get("uses", ""), name
            assert not re.search(r"terraform (plan|apply|destroy)", step.get("run", "")), name


def test_no_foundation_role_or_state_prefix_names_billing_export() -> None:
    """The foundation's Databricks job (databricks-billing-export) is another name."""
    for path in sorted((REPO_ROOT / "foundation").glob("*.tf")):
        text = path.read_text()
        assert f"project={RESERVED}" not in text, path.name
        assert f'"{RESERVED}"' not in text, path.name
