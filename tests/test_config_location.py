"""Where the CLI looks for its configuration, and what it says when it finds none."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

import jaws.settings
from jaws.errors import ConfigError
from jaws.settings import NO_CONFIGURATION, load_settings
from tests.conftest import CONFIG_DIR


def test_the_configuration_a_platform_s_image_holds_is_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What every jaws-cli caller runs: no JAWS_CONFIG, the image's directory, and no
    ./config in the working directory."""
    image_config = tmp_path / "image" / "etc" / "jaws" / "config"
    shutil.copytree(CONFIG_DIR, image_config)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JAWS_CONFIG", raising=False)
    monkeypatch.setattr(jaws.settings, "IMAGE_CONFIG_PATH", image_config)
    assert load_settings(environ={}) == load_settings(CONFIG_DIR, environ={})


def test_the_configuration_in_the_working_directory_is_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A checkout run outside any image: no JAWS_CONFIG, no image directory, and the
    configuration at ./config."""
    shutil.copytree(CONFIG_DIR, tmp_path / "config")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JAWS_CONFIG", raising=False)
    monkeypatch.setattr(jaws.settings, "IMAGE_CONFIG_PATH", tmp_path / "no-image-config")
    assert load_settings(environ={}) == load_settings(CONFIG_DIR, environ={})


def test_without_a_configuration_the_cli_says_where_it_looks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("JAWS_CONFIG", raising=False)
    monkeypatch.setattr(jaws.settings, "IMAGE_CONFIG_PATH", tmp_path / "no-image-config")
    with pytest.raises(ConfigError) as raised:
        load_settings(environ={})
    assert str(raised.value) == NO_CONFIGURATION
    assert "JAWS_CONFIG" in NO_CONFIGURATION and "/etc/jaws/config" in NO_CONFIGURATION


@pytest.mark.parametrize("given", ["missing", "config"])
def test_a_configuration_given_but_missing_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, given: str
) -> None:
    """JAWS_CONFIG=config is a path given, though it is also the default's name."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JAWS_CONFIG", given)
    with pytest.raises(ConfigError, match=re.escape(f"tool configuration not found at {given}")):
        load_settings(environ={})
