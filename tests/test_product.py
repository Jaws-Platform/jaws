from __future__ import annotations

from pathlib import Path

import pytest

from jaws.errors import ConfigError
from jaws.product import PLAN_COMMENT_MAX_BYTES, load_product_pins, product_pins


def test_the_release_pins_terraform_and_every_family() -> None:
    pins = product_pins()
    assert pins.terraform_version == "1.14.7"
    assert pins.families["Jaws-Platform/jaws-ci/aws"] == "0.4.0"
    assert pins.families["Jaws-Platform/jaws-monitoring/aws"] == "0.8.2"
    assert len(pins.families) == 8


def test_the_comment_size_is_the_release_s() -> None:
    assert PLAN_COMMENT_MAX_BYTES == 60000


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            "terraform: {version: '1.14'}\nlibrary: {families: {a/b/aws: 0.1.0}}\n",
            "terraform.version",
        ),
        ("terraform: {version: 1.14.7}\nlibrary: {families: {}}\n", "library.families"),
        (
            "terraform: {version: 1.14.7}\nlibrary: {families: {not-an-address: 0.1.0}}\n",
            "registry address",
        ),
        (
            "terraform: {version: 1.14.7}\nlibrary: {families: {a/b/aws: '~> 0.1'}}\n",
            "exact version",
        ),
    ],
)
def test_a_malformed_release_file_is_refused(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "product.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_product_pins(path)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("library: {families: {a/b/aws: 0.1.0}}\n", "terraform.version"),
        ("", "mapping at the top level"),
        ("- a\n- b\n", "mapping at the top level"),
        ("terraform: [unclosed\n", "cannot be read as YAML"),
    ],
)
def test_a_structurally_broken_release_file_is_refused(
    tmp_path: Path, text: str, message: str
) -> None:
    path = tmp_path / "product.yaml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_product_pins(path)


def test_the_cached_pins_cannot_be_mutated() -> None:
    with pytest.raises(TypeError):
        product_pins().families["a/b/aws"] = "0.0.1"  # type: ignore[index]
