"""The platform's stacks hold no value of the owner's configuration."""

from __future__ import annotations

import pytest

from jaws.settings import load_settings
from tests.conftest import PLATFORM_CONFIG_DIR, REPO_ROOT


def _owner_values() -> set[str]:
    """What identifies the owner in config/:
    - every account ID;
    - the zone, its ID, its TXT names and values;
    - context.owner;
    - the platform repositories' IDs.
    Not context.organization (Jaws-Platform, the vendor's name) or repository
    names: module sources share them."""
    settings = load_settings(PLATFORM_CONFIG_DIR, environ={})
    values = {account.account_id for account in settings.aws.accounts.values()}
    values |= {settings.dns.zone, settings.dns.zone_id, settings.context.owner}
    for name, records in settings.dns.txt_records.items():
        values.add(name)
        values.update(records)
    for repository in settings.platform.repositories:
        values |= {repository.owner_id, repository.repository_id}
    return {value for value in values if value}


@pytest.mark.parametrize("stack", ["foundation", "monitoring", "data-access"])
def test_a_platform_stack_holds_no_owner_value(stack: str) -> None:
    for path in sorted((REPO_ROOT / stack).glob("*.tf")):
        found = sorted(value for value in _owner_values() if value in path.read_text())
        if found:
            pytest.fail(
                f"{path.relative_to(REPO_ROOT)} holds {len(found)} values from config/ "
                "that identify the owner",
                pytrace=False,
            )
