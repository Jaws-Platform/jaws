"""Checks of the owner's own configuration that the product's tests used to make."""

from __future__ import annotations

from tests.conftest import PLATFORM_CONFIG_DIR, REPO_ROOT


def test_the_engine_s_old_project_name_is_gone() -> None:
    """The engine's project was `rusty-chess` until 2026-11-15; the old name is gone."""
    text = "".join(path.read_text() for path in sorted(PLATFORM_CONFIG_DIR.glob("*.yaml")))
    assert "rusty-chess" not in text


def test_the_action_reads_the_config_beside_it() -> None:
    action = REPO_ROOT / ".github" / "actions" / "jaws"
    assert (action / ".." / ".." / ".." / "config").resolve() == PLATFORM_CONFIG_DIR.resolve()
