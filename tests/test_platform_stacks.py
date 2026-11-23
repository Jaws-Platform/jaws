"""Where the platform's stacks find their configuration.

The foundation and monitoring read the tool configuration where the CLI does:
`/etc/jaws/config` in the hub's image, else `config/` at the repository root
(`jaws.settings.IMAGE_CONFIG_PATH`), and the foundation reads the datasets
registry beside it. A caller overrides both with `TF_VAR_config_path` and
`TF_VAR_datasets_path`. The two stacks carry the same configuration-reading
locals, which must not drift apart.
"""

from __future__ import annotations

import re

import pytest

from jaws.settings import IMAGE_CONFIG_PATH, load_settings
from tests.conftest import CONFIG_DIR, REPO_ROOT


@pytest.mark.parametrize("stack", ["foundation", "monitoring"])
def test_a_stack_looks_for_the_image_s_configuration_where_the_cli_does(stack: str) -> None:
    text = (REPO_ROOT / stack / "config.tf").read_text()
    assert re.findall(r'image_config_path\s*=\s*"([^"]+)"', text) == [str(IMAGE_CONFIG_PATH)]


def _config_locals(stack: str) -> str:
    """The locals from `image_config_path` to `tool_config`, which both stacks share."""
    text = (REPO_ROOT / stack / "config.tf").read_text()
    match = re.search(r"^\s*image_config_path\b.*?^\s*tool_config\b[^\n]*\n", text, re.S | re.M)
    assert match, stack
    return match.group(0)


def test_the_two_stacks_read_their_configuration_identically() -> None:
    assert _config_locals("foundation") == _config_locals("monitoring")


def test_data_access_reads_only_what_the_cli_renders() -> None:
    """data-access/'s variables are `jaws access render`'s, from the CLI's config and datasets."""
    for path in sorted((REPO_ROOT / "data-access").glob("*.tf")):
        text = path.read_text()
        assert not any(word in text for word in ("yamldecode", "../config", "../datasets")), (
            path.name
        )


def _owner_values() -> set[str]:
    """What identifies the owner in config/:
    - every account ID;
    - the zone, its ID, its TXT names and values;
    - context.owner;
    - the platform repositories' IDs.
    Not context.organization (Jaws-Platform, the vendor's name) or repository
    names: module sources share them."""
    settings = load_settings(CONFIG_DIR, environ={})
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
        assert not found, (
            f"{path.relative_to(REPO_ROOT)} holds values from config/ that identify the owner"
        )
