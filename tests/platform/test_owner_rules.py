"""Rules the product's tests check on the fixture, checked here on the owner's own registry.

Each failure names a count, never a project key or any other value from config/.
"""

from __future__ import annotations

from typing import Any

import pytest

from jaws.settings import load_document
from tests.conftest import PLATFORM_CONFIG_DIR
from tests.test_billing_export import RESERVED as BILLING_EXPORT
from tests.test_bots_registry import MAX_PROJECT_KEY, MAX_RESEARCH_PROJECT_KEY
from tests.test_monitoring_stack import RESERVED as MONITORING
from tests.test_owner_access import RESERVED as OWNER_ACCESS
from tests.test_release_infra import RESERVED as RELEASE_INFRA


def _projects() -> dict[str, dict[str, Any]]:
    """The owner's onboarded projects by key."""
    document = load_document(PLATFORM_CONFIG_DIR)
    return {
        key: project
        for group in document["projects"].values()
        for key, project in group["projects"].items()
    }


@pytest.mark.parametrize("reserved", [OWNER_ACCESS, BILLING_EXPORT, MONITORING, RELEASE_INFRA])
def test_no_project_takes_a_reserved_key(reserved: str) -> None:
    """A reserved key is a root's state prefix and CI-role name (config/projects.yaml)."""
    if reserved in _projects():
        pytest.fail(
            "config/projects.yaml registers a project under a reserved root key", pytrace=False
        )


def test_registered_keys_fit_the_apply_policy_size() -> None:
    """The limit behind a real LimitExceeded apply failure (see tests/test_bots_registry.py)."""
    too_long = [
        key
        for key, project in _projects().items()
        if project["type"] in ("bot", "research")
        and len(key)
        > (MAX_RESEARCH_PROJECT_KEY if project["type"] == "research" else MAX_PROJECT_KEY)
    ]
    if too_long:
        pytest.fail(
            f"config/projects.yaml has {len(too_long)} project keys over the apply policy limit",
            pytrace=False,
        )
