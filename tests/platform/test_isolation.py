"""Only tests/platform/ reads the owner's configuration; every other test uses the fixture."""

from __future__ import annotations

from tests.conftest import REPO_ROOT


def test_only_platform_checks_read_the_owner_s_configuration() -> None:
    """tests/platform/ checks the owner's config/; every other test uses the fixture."""
    tests = REPO_ROOT / "tests"
    readers = sorted(
        path.relative_to(tests).as_posix()
        for path in tests.rglob("*.py")
        if path.relative_to(tests).parts[0] != "platform"
        and (
            "PLATFORM_CONFIG_DIR" in path.read_text() or 'REPO_ROOT / "config"' in path.read_text()
        )
    )
    assert readers == ["conftest.py"]
