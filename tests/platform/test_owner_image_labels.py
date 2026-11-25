"""The owner's engine labels stay in the owner's namespace."""

from __future__ import annotations

import pytest

from jaws import image
from jaws.settings import load_settings
from tests.conftest import PLATFORM_CONFIG_DIR


def test_the_owner_s_label_namespace_is_unchanged() -> None:
    zone = load_settings(PLATFORM_CONFIG_DIR, environ={}).dns.zone
    unchanged = image.label_namespace(zone) == "engineering.jwall"
    if not unchanged:
        pytest.fail("the owner's image label namespace changed", pytrace=False)
