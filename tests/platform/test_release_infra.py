"""release-infra/ spells the owner's values itself (spec 6.8), so check them against config/
while it exists; each failure names the field, never the value.
"""

from __future__ import annotations

import re

import pytest

from jaws.settings import load_settings
from tests.conftest import PLATFORM_CONFIG_DIR
from tests.test_release_infra import ROOT
from tests.workflow_steps import hcl_values


def test_its_state_is_in_the_platform_s_state_bucket() -> None:
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    if hcl_values(ROOT / "backend" / "prod.hcl")["bucket"] != settings.state.bucket:
        pytest.fail(
            "release-infra/backend/prod.hcl does not name config/'s state.bucket", pytrace=False
        )


def test_it_is_in_the_primary_account() -> None:
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    primary = settings.aws.accounts[settings.aws.primary].account_id
    found = re.findall(r'account_id\s*=\s*"([^"]*)"', (ROOT / "main.tf").read_text())
    if found != [primary]:
        pytest.fail(
            "release-infra/main.tf's account_id is not config/aws.yaml's primary account's",
            pytrace=False,
        )


def _local_repository() -> dict[str, str]:
    """The `name`, `owner_id` and `repository_id` inside `local.repository`."""
    text = (ROOT / "main.tf").read_text()
    block = re.search(r"repository\s*=\s*\{([^}]*)\}", text)
    assert block, "main.tf has no local.repository"
    return dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', block.group(1)))


def test_it_trusts_this_repository() -> None:
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    repository = settings.platform.repositories[0]
    expected = {
        "name": repository.repository,
        "owner_id": repository.owner_id,
        "repository_id": repository.repository_id,
    }
    found = _local_repository()
    for field, value in expected.items():
        if found.get(field) != value:
            pytest.fail(
                f"release-infra/main.tf's local.repository.{field} differs from "
                "platform.repositories[0] in config/",
                pytrace=False,
            )


def test_the_publishing_role_is_outside_the_platform_s_name_root() -> None:
    """The foundation's apply role manages every <name_root>-* role (jaws-ci's foundation/manage).

    A role named inside the name root would be one that role could reshape.
    """
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    text = (ROOT / "main.tf").read_text()
    module = text.split('module "publish_role"', 1)[1]
    name = re.search(r'\bname\s*=\s*"([^"]*)"', module)
    assert name, "main.tf's publish_role has no name"
    assert name.group(1) == "release-infra-publish"
    if name.group(1).startswith(f"{settings.context.name_root}-"):
        pytest.fail(
            "release-infra/main.tf's publishing role name starts with config/'s context.name_root",
            pytrace=False,
        )
